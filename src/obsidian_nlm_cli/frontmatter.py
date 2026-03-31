from __future__ import annotations

from pathlib import Path

from .utils import FRONTMATTER_BOUNDARY


# ── encode / decode ────────────────────────────────────────────────────
def encode_frontmatter_value(value: str | None) -> str:
    if value is None:
        return '""'
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def decode_frontmatter_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
        value = value.replace('\\"', '"').replace("\\\\", "\\")
    return value


# ── split / render ─────────────────────────────────────────────────────
def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith(FRONTMATTER_BOUNDARY + "\n"):
        return {}, text
    parts = text.split("\n" + FRONTMATTER_BOUNDARY + "\n", 1)
    if len(parts) != 2:
        return {}, text
    header = parts[0].splitlines()[1:]
    body = parts[1]
    meta: dict[str, str] = {}
    for line in header:
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        meta[key.strip()] = decode_frontmatter_value(raw)
    return meta, body


def render_markdown_with_frontmatter(meta: dict[str, str], body: str) -> str:
    lines = [FRONTMATTER_BOUNDARY]
    for key, value in meta.items():
        lines.append(f"{key}: {encode_frontmatter_value(value)}")
    lines.append(FRONTMATTER_BOUNDARY)
    lines.append("")
    lines.append(body.rstrip() + "\n")
    return "\n".join(lines)


# ── file helpers ───────────────────────────────────────────────────────
def extract_source_payload(path: Path) -> tuple[dict[str, str], str]:
    raw = path.read_text(encoding="utf-8")
    return split_frontmatter(raw)


def managed_body_for_export(title: str, source_type: str, url: str | None, content: str) -> str:
    lines = [f"# {title}", ""]
    if source_type:
        lines.append(f"- Source type: `{source_type}`")
    if url:
        lines.append(f"- Source URL: {url}")
    if source_type or url:
        lines.append("")
    lines.append(content.strip())
    lines.append("")
    return "\n".join(lines)


def managed_body_for_sync(body: str) -> str:
    normalized = body.strip()
    return normalized + "\n" if normalized else ""
