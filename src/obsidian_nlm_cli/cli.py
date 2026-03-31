from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .db import open_db
from .nlm import run_nlm
from .sync import (
    iter_notebook_folders,
    list_markdown_files,
    scan,
    scan_once,
)
from .frontmatter import managed_body_for_export, render_markdown_with_frontmatter
from .utils import (
    NOTEBOOK_META_NAME,
    SyncPaths,
    ensure_unique_path,
    json_dump,
    log,
    paths_for,
    sanitize_name,
    sha256_text,
    short_id,
)


def _resolve_vault(args: argparse.Namespace) -> str:
    """Return the vault path from args, falling back to env var or '.'."""
    return args.vault


# ── bootstrap ──────────────────────────────────────────────────────────
def bootstrap(args: argparse.Namespace) -> None:
    sp = paths_for(Path(_resolve_vault(args)))
    sp.vault.mkdir(parents=True, exist_ok=True)
    conn = open_db(sp.state_db)
    notebooks = run_nlm(["notebook", "list", "--json"], timeout_seconds=180)
    log(f"Bootstrapping {len(notebooks)} notebooks into {sp.vault}")

    for notebook in notebooks:
        notebook_id = notebook["id"]
        title = notebook.get("title") or f"untitled-{short_id(notebook_id)}"
        existing_notebook = conn.execute(
            "SELECT folder_path, metadata_path FROM notebooks WHERE notebook_id = ?", (notebook_id,)
        ).fetchone()
        if existing_notebook:
            folder = Path(existing_notebook["folder_path"])
            metadata_path = Path(existing_notebook["metadata_path"])
            folder.mkdir(parents=True, exist_ok=True)
        else:
            folder_name = sanitize_name(title, f"untitled-{short_id(notebook_id)}")
            folder = ensure_unique_path(sp.vault / folder_name)
            folder.mkdir(parents=True, exist_ok=False)
            metadata_path = folder / NOTEBOOK_META_NAME
        json_dump({"notebook_id": notebook_id, "title": title}, metadata_path)
        from .db import upsert_notebook as _upsert_notebook
        _upsert_notebook(
            conn,
            notebook_id=notebook_id,
            title=title,
            folder_path=folder,
            metadata_path=metadata_path,
            created_via="bootstrap",
        )

        try:
            sources = run_nlm(["source", "list", notebook_id, "--json"], timeout_seconds=180)
        except Exception as exc:
            from .db import append_failure
            append_failure(
                sp,
                {
                    "kind": "notebook_source_list",
                    "notebook_id": notebook_id,
                    "notebook_title": title,
                    "error": str(exc),
                },
            )
            log(f"  [{folder.name}] failed to list sources, skipping notebook")
            continue

        log(f"  [{folder.name}] exporting {len(sources)} sources")
        for source in sources:
            source_id = source["id"]
            source_title = source.get("title") or f"source-{short_id(source_id)}"
            source_type = source.get("type")
            source_url = source.get("url")
            existing_source = conn.execute(
                "SELECT file_path FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone()
            if existing_source and Path(existing_source["file_path"]).exists():
                continue
            try:
                payload = run_nlm(["source", "content", source_id, "--json"], timeout_seconds=240)
                value = payload["value"]
                content = value.get("content", "")
                body = managed_body_for_export(
                    source_title,
                    value.get("source_type") or source_type or "",
                    value.get("url") or source_url,
                    content,
                )
                meta = {
                    "nlm_notebook_id": notebook_id,
                    "nlm_source_id": source_id,
                    "nlm_source_type": value.get("source_type") or source_type or "",
                    "nlm_source_url": value.get("url") or source_url or "",
                }
                file_name = sanitize_name(source_title, f"source-{short_id(source_id)}")
                if existing_source:
                    file_path = Path(existing_source["file_path"])
                else:
                    file_path = ensure_unique_path(folder / f"{file_name}.md")
                markdown = render_markdown_with_frontmatter(meta, body)
                file_path.write_text(markdown, encoding="utf-8")
                from .db import upsert_source as _upsert_source
                _upsert_source(
                    conn,
                    source_id=source_id,
                    notebook_id=notebook_id,
                    title=source_title,
                    file_path=file_path,
                    source_type=meta["nlm_source_type"] or None,
                    source_url=meta["nlm_source_url"] or None,
                    content_hash=sha256_text(body),
                    created_via="bootstrap",
                )
            except Exception as exc:
                from .db import append_failure
                append_failure(
                    sp,
                    {
                        "kind": "source_content",
                        "notebook_id": notebook_id,
                        "notebook_title": title,
                        "source_id": source_id,
                        "source_title": source_title,
                        "error": str(exc),
                    },
                )
                log(f"    failed source {source_title} ({source_id}), skipping")
                continue

    log("Bootstrap completed.")


# ── status ─────────────────────────────────────────────────────────────
def status(args: argparse.Namespace) -> None:
    sp = paths_for(Path(_resolve_vault(args)))
    conn = open_db(sp.state_db)
    notebook_count = conn.execute("SELECT COUNT(*) FROM notebooks").fetchone()[0]
    source_count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    live_folder_count = sum(1 for _ in iter_notebook_folders(sp.vault)) if sp.vault.exists() else 0
    live_file_count = 0
    if sp.vault.exists():
        for folder in iter_notebook_folders(sp.vault):
            live_file_count += len(list_markdown_files(folder))
    print(
        json.dumps(
            {
                "vault": str(sp.vault),
                "state_db": str(sp.state_db),
                "tracked_notebooks": notebook_count,
                "tracked_sources": source_count,
                "live_folders": live_folder_count,
                "live_markdown_files": live_file_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


# ── watch ──────────────────────────────────────────────────────────────
def watch(args: argparse.Namespace) -> None:
    interval = args.interval
    log(f"Watching {_resolve_vault(args)} every {interval}s")
    while True:
        scan(args)
        time.sleep(interval)


# ── CLI parser ─────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    default_vault = os.environ.get("OBSIDIAN_NLM_VAULT", ".")

    parser = argparse.ArgumentParser(
        description="One-way Obsidian -> NotebookLM sync with NLM bootstrap."
    )
    parser.add_argument(
        "--vault",
        default=default_vault,
        help="Obsidian vault folder to manage (default: OBSIDIAN_NLM_VAULT env var or '.')",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap", help="Bootstrap an empty vault from existing NotebookLM data"
    )
    bootstrap_parser.set_defaults(func=bootstrap)

    scan_parser = subparsers.add_parser(
        "scan", help="Apply local Obsidian changes to NotebookLM"
    )
    scan_parser.set_defaults(func=scan)

    status_parser = subparsers.add_parser(
        "status", help="Show local sync status"
    )
    status_parser.set_defaults(func=status)

    watch_parser = subparsers.add_parser(
        "watch", help="Poll the vault and apply changes continuously"
    )
    watch_parser.add_argument(
        "--interval", type=int, default=60, help="Polling interval in seconds (default: 60)"
    )
    watch_parser.set_defaults(func=watch)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
