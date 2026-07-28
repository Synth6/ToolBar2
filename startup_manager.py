import os
import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # pragma: no cover - winreg is only available on Windows.
    winreg = None


STARTUP_VALUE_NAME = "ToolBar2"
STARTUP_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_compiled_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def startup_supported() -> bool:
    return is_windows() and is_compiled_app()


def current_executable_path() -> Path:
    return Path(sys.executable).resolve()


def startup_command() -> str:
    return f'"{os.fspath(current_executable_path())}"'


def is_startup_registered() -> bool:
    if not startup_supported() or winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_PATH, 0, winreg.KEY_READ) as key:
            value, _value_type = winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
    except FileNotFoundError:
        return False
    except OSError:
        raise
    return str(value).strip() == startup_command()


def set_startup_enabled(enabled: bool) -> None:
    if not startup_supported() or winreg is None:
        return

    try:
        if enabled:
            executable = current_executable_path()
            if not executable.exists() or not executable.is_file():
                raise RuntimeError(f"Startup executable does not exist: {executable}")
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                STARTUP_REGISTRY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, startup_command())
            return

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                STARTUP_REGISTRY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, STARTUP_VALUE_NAME)
        except FileNotFoundError:
            return
    except (OSError, RuntimeError):
        raise


def sync_startup_registration(enabled: bool) -> None:
    set_startup_enabled(enabled)
