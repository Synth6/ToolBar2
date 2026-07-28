from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from config_manager import CONFIG_VERSION, resource_path


HELP_INDEX_RELATIVE_PATH = "help/index.html"
ToolBar2_VERSION_LABEL = f"Config Version {CONFIG_VERSION}"


def help_index_path() -> Path:
    return Path(resource_path(HELP_INDEX_RELATIVE_PATH))


def open_ToolBar2_help(parent: QtWidgets.QWidget | None = None) -> bool:
    help_path = help_index_path()
    if not help_path.exists():
        QtWidgets.QMessageBox.warning(
            parent,
            "Help Unavailable",
            f"ToolBar2 Help could not be found:\n{help_path}",
        )
        return False
    url = QtCore.QUrl.fromLocalFile(str(help_path.resolve()))
    if QtGui.QDesktopServices.openUrl(url):
        return True
    QtWidgets.QMessageBox.warning(
        parent,
        "Help Unavailable",
        f"ToolBar2 Help could not be opened:\n{help_path}",
    )
    return False
