from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ── constants ──────────────────────────────────────────────────────────
STATE_DIR_NAME = ".nlm-sync"
STATE_DB_NAME = "state.db"
NOTEBOOK_META_NAME = ".notebooklm.json"
FAILED_LOG_NAME = "failures.jsonl"
FRONTMATTER_BOUNDARY = "---"

NLM_BIN: str = shutil.which("nlm") or str(Path.home() / ".local" / "bin" / "nlm")


# ── paths dataclass ────────────────────────────────────────────────────
@dataclass
class SyncPaths:
    vault: Path
    state_dir: Path
    state_db: Path
    failure_log: Path


# ── path helpers ───────────────────────────────────────────────────────
def paths_for(vault: Path) -> SyncPaths:
    state_dir = vault / STATE_DIR_NAME
    return SyncPaths(
        vault=vault,
        state_dir=state_dir,
        state_db=state_dir / STATE_DB_NAME,
        failure_log=state_dir / FAILED_LOG_NAME,
    )


# ── naming helpers ─────────────────────────────────────────────────────
def sanitize_name(value: str, fallback: str) -> str:
    value = value.strip()
    value = re.sub(r"[\\/:*?\"<>|]", "-", value)
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" .")
    return value or fallback


def short_id(value: str) -> str:
    return value.split("-")[0]


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem} {counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


# ── hashing ────────────────────────────────────────────────────────────
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── JSON helpers ───────────────────────────────────────────────────────
def json_dump(data: Any, path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def json_load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ── time helpers ───────────────────────────────────────────────────────
def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── logging ────────────────────────────────────────────────────────────
def log(message: str) -> None:
    print(message, flush=True)
