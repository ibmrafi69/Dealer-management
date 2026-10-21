"""Paths shared by Django settings and the frozen application launcher."""

import os
import sys
from pathlib import Path


APP_NAME = "Dealer Management"
DATA_DIR_ENVIRONMENT_VARIABLE = "DEALER_MANAGEMENT_DATA_DIR"
FROZEN = getattr(sys, "frozen", False)

SOURCE_ROOT = Path(__file__).resolve().parent.parent
EXECUTABLE_ROOT = Path(sys.executable).resolve().parent if FROZEN else SOURCE_ROOT
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)) if FROZEN else SOURCE_ROOT


def _default_data_root() -> Path:
    """Return a location that survives replacement of the ONEDIR folder."""
    configured_path = os.environ.get(DATA_DIR_ENVIRONMENT_VARIABLE)
    if configured_path:
        return Path(configured_path).expanduser()

    if not FROZEN:
        return SOURCE_ROOT

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME
    return Path.home() / "AppData" / "Local" / APP_NAME


DATA_ROOT = _default_data_root()
