from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .db import (
    append_failure,
    open_db,
    purge_notebook_state,
    remove_source_state,
    upsert_notebook,
    upsert_source,
)
from .frontmatter import (
    extract_source_payload,
    managed_body_for_export,
    managed_body_for_sync,
    render_markdown_with_frontmatter,
)
from .nlm import parse_id_from_output, run_nlm
from .utils import (
    NOTEBOOK_META_NAME,
    STATE_DIR_NAME,
    SyncPaths,
    ensure_unique_path,
    json_dump,
    json_load,
    log,
    paths_for,
    sanitize_name,
    sha256_text,
    short_id,
)


# ── folder / file helpers ──────────────────────────────────────────────
def organize_loose_files(vault: Path) -> int:
    """Move loose .md files in vault root into auto-created folders."""
    moved = 0
    for file_path in list_markdown_files(vault):
        folder_name = sanitize_name(file_path.stem, f"untitled-{short_id('loose')}")
        folder = ensure_unique_path(vault / folder_name)
        folder.mkdir(parents=True, exist_ok=True)
        new_path = folder / file_path.name
        file_path.rename(new_path)
        log(f"Organized: {file_path.name} -> {folder.name}/")
        moved += 1
    return moved


def iter_notebook_folders(vault: Path) -> Iterable[Path]:
    for child in sorted(vault.iterdir()):
        if child.name == STATE_DIR_NAME:
            continue
        if child.is_dir():
            yield child


def list_markdown_files(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".md" and not p.name.startswith(".")
    )


# ── notebook lifecycle ─────────────────────────────────────────────────
def ensure_notebook(
    folder: Path, conn, remote_notebook_ids: set[str]
) -> tuple[str, str, int]:
    metadata_path = folder / NOTEBOOK_META_NAME
    folder_title = folder.name
    changes = 0

    if metadata_path.exists():
        meta = json_load(metadata_path)
        notebook_id = meta["notebook_id"]
        if notebook_id not in remote_notebook_ids:
            log(f"Stale notebook {short_id(notebook_id)}, recreating: {folder_title}")
            purge_notebook_state(conn, notebook_id)
            metadata_path.unlink(missing_ok=True)
            # Fall through to create new notebook below
        else:
            current_title = meta.get("title") or folder_title
            if current_title != folder_title:
                run_nlm(["rename", "notebook", notebook_id, "--", folder_title], expect_json=False)
                meta["title"] = folder_title
                json_dump(meta, metadata_path)
                changes += 1
            upsert_notebook(
                conn,
                notebook_id=notebook_id,
                title=folder_title,
                folder_path=folder,
                metadata_path=metadata_path,
                created_via="obsidian",
            )
            return notebook_id, folder_title, changes

    create_output = run_nlm(["notebook", "create", "--", folder_title], expect_json=False)
    notebook_id = parse_id_from_output(create_output)
    json_dump({"notebook_id": notebook_id, "title": folder_title}, metadata_path)
    upsert_notebook(
        conn,
        notebook_id=notebook_id,
        title=folder_title,
        folder_path=folder,
        metadata_path=metadata_path,
        created_via="obsidian",
    )
    log(f"Created notebook: {folder_title} ({notebook_id})")
    return notebook_id, folder_title, 1


def force_delete_notebook(
    conn, sp: SyncPaths, notebook_id: str, folder_path: str, *, reason: str
) -> int:
    try:
        run_nlm(["notebook", "delete", notebook_id, "--confirm"], expect_json=False)
        log(f"Deleted notebook from NLM: {folder_path}")
    except Exception as exc:
        append_failure(
            sp,
            {
                "kind": "forced_notebook_delete",
                "notebook_id": notebook_id,
                "folder_path": folder_path,
                "reason": reason,
                "error": str(exc),
            },
        )
        log(f"Failed notebook delete, pruning local state anyway: {folder_path}")
    affected = conn.execute("SELECT COUNT(*) FROM sources WHERE notebook_id = ?", (notebook_id,)).fetchone()[0]
    purge_notebook_state(conn, notebook_id)
    return affected + 1


# ── source lifecycle ───────────────────────────────────────────────────
def add_or_update_source(
    folder: Path, file_path: Path, notebook_id: str, conn
) -> tuple[str | None, int]:
    if not file_path.exists():
        return None, 0
    meta, body = extract_source_payload(file_path)
    canonical_title = file_path.stem
    managed_body = managed_body_for_sync(body or file_path.read_text(encoding="utf-8"))
    content_hash = sha256_text(managed_body)
    changes = 0

    source_id = meta.get("nlm_source_id")
    source_url = meta.get("nlm_source_url") or None
    source_type = meta.get("nlm_source_type") or "text"

    if not source_id:
        add_output = run_nlm(
            ["source", "add", notebook_id, "--text", managed_body, "--title", canonical_title, "--wait"],
            expect_json=False,
        )
        source_id = parse_id_from_output(add_output)
        new_meta = {
            "nlm_notebook_id": notebook_id,
            "nlm_source_id": source_id,
            "nlm_source_type": source_type,
            "nlm_source_url": source_url or "",
        }
        file_path.write_text(render_markdown_with_frontmatter(new_meta, managed_body), encoding="utf-8")
        upsert_source(
            conn,
            source_id=source_id,
            notebook_id=notebook_id,
            title=canonical_title,
            file_path=file_path,
            source_type=source_type,
            source_url=source_url,
            content_hash=content_hash,
            created_via="obsidian",
        )
        log(f"Created source: {file_path}")
        return source_id, 1

    existing = conn.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
    if existing is None:
        upsert_source(
            conn,
            source_id=source_id,
            notebook_id=notebook_id,
            title=canonical_title,
            file_path=file_path,
            source_type=source_type,
            source_url=source_url,
            content_hash=content_hash,
            created_via="obsidian",
        )
        existing = conn.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()

    if existing["notebook_id"] != notebook_id:
        run_nlm(["source", "delete", source_id, "--confirm"], expect_json=False)
        add_output = run_nlm(
            ["source", "add", notebook_id, "--text", managed_body, "--title", canonical_title, "--wait"],
            expect_json=False,
        )
        source_id = parse_id_from_output(add_output)
        meta["nlm_source_id"] = source_id
        meta["nlm_notebook_id"] = notebook_id
        file_path.write_text(render_markdown_with_frontmatter(meta, managed_body), encoding="utf-8")
        remove_source_state(conn, existing["source_id"])
        upsert_source(
            conn,
            source_id=source_id,
            notebook_id=notebook_id,
            title=canonical_title,
            file_path=file_path,
            source_type=source_type,
            source_url=source_url,
            content_hash=content_hash,
            created_via="obsidian",
        )
        log(f"Moved source to notebook: {file_path}")
        return source_id, 1

    if existing["title"] != canonical_title:
        run_nlm(["rename", "source", source_id, "--notebook", notebook_id, "--", canonical_title], expect_json=False)
        changes += 1

    if existing["content_hash"] != content_hash:
        run_nlm(["source", "delete", source_id, "--confirm"], expect_json=False)
        add_output = run_nlm(
            ["source", "add", notebook_id, "--text", managed_body, "--title", canonical_title, "--wait"],
            expect_json=False,
        )
        new_source_id = parse_id_from_output(add_output)
        meta["nlm_source_id"] = new_source_id
        meta["nlm_notebook_id"] = notebook_id
        file_path.write_text(render_markdown_with_frontmatter(meta, managed_body), encoding="utf-8")
        remove_source_state(conn, source_id)
        source_id = new_source_id
        log(f"Rebuilt source after content change: {file_path}")
        changes += 1

    upsert_source(
        conn,
        source_id=source_id,
        notebook_id=notebook_id,
        title=canonical_title,
        file_path=file_path,
        source_type=source_type,
        source_url=source_url,
        content_hash=content_hash,
        created_via="obsidian",
    )
    return source_id, changes


# ── scan (core sync logic) ─────────────────────────────────────────────
def scan_once(args) -> int:
    sp = paths_for(Path(args.vault))
    sp.vault.mkdir(parents=True, exist_ok=True)
    conn = open_db(sp.state_db)

    changes = 0
    live_notebooks: set[str] = set()
    live_sources: set[str] = set()
    local_sources_by_notebook: dict[str, set[str]] = {}

    # Organize loose .md files in vault root into their own folders
    organize_loose_files(sp.vault)

    # Fetch remote state first so ensure_notebook can validate stale IDs
    remote_notebooks = run_nlm(["notebook", "list", "--json"], timeout_seconds=180)
    remote_notebook_ids = {row["id"] for row in remote_notebooks}

    # Phase 1: sync local folders -> NLM (isolated per-folder error handling)
    for folder in iter_notebook_folders(sp.vault):
        try:
            notebook_id, _, notebook_changes = ensure_notebook(folder, conn, remote_notebook_ids)
            changes += notebook_changes
            live_notebooks.add(notebook_id)
            local_sources_by_notebook.setdefault(notebook_id, set())
            for file_path in list_markdown_files(folder):
                try:
                    source_id, source_changes = add_or_update_source(folder, file_path, notebook_id, conn)
                    changes += source_changes
                    if source_id:
                        live_sources.add(source_id)
                        local_sources_by_notebook[notebook_id].add(source_id)
                except Exception as exc:
                    log(f"  Failed to sync source {file_path.name}: {exc}")
                    append_failure(
                        sp,
                        {
                            "kind": "source_sync",
                            "folder": folder.name,
                            "file": file_path.name,
                            "error": str(exc),
                        },
                    )
        except Exception as exc:
            log(f"Failed to sync folder {folder.name}: {exc}")
            append_failure(
                sp,
                {"kind": "folder_sync", "folder": folder.name, "error": str(exc)},
            )

    # Phase 2: delete remote-only notebooks (exist in NLM but not locally)
    for remote_notebook in remote_notebooks:
        notebook_id = remote_notebook["id"]
        if notebook_id in live_notebooks:
            continue
        changes += force_delete_notebook(
            conn,
            sp,
            notebook_id,
            remote_notebook.get("title") or notebook_id,
            reason="remote_notebook_missing_locally",
        )

    # Phase 3: delete remote-only sources within synced notebooks
    for notebook_id in list(live_notebooks):
        try:
            remote_sources = run_nlm(["source", "list", notebook_id, "--json"], timeout_seconds=180)
        except Exception as exc:
            log(f"Failed to list remote sources for {notebook_id}: {exc}")
            append_failure(
                sp,
                {"kind": "remote_source_list", "notebook_id": notebook_id, "error": str(exc)},
            )
            continue
        local_ids = local_sources_by_notebook.get(notebook_id, set())
        for remote_source in remote_sources:
            remote_source_id = remote_source["id"]
            if remote_source_id in local_ids:
                continue
            try:
                run_nlm(["source", "delete", remote_source_id, "--confirm"], expect_json=False)
                log(f"Deleted remote-only source: {remote_source_id} in notebook {notebook_id}")
                changes += 1
            except Exception as exc:
                log(f"Failed to delete remote source {remote_source_id}: {exc}")
                append_failure(
                    sp,
                    {
                        "kind": "remote_source_delete",
                        "notebook_id": notebook_id,
                        "source_id": remote_source_id,
                        "error": str(exc),
                    },
                )

    # Phase 4: clean up stale DB entries for notebooks no longer tracked
    for row in conn.execute("SELECT notebook_id FROM notebooks").fetchall():
        if row["notebook_id"] not in live_notebooks:
            purge_notebook_state(conn, row["notebook_id"])
            changes += 1

    return changes


def scan(args) -> None:
    total_changes = 0
    passes = 0
    while True:
        changes = scan_once(args)
        total_changes += changes
        passes += 1
        if changes == 0:
            break
        log(f"Scan pass {passes} applied {changes} changes; continuing until stable")
    log(f"Scan completed after {passes} pass(es), total changes: {total_changes}.")
