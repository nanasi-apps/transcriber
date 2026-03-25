from __future__ import annotations

import os
from pathlib import Path


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip().strip('"').strip("'")

    if not key:
        return None

    return key, value


def load_local_env() -> None:
    candidates = [
        Path.cwd() / ".env.local",
        Path(__file__).resolve().parents[3] / ".env.local",
        Path(__file__).resolve().parents[2] / ".env.local",
    ]

    for path in candidates:
        if not path.exists() or not path.is_file():
            continue

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(raw_line)
            if parsed is None:
                continue

            key, value = parsed
            os.environ.setdefault(key, value)
