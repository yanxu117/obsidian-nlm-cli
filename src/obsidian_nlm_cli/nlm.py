from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Any

from .utils import NLM_BIN, log

# ── constants ──────────────────────────────────────────────────────────
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_RETRIES = 3


# ── NLM runner ─────────────────────────────────────────────────────────
def run_nlm(
    args: list[str],
    *,
    expect_json: bool = True,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
) -> Any:
    cmd = [NLM_BIN, *args]
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
            if result.returncode != 0:
                raise RuntimeError(
                    f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                )
            stdout = result.stdout.strip()
            if not expect_json:
                return stdout
            if not stdout:
                return None
            return json.loads(stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            log(f"Retry {attempt}/{retries - 1} for: {' '.join(cmd)}")
            time.sleep(min(2 * attempt, 10))
    assert last_error is not None
    raise RuntimeError(f"Failed after {retries} attempts: {' '.join(cmd)}\n{last_error}")


# ── output parsing ─────────────────────────────────────────────────────
def parse_id_from_output(output: str) -> str:
    match = re.search(r"\bID:\s*([0-9a-f-]{36})\b", output)
    if match:
        return match.group(1)
    match = re.search(r"\bSource ID:\s*([0-9a-f-]{36})\b", output)
    if match:
        return match.group(1)
    raise RuntimeError(f"Could not parse ID from output:\n{output}")
