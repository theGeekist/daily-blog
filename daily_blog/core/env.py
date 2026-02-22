"""Environment-loading helpers shared by backend scripts."""

import os
from pathlib import Path


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Treat empty/whitespace env values as unset so .env can fill them.
        current = os.environ.get(key, "")
        if key and (key not in os.environ or not current.strip()):
            os.environ[key] = value
