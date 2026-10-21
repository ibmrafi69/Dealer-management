"""PyInstaller entry point for the local Dealer Management server."""

import ctypes
from ctypes import wintypes
import os
import shutil
import socket
import sys
import threading
import time
import tempfile
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from config.runtime import APP_NAME, DATA_ROOT, EXECUTABLE_ROOT, FROZEN, RESOURCE_ROOT


HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}/"
_MUTEX_NAME = "Local\\DealerManagementLauncher"
_ERROR_ALREADY_EXISTS = 183
_LOG_FILE_NAME = "launcher.log"


def _startup_log_paths() -> tuple[Path, ...]:
    """Return durable log locations, preferring the user data directory."""
    temporary_directory = Path(os.environ.get("TEMP", tempfile.gettempdir()))
    return (
        DATA_ROOT / "logs" / _LOG_FILE_NAME,
        temporary_directory / APP_NAME / "logs" / _LOG_FILE_NAME,
    )


def log_startup_message(message: str) -> None:
    """Print diagnostics and retain them when a double-clicked EXE closes."""
    print(message, file=sys.stderr, flush=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    for log_path in _startup_log_paths():
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(f"[{timestamp}] {message}\n")
            return
        except OSError:
            # The data location itself can be the failed resource, so use the
            # temp fallback before giving up on persistent diagnostics.
            continue


def ensure_directory_is_writable(directory: Path) -> None:
    """Check the external data directory before Django starts using SQLite."""
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".write-test-", delete=True):
            pass
    except OSError as error:
        raise RuntimeError(
            f"Application data directory is not writable: {directory}"
        ) from error


def _copy_file_if_missing(destination: Path, *sources: Path) -> bool:
    """Initialize a file once, never replacing an existing user file."""
    if destination.exists():
        return False
    for source in sources:
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            return True
    return False


def _copy_tree_without_overwriting(source: Path, destination: Path) -> None:
    """Bring forward legacy/seed media while preserving every user upload."""
    if not source.is_dir():
        return
    for source_file in source.rglob("*"):
        if not source_file.is_file():
            continue
        destination_file = destination / source_file.relative_to(source)
        if not destination_file.exists():
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination_file)


def prepare_persistent_data() -> bool:
    """Prepare external data and report whether a fresh database is needed."""
    if not FROZEN:
        return False

    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    ensure_directory_is_writable(DATA_ROOT)
    database_path = DATA_ROOT / "db.sqlite3"
    copied_legacy_database = _copy_file_if_missing(
        database_path,
        EXECUTABLE_ROOT / "db.sqlite3",  # Legacy installs only; never bundled.
    )

    # Existing installs next to the EXE are brought forward once. Bundled
    # media only fills absent files and can never replace an uploaded file.
    media_path = DATA_ROOT / "media"
    _copy_tree_without_overwriting(EXECUTABLE_ROOT / "media", media_path)
    _copy_tree_without_overwriting(RESOURCE_ROOT / "seed_media", media_path)

    if copied_legacy_database:
        print(f"Initialized persistent database: {database_path}", flush=True)
    print(f"Using persistent application data: {DATA_ROOT}", flush=True)
    return not database_path.is_file()


def _another_instance_is_running() -> bool:
    """Use a Windows named mutex to prevent duplicate servers/browser tabs."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    create_mutex.restype = wintypes.HANDLE
    mutex = create_mutex(None, False, _MUTEX_NAME)
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(mutex)
        return True
    # Keep the mutex handle open for the lifetime of this process.
    globals()["_instance_mutex"] = mutex
    return False


def _port_is_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.25)
        return connection.connect_ex((HOST, PORT)) == 0


def open_browser_when_ready() -> None:
    """Open exactly one browser tab after the local server accepts requests."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=1) as response:
                if response.status < 500:
                    print(f"Opening browser: {URL}", flush=True)
                    webbrowser.open_new(URL)
                    return
        except urllib.error.HTTPError as error:
            # A response from Django proves the server started. A 5xx is an
            # application failure, not a reason to create repeated requests.
            log_startup_message(
                f"Dashboard failed to start at {URL}: HTTP {error.code}. "
                "See the console traceback and launcher log for details."
            )
            return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.25)
    log_startup_message(f"Dealer Management did not become ready at {URL} within 30 seconds.")


def ensure_database_is_writable() -> None:
    """Acquire and release a SQLite write lock without altering business data."""
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("ROLLBACK")
    except Exception as error:
        raise RuntimeError(
            f"Application database is not writable: {connection.settings_dict['NAME']}"
        ) from error


def main() -> None:
    try:
        if _another_instance_is_running():
            print("Dealer Management is already running.", flush=True)
            return
        if _port_is_in_use():
            print(f"Port {PORT} is already in use; Dealer Management was not started.", flush=True)
            return

        fresh_database = prepare_persistent_data()
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

        import django
        from django.core.management import execute_from_command_line

        django.setup()
        if fresh_database:
            # This only creates a missing per-user database for a new install.
            # Existing business databases are never overwritten or migrated here.
            execute_from_command_line([sys.argv[0], "migrate", "--noinput"])
        ensure_database_is_writable()
        threading.Thread(target=open_browser_when_ready, daemon=True).start()
        # Use Django's in-process command runner.  Do not launch manage.py with
        # sys.executable: that would relaunch this EXE recursively when frozen.
        execute_from_command_line([
            sys.argv[0],
            "runserver",
            f"{HOST}:{PORT}",
            "--noreload",
        ])
    except Exception:
        log_startup_message(
            "Dealer Management could not start. Details follow:\n"
            f"{traceback.format_exc()}"
        )
        raise


if __name__ == "__main__":
    main()
