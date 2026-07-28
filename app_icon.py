from __future__ import annotations

import ctypes
import sys

from PyQt6 import QtGui

from config_manager import resource_path


APP_ICON_PATH = "img/ToolBar2.ico"
WINDOWS_APP_USER_MODEL_ID = "MiddleCreekInsurance.MCIToolbar"


def application_icon() -> QtGui.QIcon:
    return QtGui.QIcon(resource_path(APP_ICON_PATH))


def apply_window_icon(window) -> None:
    icon = application_icon()
    if not icon.isNull():
        window.setWindowIcon(icon)


def set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass
