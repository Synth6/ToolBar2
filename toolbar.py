import sys

from PyQt6 import QtWidgets

from app_icon import application_icon, set_windows_app_user_model_id
from toolbar_manager import ToolbarManager


def main() -> None:
    set_windows_app_user_model_id()

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("ToolBar2")
    app.setOrganizationName("StudioDezines")
    icon = application_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    app.setQuitOnLastWindowClosed(False)

    manager = ToolbarManager(app)
    manager.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
