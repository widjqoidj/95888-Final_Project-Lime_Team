"""
Shared utility helpers for directory setup.
"""

from __future__ import annotations

from config import DATA_DIR

def ensure_project_directories() -> None:
    """Create required project directories if they do not exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
