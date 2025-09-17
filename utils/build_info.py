"""Helpers for exposing build/version information in the UI and logs."""
from __future__ import annotations

import os
import pathlib
import subprocess
from functools import lru_cache

_DEFAULT_VERSION = "dev"


@lru_cache(maxsize=1)
def get_app_version() -> str:
    """Return the best-effort application version string.

    Preference order:
    1. Environment variable (several common names) injected at build/runtime.
    2. A VERSION-esque file bundled with the app.
    3. Git commit hash when available (developer runs).
    4. Fallback constant "dev".
    """
    env_candidates = (
        "POPRAWIACZTEKSTU_VERSION",
        "POPRAWIACZTEKSTUPY_VERSION",
        "POPRAWIACZ_VERSION",
        "POPRAWIACZPY_VERSION",
        "BUILD_VERSION",
        "APP_VERSION",
        "GITHUB_RUN_NUMBER",
    )
    for var in env_candidates:
        value = os.getenv(var)
        if value:
            return value.strip()

    project_root = pathlib.Path(__file__).resolve().parents[1]
    file_candidates = (
        project_root / "VERSION",
        project_root / "build" / "VERSION",
        project_root / "build" / "build_info.txt",
    )
    for path in file_candidates:
        try:
            if path.exists():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    return text
        except OSError:
            continue

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(project_root),
            check=True,
            capture_output=True,
            text=True,
        )
        commit = result.stdout.strip()
        if commit:
            return f"git-{commit}"
    except (OSError, subprocess.SubprocessError):
        pass

    return _DEFAULT_VERSION
