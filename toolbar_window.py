from __future__ import annotations

import copy
import os
import shutil
import sys
from urllib.parse import quote_plus
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6 import QtCore, QtGui, QtWidgets

from app_icon import apply_window_icon
from config_manager import DEFAULT_CONFIG, resource_path
from config_manager import isolate_profile_item_assets, isolate_profile_menu_assets
from drop_handler import DroppedItemsDialog, extract_local_paths_from_mime_data, extract_targets_from_mime_data
from folder_menu_properties_dialog import FolderMenuPropertiesDialog
from help_utils import open_ToolBar2_help
from icon_utilities import AssetContext, delete_managed_icon_if_unused, delete_managed_menu_icon_if_unused, folder_icon, folder_menu_icon, icon_for_item, menu_button_icon
from launcher import launch_item, launch_item_with_args, launch_target
from launcher_editor import LauncherEditorDialog
from logo_editor_dialog import LogoEditorDialog
from logo_widget import LogoWidget
from managed_qmenu import ManagedMenu
from menu_config_helpers import (
    add_heading_to_container_by_id,
    add_launcher_to_container_by_id,
    add_separator_to_container_by_id,
    add_submenu_to_container_by_id,
    count_nested_descendants,
    delete_menu_by_id,
    delete_item_by_id,
    duplicate_item_by_id,
    duplicate_menu_by_id,
    find_any_item_by_id,
    find_menu_by_id,
    find_menu_index_by_id,
    find_item_location,
    insert_launcher_items,
    list_menu_destinations,
    move_item_by_id,
    move_menu_by_id,
    replace_item_by_id,
    toggle_item_enabled_by_id,
    top_launcher_to_editor_item,
    top_launcher_to_launcher_item,
    valid_menu_destination_at_path,
)
from menu_properties_dialog import MenuPropertiesDialog
from monitor_utils import screen_for_monitor_id

if TYPE_CHECKING:
    from toolbar_manager import ToolbarManager


DEFAULT_WEB_SEARCH_BAR_WIDTH = 180


def color_with_opacity(hex_color: str, opacity: float) -> str:
    color = QtGui.QColor(hex_color)
    if not color.isValid():
        color = QtGui.QColor("#202020")
    try:
        opacity_value = float(opacity)
    except (TypeError, ValueError):
        opacity_value = 1.0
    alpha = round(max(0.0, min(1.0, opacity_value)) * 255)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


class FolderMenuWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(str, list, str)

    def __init__(self, folder_path: str, include_files: bool, include_folders: bool) -> None:
        super().__init__()
        self.folder_path = folder_path
        self.include_files = include_files
        self.include_folders = include_folders

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            path = Path(os.path.expandvars(os.path.expanduser(self.folder_path)))
            if not path.exists() or not path.is_dir():
                self.finished.emit(self.folder_path, [], "Folder unavailable")
                return
            folders: list[dict] = []
            files: list[dict] = []
            with os.scandir(path) as entries:
                for entry in entries:
                    if is_hidden_or_system(entry):
                        continue
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                        is_file = entry.is_file(follow_symlinks=False)
                    except OSError:
                        continue
                    if is_dir and self.include_folders:
                        folders.append({"name": entry.name, "path": entry.path, "is_dir": True})
                    elif is_file and self.include_files:
                        files.append({"name": entry.name, "path": entry.path, "is_dir": False})
            folders.sort(key=lambda item: item["name"].casefold())
            files.sort(key=lambda item: item["name"].casefold())
            self.finished.emit(self.folder_path, folders + files, "")
        except OSError:
            self.finished.emit(self.folder_path, [], "Folder unavailable")


class FolderTransferWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(int, list)

    def __init__(self, transfers: list[dict], action: str) -> None:
        super().__init__()
        self.transfers = transfers
        self.action = action

    @QtCore.pyqtSlot()
    def run(self) -> None:
        completed = 0
        errors: list[str] = []
        for transfer in self.transfers:
            source = Path(str(transfer.get("source") or ""))
            destination = Path(str(transfer.get("destination") or ""))
            replace = bool(transfer.get("replace", False))
            self.progress.emit(source.name or str(source))
            try:
                if not source.exists():
                    raise FileNotFoundError(f"Source no longer exists: {source}")
                if destination.exists():
                    if not replace:
                        raise FileExistsError(f"Destination already exists: {destination}")
                    self.remove_existing_destination(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if self.action == "move":
                    shutil.move(str(source), str(destination))
                elif source.is_dir():
                    shutil.copytree(str(source), str(destination))
                else:
                    shutil.copy2(str(source), str(destination))
                completed += 1
            except Exception as exc:
                errors.append(f"{source.name or source}: {exc}")
        self.finished.emit(completed, errors)

    def remove_existing_destination(self, destination: Path) -> None:
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()


def is_hidden_or_system(entry: os.DirEntry) -> bool:
    if entry.name.startswith("."):
        return True
    attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attrs & 0x2 or attrs & 0x4)


class ToolbarWindow(QtWidgets.QFrame):
    def __init__(self, manager: ToolbarManager, config: dict, monitor_id: str) -> None:
        super().__init__()

        self.manager = manager
        self.config = config
        self.monitor_id = monitor_id
        self._removing = False
        self.current_screen: QtGui.QScreen | None = None
        self.is_open = False
        self.mouse_out_ticks = 0
        self.menu_open = False
        self.minimum_required_toolbar_width = 0
        self.effective_toolbar_width = 0
        self.active_menu_count = 0
        self.drag_active = False
        self.drop_dialog_open = False
        self.dialog_open = False
        self.menu_buttons: list[QtWidgets.QPushButton] = []
        self.ordered_top_level_widgets: list[QtWidgets.QWidget] = []
        self.effective_metrics: dict[str, int] = {}
        self.folder_transfer_threads: list[tuple[QtCore.QThread, FolderTransferWorker]] = []
        self.hover_menu_timer = QtCore.QTimer(self)
        self.hover_menu_timer.setSingleShot(True)
        self.hover_menu_timer.timeout.connect(self.open_hovered_toolbar_menu)
        self.hovered_menu_id = ""
        self.hovered_menu_button: QtWidgets.QPushButton | None = None
        self.active_toolbar_menu: QtWidgets.QMenu | None = None
        self.active_toolbar_menu_id = ""
        self.menu_switch_timer = QtCore.QTimer(self)
        self.menu_switch_timer.setInterval(45)
        self.menu_switch_timer.timeout.connect(self.check_toolbar_menu_switch)
        self.switch_candidate_menu_id = ""
        self.switch_candidate_button: QtWidgets.QPushButton | None = None
        self.switch_candidate_elapsed = QtCore.QElapsedTimer()
        self.menu_leave_elapsed = QtCore.QElapsedTimer()
        self.menu_leave_pending = False
        self.top_button_context_pending = False
        self.top_button_context_active = False
        self.folder_menu_threads: list[tuple[QtCore.QThread, FolderMenuWorker]] = []
        self.drag_open_timer = QtCore.QTimer(self)
        self.drag_open_timer.setSingleShot(True)
        self.drag_open_timer.timeout.connect(self.open_drag_candidate)
        self.drag_open_button: QtWidgets.QPushButton | None = None
        self.drag_open_menu: QtWidgets.QMenu | None = None
        self.drag_open_action: QtGui.QAction | None = None
        self.drag_highlight_button: QtWidgets.QPushButton | None = None

        self.setWindowTitle("ToolBar2")
        apply_window_icon(self)
        self.setObjectName("toolbarWindow")
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)

        self.build_ui()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self.animation = QtCore.QPropertyAnimation(self, b"geometry", self)
        self.animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        self.mouse_timer = QtCore.QTimer(self)
        self.mouse_timer.timeout.connect(self.check_mouse_position)
        self.mouse_timer.start(50)

        self.refresh_config(self.config)

    def build_ui(self) -> None:
        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.toolbar_surface = QtWidgets.QFrame()
        self.toolbar_surface.setObjectName("toolbarSurface")
        self.toolbar_surface.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        outer_layout.addWidget(self.toolbar_surface)

        self.main_layout = QtWidgets.QHBoxLayout(self.toolbar_surface)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.left_controls_container = QtWidgets.QWidget()
        self.left_controls_layout = QtWidgets.QHBoxLayout(self.left_controls_container)
        self.left_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.left_controls_layout.setSpacing(0)
        self.logo_label = LogoWidget()
        self.logo_label.leftClicked.connect(self.handle_logo_left_click)
        self.logo_label.rightClicked.connect(self.open_logo_context_menu)
        self.left_controls_layout.addWidget(self.logo_label, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        self.main_layout.addWidget(self.left_controls_container, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        self.logo_menu_gap = QtWidgets.QSpacerItem(
            0,
            0,
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        self.main_layout.addItem(self.logo_menu_gap)

        self.left_menu_spacer = QtWidgets.QSpacerItem(
            0,
            0,
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        self.main_layout.addItem(self.left_menu_spacer)

        self.menu_container = QtWidgets.QWidget()
        self.menu_layout = QtWidgets.QHBoxLayout(self.menu_container)
        self.menu_layout.setContentsMargins(0, 0, 0, 0)
        self.menu_layout.setSpacing(10)
        self.main_layout.addWidget(self.menu_container, 0, QtCore.Qt.AlignmentFlag.AlignCenter)

        self.right_menu_spacer = QtWidgets.QSpacerItem(
            0,
            0,
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        self.main_layout.addItem(self.right_menu_spacer)

        self.menu_controls_gap = QtWidgets.QSpacerItem(
            0,
            0,
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        self.main_layout.addItem(self.menu_controls_gap)

        self.right_controls_container = QtWidgets.QWidget()
        self.right_controls_layout = QtWidgets.QHBoxLayout(self.right_controls_container)
        self.right_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.right_controls_layout.setSpacing(6)
        self.web_search_edit = QtWidgets.QLineEdit()
        self.web_search_edit.setObjectName("webSearchEdit")
        self.web_search_edit.setPlaceholderText("Search the web...")
        self.web_search_edit.setClearButtonEnabled(True)
        self.web_search_edit.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.NoContextMenu)
        self.web_search_edit.returnPressed.connect(self.submit_web_search)

        self.settings_button = QtWidgets.QToolButton()
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.settings_button.setToolTip("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        self.right_controls_layout.addWidget(self.settings_button, 0, QtCore.Qt.AlignmentFlag.AlignRight)

        self.close_button = QtWidgets.QToolButton()
        self.close_button.setObjectName("closeButton")
        self.close_button.setText("×")
        self.close_button.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.close_button.setToolTip("Exit Toolbar")
        self.close_button.clicked.connect(self.exit_toolbar)
        self.right_controls_layout.addWidget(self.close_button, 0, QtCore.Qt.AlignmentFlag.AlignRight)
        self.main_layout.addWidget(self.right_controls_container, 0, QtCore.Qt.AlignmentFlag.AlignRight)

        self.settings_button.installEventFilter(self)
        self.close_button.installEventFilter(self)
        self.web_search_edit.installEventFilter(self)

    def refresh_config(self, config: dict, monitor_id: str | None = None) -> None:
        self.config = copy.deepcopy(config)
        if monitor_id is not None:
            self.monitor_id = monitor_id
        appearance = self.config["appearance"]
        self.setFixedHeight(appearance["toolbar_height"])
        self.effective_metrics = self.calculate_effective_metrics()
        self.setWindowOpacity(1.0)
        self.animation.setDuration(self.config["behavior"]["animation_duration_ms"])
        self.update_control_button_visibility()
        self.apply_style()
        self.update_logo()
        self.update_settings_icon()
        self.update_web_search_field_metrics()
        self.update_group_visibility()
        self.apply_layout_metrics()
        self.render_menus()
        self.apply_menu_alignment()
        self.refresh_minimum_required_toolbar_width()

        screen = self.configured_screen()
        if self.is_open:
            self.show_menu(screen)
        else:
            self.position_hidden(screen)

    def commit_config(self) -> None:
        try:
            self.manager.apply_toolbar_change(self.monitor_id, self.config)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Config Save Failed",
                str(exc) or "The toolbar configuration could not be saved.",
            )

    def current_profile_id(self) -> str | None:
        return self.manager.profile_id_for_monitor(self.monitor_id)

    def prepare_for_removal(self) -> None:
        self._removing = True
        self.mouse_timer.stop()
        self.hover_menu_timer.stop()
        self.menu_switch_timer.stop()
        self.drag_open_timer.stop()
        self.animation.stop()
        self.clear_drag_state()
        self.close_visible_popup_menus()
        self.close_active_toolbar_menu()
        for thread, worker in list(self.folder_menu_threads):
            if thread.isRunning():
                try:
                    worker.finished.disconnect()
                except (TypeError, RuntimeError):
                    pass
                worker.finished.connect(thread.quit)
                worker.finished.connect(worker.deleteLater)
                thread.finished.connect(thread.deleteLater)
                thread.setParent(None)
                thread.quit()
                thread.wait(100)
        self.folder_menu_threads.clear()
        for thread, worker in list(self.folder_transfer_threads):
            if thread.isRunning():
                try:
                    worker.finished.disconnect()
                except (TypeError, RuntimeError):
                    pass
                worker.finished.connect(thread.quit)
                worker.finished.connect(worker.deleteLater)
                thread.finished.connect(thread.deleteLater)
                thread.setParent(None)
                thread.quit()
                thread.wait(100)
        self.folder_transfer_threads.clear()
        self.hide()

    def refresh_screen_geometry(self) -> None:
        if self._removing:
            return
        was_open = self.is_open
        self.animation.stop()
        self.close_visible_popup_menus()
        self.current_screen = None
        screen = self.configured_screen()
        if screen is None:
            self.hide()
            return
        self.apply_layout_metrics()
        self.apply_menu_alignment()
        if was_open:
            self.setGeometry(self.get_visible_rect(screen))
            self.current_screen = screen
            self.show()
            self.raise_()
            self.is_open = True
        else:
            self.position_hidden(screen)

    def safe_int(self, value: object, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def calculate_effective_metrics(self) -> dict[str, int]:
        appearance = self.config.get("appearance", {})
        logo = self.config.get("logo", {})
        toolbar_height = max(16, self.safe_int(appearance.get("toolbar_height"), 48))
        requested_button_height = max(12, self.safe_int(appearance.get("button_height"), 30))
        requested_logo_height = max(
            8,
            self.safe_int(
                logo.get("height"),
                DEFAULT_CONFIG["logo"]["height"],
            ),
        )
        requested_vertical_padding = max(0, self.safe_int(appearance.get("vertical_padding"), 0))
        maximum_padding = max(0, (toolbar_height - 12) // 2)
        effective_vertical_padding = min(requested_vertical_padding, maximum_padding)
        available_height = max(10, toolbar_height - (effective_vertical_padding * 2) - 2)
        effective_button_height = max(10, min(requested_button_height, available_height))
        effective_logo_height = max(6, min(requested_logo_height, available_height))
        control_size = max(10, min(effective_button_height, available_height))
        control_icon_size = max(7, min(32, control_size - 3))
        menu_icon_size = max(7, min(32, effective_button_height - 3))
        font_size = max(7, min(14, effective_button_height - 5))
        horizontal_button_padding = max(1, min(18, effective_button_height // 3))
        effective_corner_radius = max(
            0,
            min(
                self.safe_int(appearance.get("corner_radius"), 6),
                effective_button_height // 2,
            ),
        )
        return {
            "toolbar_height": toolbar_height,
            "effective_button_height": effective_button_height,
            "effective_logo_height": effective_logo_height,
            "effective_vertical_padding": effective_vertical_padding,
            "horizontal_padding": max(0, self.safe_int(appearance.get("horizontal_padding"), 0)),
            "menu_button_spacing": max(0, self.safe_int(appearance.get("menu_button_spacing"), 0)),
            "control_size": control_size,
            "control_icon_size": control_icon_size,
            "menu_icon_size": menu_icon_size,
            "font_size": font_size,
            "horizontal_button_padding": horizontal_button_padding,
            "effective_corner_radius": effective_corner_radius,
        }

    def apply_style(self) -> None:
        a = self.config["appearance"]
        metrics = self.effective_metrics or self.calculate_effective_metrics()
        toolbar_background = color_with_opacity(a["toolbar_background"], a["opacity"])
        button_height = metrics["effective_button_height"]
        button_content_height = max(1, button_height - 2)
        font_size = metrics["font_size"]
        button_padding = metrics["horizontal_button_padding"]
        corner_radius = metrics["effective_corner_radius"]
        exit_font_size = max(8, min(22, metrics["control_size"] - 1))
        self.setStyleSheet(f"""
            QFrame#toolbarSurface {{
                background-color: {toolbar_background};
                border-bottom: 1px solid {a["border_color"]};
            }}
            QPushButton {{
                min-height: {button_content_height}px;
                max-height: {button_content_height}px;
                padding: 0 {button_padding}px;
                color: {a["button_text"]};
                background-color: {a["button_background"]};
                border: 1px solid {a["border_color"]};
                border-radius: {corner_radius}px;
                font-size: {font_size}px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {a["button_hover"]};
            }}
            QMenu {{
                color: {a["menu_text"]};
                background-color: {a["menu_background"]};
                border: 1px solid {a["border_color"]};
            }}
            QMenu::item {{
                padding: 7px 26px 7px 18px;
            }}
            QMenu::item:selected {{
                background-color: {a["button_hover"]};
            }}
            QToolButton#settingsButton {{
                border: none;
                background: transparent;
                padding: 0;
            }}
            QToolButton#closeButton {{
                color: #ff4d4d;
                background: transparent;
                border: none;
                padding: 0;
                font-size: {exit_font_size}px;
                font-weight: bold;
            }}
            QToolButton#closeButton:hover {{
                color: #ffffff;
                background-color: #b42323;
                border-radius: 5px;
            }}
            QToolButton#closeButton:pressed {{
                background-color: #e00000;
            }}
            QLineEdit#webSearchEdit {{
                min-height: {button_content_height}px;
                max-height: {button_content_height}px;
                color: {a["button_text"]};
                background-color: {a["button_background"]};
                border: 1px solid {a["border_color"]};
                border-radius: {corner_radius}px;
                padding: 0 8px;
                font-size: {font_size}px;
            }}
            QLineEdit#webSearchEdit:hover,
            QLineEdit#webSearchEdit:focus {{
                background-color: {a["button_hover"]};
            }}

            QToolTip {{
                color: #ffffff;
                background-color: #2c2c2c;
                border: 1px solid #606060;
                padding: 5px;
            }}
        """)

    def update_logo(self) -> None:
        logo_config = copy.deepcopy(self.config["logo"])
        logo_config["height"] = self.effective_metrics["effective_logo_height"]
        self.logo_label.apply_logo_config(logo_config)

    def update_settings_icon(self) -> None:
        control_size = self.effective_metrics["control_size"]
        icon_size = self.effective_metrics["control_icon_size"]
        self.settings_button.setIcon(QtGui.QIcon(resource_path("img/gear.svg")))
        self.settings_button.setIconSize(QtCore.QSize(icon_size, icon_size))
        self.settings_button.setFixedSize(control_size, control_size)
        self.close_button.setFixedSize(control_size, control_size)

    def update_web_search_field_metrics(self) -> None:
        appearance = self.config.get("appearance", {})
        button_height = self.effective_metrics["effective_button_height"]
        self.web_search_edit.setFixedHeight(button_height)
        self.web_search_edit.setFixedWidth(
            max(100, min(500, self.safe_int(appearance.get("web_search_width"), DEFAULT_WEB_SEARCH_BAR_WIDTH)))
        )
        self.web_search_edit.setPlaceholderText(
            str(appearance.get("web_search_placeholder") or "Search the web...")
        )

    def update_control_button_visibility(self) -> None:
        appearance = self.config.get("appearance", {})
        self.settings_button.setVisible(
            bool(appearance.get("show_settings_button", True))
        )
        self.close_button.setVisible(
            bool(appearance.get("show_exit_button", False))
        )
        self.web_search_edit.setVisible(
            bool(appearance.get("show_web_search_bar", False))
        )
        self.update_group_visibility()

    def update_group_visibility(self) -> None:
        if hasattr(self, "left_controls_container"):
            self.left_controls_container.setVisible(not self.logo_label.isHidden())
        if hasattr(self, "right_controls_container"):
            self.right_controls_container.setVisible(
                not self.settings_button.isHidden()
                or not self.close_button.isHidden()
            )

    def confirm_exit_toolbar(self) -> None:
        self.dialog_open = True
        self.show_menu(self.configured_screen())
        try:
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("Exit ToolBar2?")
            box.setText("Exit ToolBar2?\n\nThis will close the toolbar completely.")
            exit_button = box.addButton("Exit", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == exit_button:
                self.manager.exit_application()
        finally:
            self.dialog_open = False

    def exit_toolbar(self) -> None:
        if self.config["behavior"].get("confirm_before_exit", False):
            self.confirm_exit_toolbar()
        else:
            self.manager.exit_application()

    def apply_layout_metrics(self) -> None:
        appearance = self.config["appearance"]
        metrics = self.effective_metrics or self.calculate_effective_metrics()
        horizontal_padding = metrics["horizontal_padding"]
        toolbar_height = metrics["toolbar_height"]
        effective_button_height = metrics["effective_button_height"]
        effective_logo_height = metrics["effective_logo_height"] if self.config["logo"].get("visible", True) else 0
        control_size = metrics["control_size"]
        show_settings = bool(appearance.get("show_settings_button", True))
        show_exit = bool(appearance.get("show_exit_button", False))
        settings_height = control_size if show_settings else 0
        exit_height = control_size if show_exit else 0
        search_height = effective_button_height if bool(appearance.get("show_web_search_bar", False)) else 0
        content_height = max(effective_button_height, effective_logo_height, settings_height, exit_height, search_height)
        max_vertical_padding = max(0, (toolbar_height - content_height) // 2)
        effective_vertical_padding = min(metrics["effective_vertical_padding"], max_vertical_padding)

        self.main_layout.setContentsMargins(
            horizontal_padding,
            effective_vertical_padding,
            horizontal_padding,
            effective_vertical_padding,
        )
        self.menu_layout.setSpacing(metrics["menu_button_spacing"])

    def visible_control_width(self, widget: QtWidgets.QWidget) -> int:
        return 0 if widget.isHidden() else widget.sizeHint().width()

    def reset_control_container_widths(self) -> None:
        for container in (self.left_controls_container, self.right_controls_container):
            container.setMinimumWidth(0)
            container.setMaximumWidth(16777215)
            container.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Fixed,
                QtWidgets.QSizePolicy.Policy.Preferred,
            )

    def visible_menu_buttons(self) -> list[QtWidgets.QPushButton]:
        return [button for button in self.menu_buttons if not button.isHidden()]

    def visible_top_level_widgets(self) -> list[QtWidgets.QWidget]:
        return [widget for widget in self.ordered_top_level_widgets if not widget.isHidden()]

    def visible_right_controls(self) -> list[QtWidgets.QWidget]:
        return [
            widget
            for widget in (self.settings_button, self.close_button)
            if not widget.isHidden()
        ]

    def set_menu_spacers(
        self,
        left_policy: QtWidgets.QSizePolicy.Policy,
        right_policy: QtWidgets.QSizePolicy.Policy,
    ) -> None:
        self.left_menu_spacer.changeSize(
            0,
            0,
            left_policy,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        self.right_menu_spacer.changeSize(
            0,
            0,
            right_policy,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )

    def set_group_gaps(self) -> None:
        group_gap = self.effective_metrics.get("menu_button_spacing", 0)
        logo_visible = not self.logo_label.isHidden()
        menus_visible = bool(self.visible_top_level_widgets())
        right_controls_visible = bool(self.visible_right_controls())
        self.logo_menu_gap.changeSize(
            group_gap if logo_visible and menus_visible else 0,
            0,
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        self.menu_controls_gap.changeSize(
            group_gap if menus_visible and right_controls_visible else 0,
            0,
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        self.right_controls_layout.setSpacing(
            self.effective_metrics.get("menu_button_spacing", 0)
            if len(self.visible_right_controls()) > 1
            else 0
        )

    def apply_menu_alignment(self) -> None:
        appearance = self.config.get("appearance", {})
        alignment = str(appearance.get("menu_alignment") or "center").lower()
        if alignment not in {"left", "center", "right"}:
            alignment = "center"

        self.reset_control_container_widths()
        self.update_group_visibility()
        self.set_group_gaps()
        expanding = QtWidgets.QSizePolicy.Policy.Expanding
        fixed = QtWidgets.QSizePolicy.Policy.Fixed

        if alignment == "left":
            self.set_menu_spacers(fixed, expanding)
        elif alignment == "right":
            self.set_menu_spacers(expanding, fixed)
        else:
            self.set_menu_spacers(expanding, expanding)

        self.menu_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.main_layout.invalidate()

    def render_menus(self) -> None:
        self.hover_menu_timer.stop()
        self.close_active_toolbar_menu()
        self.menu_layout.removeWidget(self.web_search_edit)
        for button in self.menu_buttons:
            self.menu_layout.removeWidget(button)
            button.deleteLater()
        self.menu_buttons.clear()
        self.ordered_top_level_widgets.clear()

        menus = self.config.get("menus", [])
        search_position = self.effective_web_search_position()
        search_added = False
        for index, menu_config in enumerate(menus):
            if not search_added and index == search_position:
                self.menu_layout.addWidget(self.web_search_edit)
                self.ordered_top_level_widgets.append(self.web_search_edit)
                search_added = True
            button = QtWidgets.QPushButton(menu_config.get("name", "Menu"))
            button.setProperty("menu_path", [index])
            button.setProperty("menu_id", menu_config.get("id", ""))
            button.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            button.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            button.setAcceptDrops(True)
            button.installEventFilter(self)
            self.apply_menu_button_metrics(button)
            self.apply_menu_button_style(button, menu_config)
            self.apply_menu_button_icon(button, menu_config)
            button.clicked.connect(lambda checked=False, menu_id=menu_config.get("id", ""), source=button: self.activate_top_level_button(source, menu_id))
            button.customContextMenuRequested.connect(
                lambda position, menu_id=menu_config.get("id", ""), source=button: self.open_menu_button_context(source, menu_id, position)
            )
            self.menu_layout.addWidget(button)
            self.menu_buttons.append(button)
            self.ordered_top_level_widgets.append(button)
        if self.web_search_edit.isVisible() and not search_added:
            self.menu_layout.addWidget(self.web_search_edit)
            self.ordered_top_level_widgets.append(self.web_search_edit)

    def effective_web_search_position(self) -> int:
        menus_count = len(self.config.get("menus", []))
        appearance = self.config.get("appearance", {})
        if not bool(appearance.get("show_web_search_bar", False)):
            return -1
        try:
            position = int(appearance.get("web_search_position", -1))
        except (TypeError, ValueError):
            position = -1
        if position < 0:
            return menus_count
        return max(0, min(position, menus_count))

    def apply_menu_button_metrics(self, button: QtWidgets.QPushButton) -> None:
        button_height = self.effective_metrics["effective_button_height"]
        button.setMinimumHeight(button_height)
        button.setMaximumHeight(button_height)
        button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

    def menu_button_metric_stylesheet(self) -> str:
        metrics = self.effective_metrics
        button_content_height = max(1, metrics["effective_button_height"] - 2)
        return (
            f"min-height: {button_content_height}px;"
            f"max-height: {button_content_height}px;"
            f"padding: 0 {metrics['horizontal_button_padding']}px;"
            f"border-radius: {metrics['effective_corner_radius']}px;"
            f"font-size: {metrics['font_size']}px;"
            "font-weight: 600;"
        )

    def apply_menu_button_style(self, button: QtWidgets.QPushButton, menu_config: dict) -> None:
        metrics_css = self.menu_button_metric_stylesheet()
        style = menu_config.get("button_style", {})
        if not style.get("use_custom_colors", False):
            if menu_config.get("enabled", True):
                button.setStyleSheet("")
            else:
                button.setStyleSheet(
                    f"""
                    QPushButton {{
                        {metrics_css}
                        color: rgba(255, 255, 255, 110);
                    }}
                    """
                )
            self.apply_menu_button_metrics(button)
            return
        text_color = style["text"] if menu_config.get("enabled", True) else "rgba(255, 255, 255, 120)"
        button.setStyleSheet(
            f"""
            QPushButton {{
                {metrics_css}
                background-color: {style["background"]};
                color: {text_color};
                border: 1px solid {style["border"]};
            }}
            QPushButton:hover {{
                background-color: {style["hover"]};
            }}
            """
        )
        self.apply_menu_button_metrics(button)

    def button_style_fallbacks(self) -> dict[str, str]:
        appearance = self.config.get("appearance", {})
        return {
            "background": appearance.get("button_background", "#3b3b3b"),
            "hover": appearance.get("button_hover", "#505050"),
            "text": appearance.get("button_text", "#ffffff"),
            "border": appearance.get("border_color", "#606060"),
        }

    def apply_menu_button_icon(self, button: QtWidgets.QPushButton, menu_config: dict) -> None:
        menu_name = str(menu_config.get("name") or "Menu")
        if menu_config.get("type") == "folder_menu":
            icon = folder_menu_icon(menu_config, button)
        else:
            icon = menu_button_icon(str(menu_config.get("icon_path") or ""))
        if icon.isNull() and menu_config.get("type") == "top_launcher":
            icon = icon_for_item(
                {
                    "type": "launcher",
                    "target": menu_config.get("target", ""),
                    "target_type": menu_config.get("target_type", "Auto Detect"),
                    "icon": "",
                },
                button,
            )
        if icon.isNull():
            if bool(menu_config.get("icon_only", False)):
                compact_size = max(10, self.effective_metrics["effective_button_height"])
                fallback_text = (menu_name.strip()[:1] or "?").upper()
                button.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon))
                button.setIconSize(QtCore.QSize(self.effective_metrics["menu_icon_size"], self.effective_metrics["menu_icon_size"]))
                button.setText("")
                button.setToolTip(menu_name)
                button.setAccessibleName(fallback_text)
                button.setFixedWidth(compact_size)
            else:
                button.setIcon(QtGui.QIcon())
                button.setText(menu_name)
                button.setToolTip("")
                self.apply_menu_button_natural_width(button)
                button.setMaximumWidth(16777215)
            return
        icon_size = self.effective_metrics["menu_icon_size"]
        button.setIcon(icon)
        button.setIconSize(QtCore.QSize(icon_size, icon_size))
        if bool(menu_config.get("icon_only", False)):
            compact_size = max(10, self.effective_metrics["effective_button_height"])
            button.setText("")
            button.setToolTip(menu_name)
            button.setFixedWidth(compact_size)
        else:
            button.setText(menu_name)
            button.setToolTip("")
            self.apply_menu_button_natural_width(button)
            button.setMaximumWidth(16777215)

    def apply_menu_button_natural_width(self, button: QtWidgets.QPushButton) -> int:
        button.setMaximumWidth(16777215)
        button.ensurePolished()
        natural_width = max(1, button.sizeHint().width(), button.minimumSizeHint().width())
        button.setMinimumWidth(natural_width)
        return natural_width

    def refresh_minimum_required_toolbar_width(self) -> int:
        metrics = self.effective_metrics or self.calculate_effective_metrics()
        edge_padding = metrics["horizontal_padding"]
        group_gap = metrics["menu_button_spacing"]
        logo_visible = not self.logo_label.isHidden()
        logo_width = self.logo_label.sizeHint().width() if logo_visible else 0
        visible_top_level_widgets = self.visible_top_level_widgets()
        menu_width = sum(
            max(widget.minimumWidth(), widget.sizeHint().width(), widget.minimumSizeHint().width())
            for widget in visible_top_level_widgets
        )
        if len(visible_top_level_widgets) > 1:
            menu_width += metrics["menu_button_spacing"] * (len(visible_top_level_widgets) - 1)
        visible_right_controls = self.visible_right_controls()
        right_controls_width = sum(button.sizeHint().width() for button in visible_right_controls)
        if len(visible_right_controls) > 1:
            right_controls_width += metrics["menu_button_spacing"] * (len(visible_right_controls) - 1)

        minimum_width = edge_padding * 2 + logo_width + menu_width + right_controls_width
        if logo_width and menu_width:
            minimum_width += group_gap
        if menu_width and right_controls_width:
            minimum_width += group_gap
        self.minimum_required_toolbar_width = max(1, minimum_width)
        return self.minimum_required_toolbar_width

    def activate_top_level_button(self, button: QtWidgets.QPushButton, menu_id: str) -> None:
        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is None or not bool(menu_config.get("enabled", True)):
            return
        if menu_config.get("type") == "top_launcher":
            self.close_active_toolbar_menu()
            launch_item(self.top_launcher_as_launcher_item(menu_config), self)
            return
        self.open_toolbar_menu(button, menu_config)

    def open_toolbar_menu_by_id(self, button: QtWidgets.QPushButton, menu_id: str) -> None:
        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is None or not bool(menu_config.get("enabled", True)):
            return
        if menu_config.get("type") == "top_launcher":
            return
        self.open_toolbar_menu(button, menu_config)

    def open_toolbar_menu(self, button: QtWidgets.QPushButton, menu_config: dict) -> None:
        self.hover_menu_timer.stop()
        menu_id = str(menu_config.get("id") or "")
        if self.active_toolbar_menu is not None and self.active_toolbar_menu_id == menu_id:
            return
        self.close_active_toolbar_menu()
        menu = self.build_qmenu(menu_config, managed=True)
        self.active_toolbar_menu = menu
        self.active_toolbar_menu_id = menu_id
        menu.aboutToHide.connect(lambda active=menu: self.clear_active_toolbar_menu(active))
        self.show_menu(self.configured_screen())
        menu.popup(button.mapToGlobal(QtCore.QPoint(0, button.height())))
        self.start_menu_switch_timer()

    def close_active_toolbar_menu(self) -> None:
        if self.active_toolbar_menu is not None:
            old_menu = self.active_toolbar_menu
            self.active_toolbar_menu = None
            self.active_toolbar_menu_id = ""
            self.stop_menu_switch_timer()
            old_menu.close()
            old_menu.deleteLater()

    def close_visible_popup_menus(self) -> None:
        self.close_active_toolbar_menu()
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QMenu) and widget.isVisible():
                widget.close()
        self.active_menu_count = 0
        self.menu_open = False
        self.mouse_out_ticks = 0

    def clear_active_toolbar_menu(self, menu: QtWidgets.QMenu) -> None:
        if self.active_toolbar_menu is menu:
            self.active_toolbar_menu = None
            self.active_toolbar_menu_id = ""
            self.stop_menu_switch_timer()

    def build_qmenu(self, menu_config: dict, managed: bool = False) -> QtWidgets.QMenu:
        menu = ManagedMenu(self) if managed else QtWidgets.QMenu(self)
        if isinstance(menu, ManagedMenu):
            menu.itemContextRequested.connect(self.open_popup_item_context)
            self.connect_managed_menu_drag(menu)
        menu.setProperty("container_id", menu_config.get("id", ""))
        self.install_menu_lifetime_hooks(menu)
        if menu_config.get("type") == "folder_menu":
            self.populate_folder_menu(menu, menu_config)
        else:
            self.populate_qmenu(menu, menu_config.get("items", []), managed=managed)
        return menu

    def populate_qmenu(self, menu: QtWidgets.QMenu, items: list[dict], managed: bool = False) -> None:
        if not items:
            empty_action = menu.addAction("No items configured")
            empty_action.setEnabled(False)
            return

        for item in items:
            item_type = item.get("type")
            if item_type == "separator":
                action = menu.addSeparator()
                self.set_action_metadata(action, item)
            elif item_type == "heading":
                action = menu.addAction(item.get("name", "Heading"))
                self.set_action_metadata(action, item)
                icon = icon_for_item(item, self)
                if not icon.isNull():
                    action.setIcon(icon)
            elif item_type == "submenu":
                if bool(item.get("enabled", True)):
                    submenu = ManagedMenu(menu) if managed else QtWidgets.QMenu(menu)
                    if isinstance(submenu, ManagedMenu):
                        submenu.itemContextRequested.connect(self.open_popup_item_context)
                        self.connect_managed_menu_drag(submenu)
                    submenu.setProperty("container_id", item.get("id", ""))
                    submenu.setTitle(item.get("name", "Submenu"))
                    self.install_menu_lifetime_hooks(submenu)
                    submenu.setIcon(icon_for_item(item, self))
                    self.populate_qmenu(submenu, item.get("items", []), managed=managed)
                    action = menu.addMenu(submenu)
                else:
                    action = menu.addAction(icon_for_item(item, self), item.get("name", "Submenu"))
                self.set_action_metadata(action, item)
            elif item_type == "folder_menu":
                if bool(item.get("enabled", True)):
                    submenu = ManagedMenu(menu) if managed else QtWidgets.QMenu(menu)
                    if isinstance(submenu, ManagedMenu):
                        submenu.itemContextRequested.connect(self.open_popup_item_context)
                        self.connect_managed_menu_drag(submenu)
                    submenu.setTitle(item.get("name", "Folder"))
                    submenu.setIcon(folder_menu_icon(item, self))
                    self.install_menu_lifetime_hooks(submenu)
                    submenu.aboutToShow.connect(lambda data=item, target=submenu: self.populate_folder_menu(target, data))
                    action = menu.addMenu(submenu)
                else:
                    action = menu.addAction(folder_menu_icon(item, self), item.get("name", "Folder"))
                self.set_action_metadata(action, item)
            elif item_type == "launcher":
                action = menu.addAction(icon_for_item(item, self), item.get("name", "Launcher"))
                self.set_action_metadata(action, item)
                action.triggered.connect(lambda checked=False, item_id=item.get("id", ""): self.open_launcher_by_id(item_id))

    def set_action_metadata(self, action: QtGui.QAction, item: dict) -> None:
        action.setData({"item_id": item.get("id", ""), "item_type": item.get("type", "")})

    def connect_managed_menu_drag(self, menu: ManagedMenu) -> None:
        menu.dragMoved.connect(self.handle_menu_drag_moved)
        menu.dragDropped.connect(self.handle_menu_drag_dropped)
        menu.dragLeft.connect(self.handle_menu_drag_left)

    def accept_copy_drop(self, event: QtCore.QEvent) -> None:
        event.setDropAction(QtCore.Qt.DropAction.CopyAction)
        event.accept()

    def open_launcher_by_id(self, item_id: str) -> None:
        item = find_any_item_by_id(self.config, item_id)
        if item is None or item.get("type") != "launcher" or not bool(item.get("enabled", True)):
            return
        launch_item(item, self)

    def populate_folder_menu(self, menu: QtWidgets.QMenu, folder_config: dict) -> None:
        menu.clear()
        folder_path = str(folder_config.get("folder_path") or "")
        if folder_config.get("show_open_folder_action", True):
            action = menu.addAction("Open This Folder")
            action.triggered.connect(lambda checked=False, path=folder_path: self.open_folder_path(path))
            menu.addSeparator()
        loading = menu.addAction("Loading...")
        loading.setEnabled(False)
        self.load_folder_menu_async(menu, folder_config)

    def load_folder_menu_async(self, menu: QtWidgets.QMenu, folder_config: dict) -> None:
        thread = QtCore.QThread(self)
        worker = FolderMenuWorker(
            str(folder_config.get("folder_path") or ""),
            bool(folder_config.get("include_files", True)),
            bool(folder_config.get("include_folders", True)),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda path, entries, error, target=menu, cfg=folder_config: self.finish_folder_menu_load(target, cfg, entries, error))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda t=thread, w=worker: self.cleanup_folder_worker(t, w))
        self.folder_menu_threads.append((thread, worker))
        thread.start()

    def cleanup_folder_worker(self, thread: QtCore.QThread, worker: FolderMenuWorker) -> None:
        self.folder_menu_threads = [(t, w) for t, w in self.folder_menu_threads if t is not thread]
        thread.deleteLater()

    def finish_folder_menu_load(self, menu: QtWidgets.QMenu, folder_config: dict, entries: list[dict], error: str) -> None:
        if menu is None:
            return
        menu.clear()
        folder_path = str(folder_config.get("folder_path") or "")
        if folder_config.get("show_open_folder_action", True):
            action = menu.addAction("Open This Folder")
            action.triggered.connect(lambda checked=False, path=folder_path: self.open_folder_path(path))
            menu.addSeparator()
        if error:
            unavailable = menu.addAction(error)
            unavailable.setEnabled(False)
            return
        if not entries:
            empty = menu.addAction("No items found")
            empty.setEnabled(False)
            return
        for entry in entries:
            if entry["is_dir"]:
                submenu = QtWidgets.QMenu(entry["name"], menu)
                submenu.setIcon(folder_icon(menu))
                self.install_menu_lifetime_hooks(submenu)
                child_config = {
                    "name": entry["name"],
                    "type": "folder_menu",
                    "folder_path": entry["path"],
                    "include_files": folder_config.get("include_files", True),
                    "include_folders": folder_config.get("include_folders", True),
                    "show_open_folder_action": folder_config.get("show_open_folder_action", True),
                    "enabled": True,
                }
                submenu.aboutToShow.connect(lambda target=submenu, cfg=child_config: self.populate_folder_menu(target, cfg))
                menu.addMenu(submenu)
            else:
                action = menu.addAction(entry["name"])
                action.triggered.connect(lambda checked=False, path=entry["path"]: self.open_file_path(path))

    def open_folder_path(self, folder_path: str) -> None:
        try:
            launch_target(folder_path, target_type="Folder")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Folder Error", f"Could not open folder.\n\n{exc}")

    def open_file_path(self, file_path: str) -> None:
        try:
            launch_target(file_path, target_type="File")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "File Error", f"Could not open file.\n\n{exc}")

    def open_popup_item_context(self, item_id: str, item_type: str, position: QtCore.QPoint) -> None:
        item = find_any_item_by_id(self.config, item_id)
        if item is None:
            return
        if item_type == "launcher":
            menu = self.build_launcher_item_context(item_id)
        elif item_type == "submenu":
            menu = self.build_submenu_item_context(item_id)
        elif item_type == "heading":
            menu = self.build_heading_item_context(item_id)
        elif item_type == "separator":
            menu = self.build_separator_item_context(item_id)
        else:
            return
        self.install_menu_lifetime_hooks(menu)
        self.show_menu(self.configured_screen())
        self.dialog_open = True
        try:
            menu.exec(position)
        finally:
            self.dialog_open = False

    def build_launcher_item_context(self, item_id: str) -> QtWidgets.QMenu:
        item = find_any_item_by_id(self.config, item_id) or {}
        location = find_item_location(self.config, item_id)
        menu = QtWidgets.QMenu(self)
        open_action = menu.addAction("Open", lambda: self.context_open_launcher(item_id))
        open_action.setEnabled(bool(item.get("enabled", True)))
        menu.addSeparator()
        menu.addAction("Edit...", lambda: self.context_edit_launcher(item_id))
        menu.addAction("Duplicate", lambda: self.context_duplicate_item(item_id))
        self.add_move_actions(menu, item_id, location)
        enabled = bool(item.get("enabled", True))
        menu.addAction("Disable Launcher" if enabled else "Enable Launcher", lambda: self.context_toggle_item(item_id))
        menu.addAction("Delete", lambda: self.context_delete_launcher(item_id))
        return menu

    def build_submenu_item_context(self, item_id: str) -> QtWidgets.QMenu:
        item = find_any_item_by_id(self.config, item_id) or {}
        location = find_item_location(self.config, item_id)
        menu = QtWidgets.QMenu(self)
        open_action = menu.addAction("Open Submenu")
        open_action.setEnabled(bool(item.get("enabled", True)))
        open_action.triggered.connect(lambda: self.show_menu(self.configured_screen()))
        menu.addSeparator()
        menu.addAction("Add Launcher...", lambda: self.context_add_launcher_to_container(item_id))
        menu.addAction("Add Submenu...", lambda: self.context_add_submenu_to_container(item_id))
        menu.addAction("Add Separator", lambda: self.context_add_separator_to_container(item_id))
        menu.addAction("Add Heading...", lambda: self.context_add_heading_to_container(item_id))
        menu.addSeparator()
        menu.addAction("Rename...", lambda: self.context_rename_submenu(item_id))
        menu.addAction("Duplicate", lambda: self.context_duplicate_item(item_id))
        self.add_move_actions(menu, item_id, location)
        enabled = bool(item.get("enabled", True))
        menu.addAction("Disable Submenu" if enabled else "Enable Submenu", lambda: self.context_toggle_item(item_id))
        menu.addAction("Delete Submenu", lambda: self.context_delete_submenu(item_id))
        return menu

    def build_heading_item_context(self, item_id: str) -> QtWidgets.QMenu:
        location = find_item_location(self.config, item_id)
        menu = QtWidgets.QMenu(self)
        menu.addAction("Rename...", lambda: self.context_rename_heading(item_id))
        menu.addAction("Duplicate", lambda: self.context_duplicate_item(item_id))
        self.add_move_actions(menu, item_id, location)
        menu.addAction("Delete Heading", lambda: self.context_delete_simple_item(item_id))
        return menu

    def build_separator_item_context(self, item_id: str) -> QtWidgets.QMenu:
        location = find_item_location(self.config, item_id)
        menu = QtWidgets.QMenu(self)
        self.add_move_actions(menu, item_id, location)
        menu.addAction("Delete Separator", lambda: self.context_delete_simple_item(item_id))
        return menu

    def add_move_actions(self, menu: QtWidgets.QMenu, item_id: str, location: dict | None) -> None:
        move_up = menu.addAction("Move Up", lambda: self.context_move_item(item_id, -1))
        move_down = menu.addAction("Move Down", lambda: self.context_move_item(item_id, 1))
        if location is None:
            move_up.setEnabled(False)
            move_down.setEnabled(False)
            return
        index = int(location["index"])
        count = len(location["items"])
        move_up.setEnabled(index > 0)
        move_down.setEnabled(index < count - 1)

    def save_and_refresh_after_menu_change(self) -> None:
        self.commit_config()

    def context_open_launcher(self, item_id: str) -> None:
        self.open_launcher_by_id(item_id)

    def context_edit_launcher(self, item_id: str) -> None:
        item = find_any_item_by_id(self.config, item_id)
        if item is None or item.get("type") != "launcher":
            return
        self.dialog_open = True
        try:
            dialog = LauncherEditorDialog(item, self, profile_id=self.current_profile_id(), asset_context=self.asset_context())
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                updated = dialog.result_item()
                updated["id"] = item_id
                if replace_item_by_id(self.config, item_id, updated):
                    self.save_and_refresh_after_menu_change()
        finally:
            self.dialog_open = False

    def context_duplicate_item(self, item_id: str) -> None:
        duplicate = duplicate_item_by_id(self.config, item_id)
        if duplicate is not None:
            profile_id = self.current_profile_id()
            if profile_id:
                isolate_profile_item_assets(duplicate, profile_id)
            self.save_and_refresh_after_menu_change()

    def context_move_item(self, item_id: str, offset: int) -> None:
        if move_item_by_id(self.config, item_id, offset):
            self.save_and_refresh_after_menu_change()

    def context_toggle_item(self, item_id: str) -> None:
        if toggle_item_enabled_by_id(self.config, item_id):
            self.save_and_refresh_after_menu_change()

    def context_delete_launcher(self, item_id: str) -> None:
        item = find_any_item_by_id(self.config, item_id)
        if item is None:
            return
        message = (
            f"Remove \"{item.get('name', 'Launcher')}\" from this toolbar menu?\n\n"
            "This removes only the toolbar shortcut.\n"
            "It will not delete the target file, folder, program, or website."
        )
        if self.confirm_delete("Delete Launcher", message) and delete_item_by_id(self.config, item_id):
            delete_managed_icon_if_unused(str(item.get("icon") or ""), self.config)
            self.save_and_refresh_after_menu_change()

    def context_delete_submenu(self, item_id: str) -> None:
        item = find_any_item_by_id(self.config, item_id)
        if item is None:
            return
        count = count_nested_descendants(item)
        message = (
            f"Delete \"{item.get('name', 'Submenu')}\" and all {count} items inside it?\n\n"
            "This removes only toolbar shortcuts.\n"
            "It will not delete any files, folders, programs, or websites."
        )
        if self.confirm_delete("Delete Submenu", message) and delete_item_by_id(self.config, item_id):
            delete_managed_menu_icon_if_unused(item, self.config)
            self.save_and_refresh_after_menu_change()

    def context_delete_simple_item(self, item_id: str) -> None:
        item = find_any_item_by_id(self.config, item_id)
        if item is not None and delete_item_by_id(self.config, item_id):
            delete_managed_icon_if_unused(str(item.get("icon") or ""), self.config)
            self.save_and_refresh_after_menu_change()

    def context_add_launcher_to_container(self, container_id: str) -> None:
        self.dialog_open = True
        try:
            dialog = LauncherEditorDialog(
                {"type": "launcher", "name": "New Launcher"},
                self,
                profile_id=self.current_profile_id(),
                asset_context=self.asset_context(),
            )
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                if add_launcher_to_container_by_id(self.config, container_id, dialog.result_item()):
                    self.save_and_refresh_after_menu_change()
        finally:
            self.dialog_open = False

    def context_add_submenu_to_container(self, container_id: str) -> None:
        self.dialog_open = True
        try:
            name, ok = QtWidgets.QInputDialog.getText(self, "Add Submenu", "Submenu name:")
            if ok and add_submenu_to_container_by_id(self.config, container_id, name.strip() or "Submenu"):
                self.save_and_refresh_after_menu_change()
        finally:
            self.dialog_open = False

    def context_add_separator_to_container(self, container_id: str) -> None:
        if add_separator_to_container_by_id(self.config, container_id):
            self.save_and_refresh_after_menu_change()

    def context_add_heading_to_container(self, container_id: str) -> None:
        self.dialog_open = True
        try:
            name, ok = QtWidgets.QInputDialog.getText(self, "Add Heading", "Heading text:")
            if ok and add_heading_to_container_by_id(self.config, container_id, name.strip() or "Heading"):
                self.save_and_refresh_after_menu_change()
        finally:
            self.dialog_open = False

    def context_rename_submenu(self, item_id: str) -> None:
        item = find_any_item_by_id(self.config, item_id)
        if item is None:
            return
        self.dialog_open = True
        try:
            name, ok = QtWidgets.QInputDialog.getText(self, "Rename Submenu", "Submenu name:", text=item.get("name", "Submenu"))
            if ok:
                item["name"] = name.strip() or "Submenu"
                self.save_and_refresh_after_menu_change()
        finally:
            self.dialog_open = False

    def context_rename_heading(self, item_id: str) -> None:
        item = find_any_item_by_id(self.config, item_id)
        if item is None:
            return
        self.dialog_open = True
        try:
            name, ok = QtWidgets.QInputDialog.getText(self, "Rename Heading", "Heading text:", text=item.get("name", "Heading"))
            if ok:
                item["name"] = name.strip() or "Heading"
                self.save_and_refresh_after_menu_change()
        finally:
            self.dialog_open = False

    def confirm_delete(self, title: str, message: str) -> bool:
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(message)
        delete_button = box.addButton("Delete", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        self.dialog_open = True
        try:
            box.exec()
            return box.clickedButton() == delete_button
        finally:
            self.dialog_open = False

    def open_menu_button_context(
        self,
        button: QtWidgets.QPushButton,
        menu_id: str,
        position: QtCore.QPoint,
        deferred: bool = False,
    ) -> None:
        if deferred:
            self.top_button_context_pending = False
        if self.top_button_context_active:
            return
        if self.top_button_context_pending and not deferred:
            return
        self.hover_menu_timer.stop()
        self.close_active_toolbar_menu()
        self.stop_menu_switch_timer()
        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is None:
            return
        index = find_menu_index_by_id(self.config, menu_id)
        context = QtWidgets.QMenu(self)
        self.install_menu_lifetime_hooks(context)
        if menu_config.get("type") == "top_launcher":
            self.populate_top_launcher_button_context(context, menu_id, menu_config, index)
            self.show_menu(self.configured_screen())
            self.dialog_open = True
            self.top_button_context_active = True
            try:
                context.exec(button.mapToGlobal(position))
            finally:
                self.top_button_context_active = False
                self.dialog_open = False
            return
        if menu_config.get("type") == "folder_menu":
            self.populate_folder_menu_button_context(context, button, menu_id, menu_config, index)
            self.show_menu(self.configured_screen())
            self.dialog_open = True
            self.top_button_context_active = True
            try:
                context.exec(button.mapToGlobal(position))
            finally:
                self.top_button_context_active = False
                self.dialog_open = False
            return

        open_action = context.addAction("Open Menu")
        open_action.setEnabled(bool(menu_config.get("enabled", True)))
        open_action.triggered.connect(lambda: self.open_toolbar_menu(button, menu_config))
        context.addSeparator()

        context.addAction("Add Launcher...", lambda: self.context_add_launcher(menu_id))
        context.addAction("Add Submenu...", lambda: self.context_add_submenu(menu_id))
        context.addAction("Edit Menu...", lambda: self.context_edit_menu(menu_id))
        context.addAction("Duplicate Menu", lambda: self.context_duplicate_menu(menu_id))
        context.addSeparator()

        move_left = context.addAction("Move Left", lambda: self.context_move_menu(menu_id, -1))
        move_left.setEnabled(self.can_move_menu_in_top_level_order(menu_id, -1))
        move_right = context.addAction("Move Right", lambda: self.context_move_menu(menu_id, 1))
        move_right.setEnabled(self.can_move_menu_in_top_level_order(menu_id, 1))
        enabled = bool(menu_config.get("enabled", True))
        context.addAction("Disable Menu" if enabled else "Enable Menu", lambda: self.context_toggle_menu(menu_id))
        context.addAction("Delete Menu", lambda: self.context_delete_menu(menu_id))

        self.show_menu(self.configured_screen())
        self.dialog_open = True
        self.top_button_context_active = True
        try:
            context.exec(button.mapToGlobal(position))
        finally:
            self.top_button_context_active = False
            self.dialog_open = False

    def populate_top_launcher_button_context(
        self,
        context: QtWidgets.QMenu,
        menu_id: str,
        launcher_config: dict,
        index: int,
    ) -> None:
        open_action = context.addAction("Open", lambda: self.context_open_top_launcher(menu_id))
        open_action.setEnabled(bool(launcher_config.get("enabled", True)))
        context.addSeparator()
        context.addAction("Edit Launcher...", lambda: self.context_edit_top_launcher(menu_id))
        move_left = context.addAction("Move Left", lambda: self.context_move_menu(menu_id, -1))
        move_left.setEnabled(self.can_move_menu_in_top_level_order(menu_id, -1))
        move_right = context.addAction("Move Right", lambda: self.context_move_menu(menu_id, 1))
        move_right.setEnabled(self.can_move_menu_in_top_level_order(menu_id, 1))
        enabled = bool(launcher_config.get("enabled", True))
        context.addAction("Disable" if enabled else "Enable", lambda: self.context_toggle_menu(menu_id))
        context.addAction("Delete", lambda: self.context_delete_menu(menu_id))

    def populate_folder_menu_button_context(
        self,
        context: QtWidgets.QMenu,
        button: QtWidgets.QPushButton,
        menu_id: str,
        menu_config: dict,
        index: int,
    ) -> None:
        context.addAction("Open Root Folder", lambda: self.open_folder_path(menu_config.get("folder_path", "")))
        context.addAction("Refresh", lambda: self.refresh_folder_menu(button, menu_id))
        context.addAction("Edit Folder Menu...", lambda: self.context_edit_folder_menu(menu_id))
        context.addAction("Rename", lambda: self.context_rename_folder_menu(menu_id))
        context.addSeparator()
        move_left = context.addAction("Move Left", lambda: self.context_move_menu(menu_id, -1))
        move_left.setEnabled(self.can_move_menu_in_top_level_order(menu_id, -1))
        move_right = context.addAction("Move Right", lambda: self.context_move_menu(menu_id, 1))
        move_right.setEnabled(self.can_move_menu_in_top_level_order(menu_id, 1))
        context.addAction("Delete Menu", lambda: self.context_delete_menu(menu_id))

    def refresh_folder_menu(self, button: QtWidgets.QPushButton, menu_id: str) -> None:
        self.close_active_toolbar_menu()
        self.open_toolbar_menu_by_id(button, menu_id)

    def context_rename_folder_menu(self, menu_id: str) -> None:
        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is None:
            return
        self.dialog_open = True
        try:
            name, ok = QtWidgets.QInputDialog.getText(self, "Rename Folder Menu", "Menu name:", text=menu_config.get("name", "Folder"))
            if ok:
                menu_config["name"] = name.strip() or "Folder"
                self.commit_config()
        finally:
            self.dialog_open = False

    def context_edit_folder_menu(self, menu_id: str) -> None:
        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is None:
            return
        self.dialog_open = True
        try:
            dialog = FolderMenuPropertiesDialog(
                menu_config,
                self,
                profile_id=self.current_profile_id(),
                asset_context=self.asset_context(),
                top_level=True,
                button_fallbacks=self.button_style_fallbacks(),
            )
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                updated = dialog.result_menu()
                updated["id"] = menu_config["id"]
                index = find_menu_index_by_id(self.config, menu_id)
                if index >= 0:
                    self.config["menus"][index] = updated
                    self.commit_config()
        finally:
            self.dialog_open = False

    def context_add_launcher(self, menu_id: str) -> None:
        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is None:
            return
        self.dialog_open = True
        try:
            dialog = LauncherEditorDialog(
                {"type": "launcher", "name": "New Launcher"},
                self,
                profile_id=self.current_profile_id(),
                asset_context=self.asset_context(),
            )
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                menu_config.setdefault("items", []).append(dialog.result_item())
                self.commit_config()
        finally:
            self.dialog_open = False

    def context_add_submenu(self, menu_id: str) -> None:
        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is None:
            return
        self.dialog_open = True
        try:
            name, ok = QtWidgets.QInputDialog.getText(self, "Add Submenu", "Submenu name:")
            if ok:
                menu_config.setdefault("items", []).append({"name": name.strip() or "Submenu", "type": "submenu", "items": []})
                self.commit_config()
        finally:
            self.dialog_open = False

    def context_edit_menu(self, menu_id: str) -> None:
        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is None:
            return
        self.dialog_open = True
        try:
            dialog = MenuPropertiesDialog(
                menu_config,
                self.config["appearance"],
                self,
                profile_id=self.current_profile_id(),
                asset_context=self.asset_context(),
            )
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                updated = dialog.result_menu()
                updated["id"] = menu_config["id"]
                index = find_menu_index_by_id(self.config, menu_id)
                if index >= 0:
                    self.config["menus"][index] = updated
                    self.commit_config()
        finally:
            self.dialog_open = False

    def context_duplicate_menu(self, menu_id: str) -> None:
        duplicate = duplicate_menu_by_id(self.config, menu_id)
        if duplicate is not None:
            profile_id = self.current_profile_id()
            if profile_id:
                isolate_profile_menu_assets(duplicate, profile_id)
            self.commit_config()

    def context_move_menu(self, menu_id: str, offset: int) -> None:
        if self.context_move_menu_in_top_level_order(menu_id, offset):
            self.commit_config()

    def can_move_menu_in_top_level_order(self, menu_id: str, offset: int) -> bool:
        menu_index = find_menu_index_by_id(self.config, menu_id)
        if menu_index < 0:
            return False
        items = self.ordered_top_level_items()
        current_index = next(
            (
                index
                for index, item in enumerate(items)
                if item[0] == "menu" and item[1] == menu_index
            ),
            -1,
        )
        return 0 <= current_index + offset < len(items)

    def ordered_top_level_items(self) -> list[tuple[str, int | None]]:
        menus = self.config.get("menus", [])
        items: list[tuple[str, int | None]] = []
        search_position = self.effective_web_search_position()
        search_added = False
        for index, _menu in enumerate(menus):
            if not search_added and index == search_position:
                items.append(("search", None))
                search_added = True
            items.append(("menu", index))
        if bool(self.config.get("appearance", {}).get("show_web_search_bar", False)) and not search_added:
            items.append(("search", None))
        return items

    def save_web_search_position_from_order(self, items: list[tuple[str, int | None]], menus_count: int) -> None:
        search_index = next((index for index, item in enumerate(items) if item[0] == "search"), -1)
        if search_index < 0:
            return
        menus_before = sum(1 for item in items[:search_index] if item[0] == "menu")
        self.config.setdefault("appearance", {})["web_search_position"] = (
            -1 if menus_before >= menus_count else menus_before
        )

    def context_move_menu_in_top_level_order(self, menu_id: str, offset: int) -> bool:
        menu_index = find_menu_index_by_id(self.config, menu_id)
        if menu_index < 0:
            return False
        items = self.ordered_top_level_items()
        current_index = next(
            (
                index
                for index, item in enumerate(items)
                if item[0] == "menu" and item[1] == menu_index
            ),
            -1,
        )
        target_index = current_index + offset
        if current_index < 0 or not 0 <= target_index < len(items):
            return False
        items[current_index], items[target_index] = items[target_index], items[current_index]
        old_menus = self.config.get("menus", [])
        self.config["menus"] = [
            copy.deepcopy(old_menus[index])
            for kind, index in items
            if kind == "menu" and index is not None
        ]
        self.save_web_search_position_from_order(items, len(self.config["menus"]))
        return True

    def context_edit_web_search_bar(self) -> None:
        appearance = self.config.setdefault("appearance", {})
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Edit Web Search Bar")
        form = QtWidgets.QFormLayout(dialog)
        width_spin = QtWidgets.QSpinBox(dialog)
        width_spin.setRange(100, 500)
        width_spin.setValue(int(appearance.get("web_search_width", 180)))
        placeholder_edit = QtWidgets.QLineEdit(
            str(appearance.get("web_search_placeholder") or "Search the web..."),
            dialog,
        )
        engine_combo = QtWidgets.QComboBox(dialog)
        for label in ("Google", "Bing", "DuckDuckGo", "Yahoo", "Custom"):
            engine_combo.addItem(label, label)
        engine_index = engine_combo.findData(appearance.get("web_search_engine", "Google"))
        engine_combo.setCurrentIndex(max(0, engine_index))
        custom_url_edit = QtWidgets.QLineEdit(
            str(appearance.get("web_search_custom_url") or ""),
            dialog,
        )
        custom_url_edit.setPlaceholderText("https://example.com/search?q={query}")
        def update_custom_state() -> None:
            custom_url_edit.setEnabled(str(engine_combo.currentData() or "Google") == "Custom")
        engine_combo.currentIndexChanged.connect(lambda *_args: update_custom_state())
        update_custom_state()
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow("Search bar width", width_spin)
        form.addRow("Placeholder text", placeholder_edit)
        form.addRow("Search engine", engine_combo)
        form.addRow("Custom search URL", custom_url_edit)
        form.addRow(buttons)
        self.dialog_open = True
        try:
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                appearance["web_search_width"] = width_spin.value()
                appearance["web_search_placeholder"] = placeholder_edit.text().strip() or "Search the web..."
                appearance["web_search_engine"] = str(engine_combo.currentData() or "Google")
                appearance["web_search_custom_url"] = custom_url_edit.text().strip()
                self.commit_config()
        finally:
            self.dialog_open = False

    def context_move_web_search_bar(self, offset: int) -> None:
        items = self.ordered_top_level_items()
        current_index = next((index for index, item in enumerate(items) if item[0] == "search"), -1)
        target_index = current_index + offset
        if current_index < 0 or not 0 <= target_index < len(items):
            return
        items[current_index], items[target_index] = items[target_index], items[current_index]
        self.save_web_search_position_from_order(items, len(self.config.get("menus", [])))
        self.commit_config()

    def context_hide_web_search_bar(self) -> None:
        self.config.setdefault("appearance", {})["show_web_search_bar"] = False
        self.commit_config()

    def context_paste_web_search_text(self) -> None:
        self.web_search_edit.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        self.web_search_edit.paste()
        self.web_search_edit.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)

    def context_select_all_web_search_text(self) -> None:
        self.web_search_edit.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        self.web_search_edit.selectAll()

    def open_web_search_context_menu(self, position: QtCore.QPoint) -> None:
        context = QtWidgets.QMenu(self)
        self.install_menu_lifetime_hooks(context)

        clipboard = QtWidgets.QApplication.clipboard()
        paste_action = context.addAction("Paste", self.context_paste_web_search_text)
        paste_action.setEnabled(bool(clipboard and clipboard.text()))
        context.addAction("Select All", self.context_select_all_web_search_text)
        context.addSeparator()

        context.addAction("Edit Search Bar...", self.context_edit_web_search_bar)
        items = self.ordered_top_level_items()
        current_index = next((index for index, item in enumerate(items) if item[0] == "search"), -1)
        move_left = context.addAction("Move Left", lambda: self.context_move_web_search_bar(-1))
        move_left.setEnabled(current_index > 0)
        move_right = context.addAction("Move Right", lambda: self.context_move_web_search_bar(1))
        move_right.setEnabled(0 <= current_index < len(items) - 1)
        context.addSeparator()
        context.addAction("Hide Search Bar", self.context_hide_web_search_bar)

        self.show_menu(self.configured_screen())
        self.dialog_open = True
        self.top_button_context_active = True
        try:
            context.exec(position)
        finally:
            self.top_button_context_active = False
            self.dialog_open = False

    def context_toggle_menu(self, menu_id: str) -> None:
        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is not None:
            menu_config["enabled"] = not bool(menu_config.get("enabled", True))
            self.commit_config()

    def top_launcher_as_launcher_item(self, launcher_config: dict) -> dict:
        return top_launcher_to_launcher_item(launcher_config)

    def top_launcher_as_editor_item(self, launcher_config: dict) -> dict:
        return top_launcher_to_editor_item(
            launcher_config,
            self.button_style_fallbacks(),
        )

    def context_open_top_launcher(self, menu_id: str) -> None:
        launcher_config = find_menu_by_id(self.config, menu_id)
        if launcher_config is None or launcher_config.get("type") != "top_launcher" or not bool(launcher_config.get("enabled", True)):
            return
        launch_item(self.top_launcher_as_launcher_item(launcher_config), self)

    def context_edit_top_launcher(self, menu_id: str) -> None:
        launcher_config = find_menu_by_id(self.config, menu_id)
        if launcher_config is None or launcher_config.get("type") != "top_launcher":
            return
        self.dialog_open = True
        try:
            dialog = LauncherEditorDialog(
                self.top_launcher_as_editor_item(launcher_config),
                self,
                global_appearance=self.config["appearance"],
                top_level=True,
                profile_id=self.current_profile_id(),
                asset_context=self.asset_context(),
            )
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                updated_item = dialog.result_item()
                updated = {
                    **launcher_config,
                    "id": launcher_config["id"],
                    "name": updated_item.get("name", "Launcher"),
                    "type": "top_launcher",
                    "target": updated_item.get("target", ""),
                    "target_type": updated_item.get("target_type", "Auto Detect"),
                    "arguments": updated_item.get("arguments", ""),
                    "working_directory": updated_item.get("working_directory", ""),
                    "python_mode": updated_item.get("python_mode", "Automatic"),
                    "enabled": bool(updated_item.get("enabled", True)),
                    "accept_dropped_files": bool(updated_item.get("accept_dropped_files", False)),
                    "folder_drop_action": updated_item.get("folder_drop_action", launcher_config.get("folder_drop_action", "move")),
                    "icon_path": updated_item.get("icon", launcher_config.get("icon_path", "")),
                    "icon_only": bool(updated_item.get("icon_only", launcher_config.get("icon_only", False))),
                    "button_style": copy.deepcopy(updated_item.get("button_style", launcher_config.get("button_style", {}))),
                }
                index = find_menu_index_by_id(self.config, menu_id)
                if index >= 0:
                    self.config["menus"][index] = updated
                    self.commit_config()
        finally:
            self.dialog_open = False

    def context_delete_menu(self, menu_id: str) -> None:
        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is None:
            return
        count = count_nested_descendants(menu_config)
        message = (
            f"Delete \"{menu_config.get('name', 'Menu')}\" and all {count} items inside it?\n\n"
            "This only removes the toolbar shortcuts. It will not delete any files from your computer."
        )
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Delete Menu")
        box.setText(message)
        delete_button = box.addButton("Delete", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        self.dialog_open = True
        try:
            box.exec()
            if box.clickedButton() == delete_button and delete_menu_by_id(self.config, menu_id):
                delete_managed_menu_icon_if_unused(menu_config, self.config)
                self.commit_config()
        finally:
            self.dialog_open = False

    def handle_logo_left_click(self) -> None:
        logo = self.config["logo"]
        action = logo.get("left_click_action", "none")
        if action == "open_menu":
            self.open_logo_context_menu(self.logo_label.mapToGlobal(QtCore.QPoint(0, self.logo_label.height())))
        elif action == "open_first_item":
            item = self.first_enabled_launcher(logo.get("menu_items", []))
            if item is not None:
                launch_item(item, self)
        elif action == "custom_launcher" and isinstance(logo.get("left_click_launcher"), dict):
            launch_item(logo["left_click_launcher"], self)

    def first_enabled_launcher(self, items: list[dict]) -> dict | None:
        for item in items:
            if item.get("type") == "launcher" and item.get("enabled", True):
                return item
            if item.get("type") == "submenu":
                found = self.first_enabled_launcher(item.get("items", []))
                if found is not None:
                    return found
        return None

    def open_logo_context_menu(self, position: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        self.install_menu_lifetime_hooks(menu)
        items = self.config["logo"].get("menu_items", [])
        if items:
            self.populate_qmenu(menu, items)
            menu.addSeparator()
        edit_logo = menu.addAction("Edit Logo...")
        edit_logo.triggered.connect(self.open_direct_logo_editor)
        settings = menu.addAction("Toolbar Settings...")
        settings.triggered.connect(self.open_settings)
        self.show_menu(self.configured_screen())
        menu.exec(position)

    def open_direct_logo_editor(self) -> None:
        self.dialog_open = True
        try:
            dialog = LogoEditorDialog(
                self.config["logo"],
                self.safe_int(self.config.get("logo", {}).get("height"), DEFAULT_CONFIG["logo"]["height"]),
                self,
                profile_id=self.current_profile_id(),
                asset_context=self.asset_context(),
            )
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                self.config["logo"] = dialog.result_logo()
                self.commit_config()
        finally:
            self.dialog_open = False

    def mark_menu_open(self) -> None:
        if self._removing:
            return
        self.active_menu_count += 1
        self.menu_open = True
        self.mouse_out_ticks = 0

    def mark_menu_closed(self) -> None:
        QtCore.QTimer.singleShot(100, self.decrement_menu_count)

    def install_menu_lifetime_hooks(self, menu: QtWidgets.QMenu) -> None:
        menu.aboutToShow.connect(self.mark_menu_open)
        menu.aboutToHide.connect(self.mark_menu_closed)

    def decrement_menu_count(self) -> None:
        if self._removing:
            return
        self.active_menu_count = max(0, self.active_menu_count - 1)
        self.menu_open = self.active_menu_count > 0
        self.mouse_out_ticks = 0

    def open_settings(self) -> None:
        self.manager.open_settings(self.monitor_id)

    def web_search_url(self, search_text: str) -> tuple[str | None, str]:
        appearance = self.config.get("appearance", {})
        encoded_query = quote_plus(search_text)
        engine = str(appearance.get("web_search_engine") or "Google")
        providers = {
            "Google": "https://www.google.com/search?q={query}",
            "Bing": "https://www.bing.com/search?q={query}",
            "DuckDuckGo": "https://duckduckgo.com/?q={query}",
            "Yahoo": "https://search.yahoo.com/search?p={query}",
        }
        if engine == "Custom":
            template = str(appearance.get("web_search_custom_url") or "").strip()
            if "{query}" not in template:
                return None, "Custom search URL must include {query}."
            return template.replace("{query}", encoded_query), ""
        template = providers.get(engine, providers["Google"])
        return template.replace("{query}", encoded_query), ""

    def submit_web_search(self) -> None:
        search_text = self.web_search_edit.text().strip()
        if not search_text:
            return
        url_text, error = self.web_search_url(search_text)
        if not url_text:
            QtWidgets.QMessageBox.warning(
                self,
                "Web Search",
                error or "The web search settings are invalid.",
            )
            return
        success = QtGui.QDesktopServices.openUrl(QtCore.QUrl(url_text))
        if success:
            self.web_search_edit.clear()
            return
        QtWidgets.QMessageBox.warning(
            self,
            "Web Search",
            "Could not open the search in your default web browser.",
        )

    def asset_context(self) -> AssetContext:
        return AssetContext(
            str(self.config.get("active_user_profile_id") or "default"),
            self.current_profile_id(),
        )

    def configured_screen(self) -> QtGui.QScreen | None:
        screens = QtGui.QGuiApplication.screens()
        if not screens:
            return None
        screen = screen_for_monitor_id(self.monitor_id)
        if screen is not None:
            return screen
        return QtGui.QGuiApplication.primaryScreen() or screens[0]

    def show_on_configured_screen(self) -> None:
        self.show_menu(self.configured_screen())

    def toolbar_uses_auto_width(self) -> bool:
        appearance = self.config.get("appearance", {})
        return bool(appearance.get("auto_toolbar_width", True)) if isinstance(appearance, dict) else True

    def custom_toolbar_rect(self, screen: QtGui.QScreen, hidden: bool = False) -> QtCore.QRect:
        appearance = self.config.get("appearance", {})
        available = screen.availableGeometry()
        height = self.config["appearance"]["toolbar_height"]
        requested_width = self.safe_int(appearance.get("toolbar_width", 1000), 1000)
        minimum_required_width = self.refresh_minimum_required_toolbar_width()
        effective_width = max(max(300, requested_width), minimum_required_width)
        width = max(1, min(effective_width, available.width()))
        self.effective_toolbar_width = width
        if requested_width < minimum_required_width:
            message = f"Toolbar requires at least {minimum_required_width} px for its current contents."
            self.setToolTip(message)
            self.toolbar_surface.setToolTip(message)
        else:
            self.setToolTip("")
            self.toolbar_surface.setToolTip("")
        alignment = str(appearance.get("horizontal_alignment") or "center").lower()
        if alignment not in {"left", "center", "right"}:
            alignment = "center"
        offset = self.safe_int(appearance.get("horizontal_offset", 0), 0)

        if alignment == "left":
            x = available.left() + offset
        elif alignment == "right":
            x = available.right() - width + 1 + offset
        else:
            x = available.left() + (available.width() - width) // 2 + offset

        min_x = available.left()
        max_x = available.right() - width + 1
        x = max(min_x, min(max_x, x))
        y = available.top() - height - 2 if hidden else available.top()
        self.setFixedWidth(width)
        return QtCore.QRect(x, y, width, height)

    def get_visible_rect(self, screen: QtGui.QScreen) -> QtCore.QRect:
        height = self.config["appearance"]["toolbar_height"]
        if not self.toolbar_uses_auto_width():
            return self.custom_toolbar_rect(screen, hidden=False)
        geometry = screen.geometry()
        self.effective_toolbar_width = geometry.width()
        self.setToolTip("")
        self.toolbar_surface.setToolTip("")
        self.setFixedWidth(max(1, geometry.width()))
        return QtCore.QRect(geometry.left(), geometry.top(), geometry.width(), height)

    def get_hidden_rect(self, screen: QtGui.QScreen) -> QtCore.QRect:
        height = self.config["appearance"]["toolbar_height"]
        if not self.toolbar_uses_auto_width():
            return self.custom_toolbar_rect(screen, hidden=True)
        geometry = screen.geometry()
        self.effective_toolbar_width = geometry.width()
        self.setToolTip("")
        self.toolbar_surface.setToolTip("")
        self.setFixedWidth(max(1, geometry.width()))
        return QtCore.QRect(geometry.left(), geometry.top() - height - 2, geometry.width(), height)

    def position_hidden(self, screen: QtGui.QScreen | None) -> None:
        if screen is None:
            return
        self.current_screen = screen
        self.setGeometry(self.get_hidden_rect(screen))
        self.is_open = False

    def show_menu(self, screen: QtGui.QScreen | None) -> None:
        if screen is None:
            return
        screen_changed = screen != self.current_screen
        self.current_screen = screen
        visible_rect = self.get_visible_rect(screen)
        hidden_rect = self.get_hidden_rect(screen)

        if (
            self.is_open
            and not screen_changed
            and self.geometry() == visible_rect
        ):
            self.mouse_out_ticks = 0
            return

        self.animation.stop()
        if screen_changed or not self.is_open:
            self.setGeometry(hidden_rect)
        self.show()
        self.raise_()
        self.animation.setStartValue(self.geometry())
        self.animation.setEndValue(visible_rect)
        self.animation.start()
        self.is_open = True
        self.mouse_out_ticks = 0

    def hide_menu(self) -> None:
        if not self.is_open or self.current_screen is None:
            return
        if self.current_screen not in QtGui.QGuiApplication.screens():
            self.current_screen = None
            self.is_open = False
            self.hide()
            return
        self.animation.stop()
        self.animation.setStartValue(self.geometry())
        self.animation.setEndValue(self.get_hidden_rect(self.current_screen))
        self.animation.start()
        self.is_open = False
        self.mouse_out_ticks = 0

    def check_mouse_position(self) -> None:
        if self._removing:
            return
        cursor_position = QtGui.QCursor.pos()
        screen = self.configured_screen()
        if screen is None:
            return

        screen_under_mouse = QtGui.QGuiApplication.screenAt(cursor_position)
        if screen_under_mouse != screen:
            if self.is_open and not self.should_hold_open():
                self.hide_menu()
            return

        geometry = screen.geometry()
        trigger_height = self.config["behavior"]["trigger_height"]
        touching_top_edge = (
            geometry.left() <= cursor_position.x() <= geometry.right()
            and geometry.top() <= cursor_position.y() <= geometry.top() + trigger_height
        )

        if touching_top_edge:
            if not self.is_open:
                self.show_menu(screen)
            else:
                self.mouse_out_ticks = 0
            return

        if not self.is_open or self.should_hold_open():
            return

        if self.frameGeometry().contains(cursor_position):
            self.mouse_out_ticks = 0
            return

        self.mouse_out_ticks += 1
        checks_to_hide = max(1, round(self.config["behavior"]["hide_delay_ms"] / 50))
        if self.mouse_out_ticks >= checks_to_hide:
            self.hide_menu()

    def should_hold_open(self) -> bool:
        settings_open = self.manager.settings_is_visible()
        search_active = (
            hasattr(self, "web_search_edit")
            and self.web_search_edit.isVisible()
            and self.web_search_edit.hasFocus()
        )
        return self.menu_open or self.drag_active or self.drop_dialog_open or self.dialog_open or settings_open or search_active

    def top_menu_button_at_global_position(self, global_position: QtCore.QPoint) -> QtWidgets.QPushButton | None:
        for button in self.menu_buttons:
            if not button.isVisible() or not button.isEnabled():
                continue
            if button.rect().contains(button.mapFromGlobal(global_position)):
                return button
        return None

    def handle_top_button_right_press(
        self,
        button: QtWidgets.QPushButton,
        global_position: QtCore.QPoint,
    ) -> bool:
        menu_id = str(button.property("menu_id") or "")
        if not menu_id:
            return False

        self.hover_menu_timer.stop()
        self.stop_menu_switch_timer()
        self.drag_open_timer.stop()
        self.hovered_menu_id = ""
        self.hovered_menu_button = None
        self.switch_candidate_menu_id = ""
        self.switch_candidate_button = None
        self.drag_open_button = None
        self.drag_open_menu = None
        self.drag_open_action = None
        self.close_visible_popup_menus()

        local_position = button.mapFromGlobal(global_position)
        self.top_button_context_pending = True
        QtCore.QTimer.singleShot(
            40,
            lambda source=button, source_menu_id=menu_id, position=local_position: self.open_menu_button_context(
                source,
                source_menu_id,
                position,
                deferred=True,
            ),
        )
        return True

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is getattr(self, "web_search_edit", None):
            if event.type() == QtCore.QEvent.Type.MouseButtonPress and isinstance(event, QtGui.QMouseEvent):
                if event.button() == QtCore.Qt.MouseButton.RightButton:
                    self.open_web_search_context_menu(event.globalPosition().toPoint())
                    return True
            return super().eventFilter(watched, event)

        if event.type() == QtCore.QEvent.Type.MouseButtonPress and isinstance(event, QtGui.QMouseEvent):
            if event.button() == QtCore.Qt.MouseButton.RightButton:
                global_position = event.globalPosition().toPoint()
                button = self.top_menu_button_at_global_position(global_position)
                if button is not None:
                    return self.handle_top_button_right_press(button, global_position)

        tooltip_buttons = tuple(
            button
            for button in (
                getattr(self, "settings_button", None),
                getattr(self, "close_button", None),
            )
            if button is not None
        )

        if watched in tooltip_buttons:
            if event.type() == QtCore.QEvent.Type.Enter:
                button = watched

                tooltip_position = button.mapToGlobal(
                    QtCore.QPoint(
                        button.width() // 2,
                        button.height() + 6,
                    )
                )

                QtWidgets.QToolTip.showText(
                    tooltip_position,
                    button.toolTip(),
                    button,
                )

            elif event.type() in (
                QtCore.QEvent.Type.Leave,
                QtCore.QEvent.Type.MouseButtonPress,
                QtCore.QEvent.Type.Hide,
            ):
                QtWidgets.QToolTip.hideText()

        if isinstance(watched, QtWidgets.QPushButton) and watched in self.menu_buttons:
            if event.type() == QtCore.QEvent.Type.DragEnter:
                drag_event = event
                if extract_targets_from_mime_data(drag_event.mimeData()):
                    self.drag_active = True
                    self.show_menu(self.configured_screen())
                    self.accept_copy_drop(drag_event)
                    return True

            elif event.type() == QtCore.QEvent.Type.DragMove:
                drag_event = event
                if extract_targets_from_mime_data(drag_event.mimeData()):
                    self.drag_active = True

                    global_position = watched.mapToGlobal(
                        drag_event.position().toPoint()
                    )

                    self.handle_top_level_button_drag_move(
                        watched,
                        global_position,
                        bool(extract_local_paths_from_mime_data(drag_event.mimeData())),
                    )
                    self.accept_copy_drop(drag_event)
                    return True

            elif event.type() == QtCore.QEvent.Type.Drop:
                drop_event = event
                paths = extract_targets_from_mime_data(drop_event.mimeData())
                local_paths = extract_local_paths_from_mime_data(drop_event.mimeData())
                self.drag_active = False
                self.clear_drag_state()
                if paths and self.handle_top_level_button_drop(watched, paths, local_paths):
                    self.accept_copy_drop(drop_event)
                    return True

            elif event.type() == QtCore.QEvent.Type.DragLeave:
                self.drag_active = False
                self.clear_drag_state()
                event.accept()
                return True

            if event.type() == QtCore.QEvent.Type.Enter:
                self.schedule_hover_menu(watched)

            elif event.type() == QtCore.QEvent.Type.Leave:
                self.cancel_hover_menu_if_pending(watched)

            elif event.type() == QtCore.QEvent.Type.MouseButtonPress:
                mouse_event = event

                if mouse_event.button() == QtCore.Qt.MouseButton.MiddleButton:
                    self.hover_menu_timer.stop()
                    return True

                if mouse_event.button() == QtCore.Qt.MouseButton.RightButton:
                    return self.handle_top_button_right_press(watched, mouse_event.globalPosition().toPoint())

        return super().eventFilter(watched, event)

    def schedule_hover_menu(self, button: QtWidgets.QPushButton) -> None:
        if self.top_button_context_pending or self.top_button_context_active:
            return
        if not self.config["behavior"].get("open_menus_on_hover", True):
            return
        menu_id = str(button.property("menu_id") or "")
        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is None or not bool(menu_config.get("enabled", True)):
            return
        if menu_config.get("type") == "top_launcher":
            return
        if not self.can_open_toolbar_menu_from_hover():
            return
        self.hovered_menu_id = menu_id
        self.hovered_menu_button = button
        self.hover_menu_timer.start(self.config["behavior"]["menu_hover_delay_ms"])

    def cancel_hover_menu_if_pending(self, button: QtWidgets.QPushButton) -> None:
        if self.hovered_menu_button is button:
            self.hover_menu_timer.stop()
            self.hovered_menu_id = ""
            self.hovered_menu_button = None

    def can_open_toolbar_menu_from_hover(self) -> bool:
        settings_open = self.manager.settings_is_visible()
        if settings_open or self.dialog_open or self.drop_dialog_open or self.drag_active:
            return False
        return not self.menu_open or self.active_toolbar_menu is not None

    def open_hovered_toolbar_menu(self) -> None:
        if self.top_button_context_pending or self.top_button_context_active:
            return
        button = self.hovered_menu_button
        menu_id = self.hovered_menu_id
        self.hovered_menu_button = None
        self.hovered_menu_id = ""
        if button is None or not button.isVisible() or not self.can_open_toolbar_menu_from_hover():
            return
        if not button.rect().contains(button.mapFromGlobal(QtGui.QCursor.pos())):
            return
        self.open_toolbar_menu_by_id(button, menu_id)

    def start_menu_switch_timer(self) -> None:
        self.switch_candidate_menu_id = ""
        self.switch_candidate_button = None
        self.menu_leave_pending = False

        if not self.menu_switch_timer.isActive():
            self.menu_switch_timer.start()

    def stop_menu_switch_timer(self) -> None:
        self.menu_switch_timer.stop()
        self.switch_candidate_menu_id = ""
        self.switch_candidate_button = None
        self.menu_leave_pending = False

    def cursor_over_active_menu_or_button(self) -> bool:
        cursor_position = QtGui.QCursor.pos()

        for button in self.menu_buttons:
            if str(button.property("menu_id") or "") != self.active_toolbar_menu_id:
                continue

            button_rect = QtCore.QRect(
                button.mapToGlobal(QtCore.QPoint(0, 0)),
                button.size(),
            )

            if button_rect.contains(cursor_position):
                return True

        if self.active_toolbar_menu is None:
            return False

        menus = [self.active_toolbar_menu]
        menus.extend(
            submenu
            for submenu in self.active_toolbar_menu.findChildren(QtWidgets.QMenu)
            if submenu.isVisible()
        )

        return any(
            menu.isVisible() and menu.frameGeometry().contains(cursor_position)
            for menu in menus
        )

    def check_toolbar_menu_switch(self) -> None:
        if self.active_toolbar_menu is None:
            self.stop_menu_switch_timer()
            return
        if not self.can_switch_active_toolbar_menu():
            self.switch_candidate_menu_id = ""
            self.switch_candidate_button = None
            return

        button = self.toolbar_button_under_cursor()

        if button is None:
            self.switch_candidate_menu_id = ""
            self.switch_candidate_button = None

            if self.cursor_over_active_menu_or_button():
                self.menu_leave_pending = False
                return

            if not self.menu_leave_pending:
                self.menu_leave_pending = True
                self.menu_leave_elapsed.restart()
                return

            if self.menu_leave_elapsed.elapsed() >= self.config["behavior"].get(
                "menu_close_delay_ms",
                350,
            ):
                self.menu_leave_pending = False
                self.close_active_toolbar_menu()

            return

        self.menu_leave_pending = False
        menu_id = str(button.property("menu_id") or "")
        if not menu_id or menu_id == self.active_toolbar_menu_id:
            self.switch_candidate_menu_id = ""
            self.switch_candidate_button = None
            return

        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is None or not bool(menu_config.get("enabled", True)):
            self.switch_candidate_menu_id = ""
            self.switch_candidate_button = None
            return
        if menu_config.get("type") == "top_launcher":
            self.switch_candidate_menu_id = ""
            self.switch_candidate_button = None
            return

        if self.switch_candidate_menu_id != menu_id or self.switch_candidate_button is not button:
            self.switch_candidate_menu_id = menu_id
            self.switch_candidate_button = button
            self.switch_candidate_elapsed.restart()
            return

        if self.switch_candidate_elapsed.elapsed() >= self.config["behavior"]["menu_hover_delay_ms"]:
            self.switch_candidate_menu_id = ""
            self.switch_candidate_button = None
            self.open_toolbar_menu_by_id(button, menu_id)

    def can_switch_active_toolbar_menu(self) -> bool:
        settings_open = self.manager.settings_is_visible()
        return not (
            settings_open
            or self.dialog_open
            or self.drop_dialog_open
            or self.drag_active
            or self.top_button_context_pending
            or self.top_button_context_active
        )

    def toolbar_button_under_cursor(self) -> QtWidgets.QPushButton | None:
        cursor_position = QtGui.QCursor.pos()
        for button in self.menu_buttons:
            if not button.isVisible():
                continue
            menu_config = find_menu_by_id(self.config, str(button.property("menu_id") or ""))
            if menu_config is None or menu_config.get("type") == "top_launcher":
                continue
            rect = QtCore.QRect(button.mapToGlobal(QtCore.QPoint(0, 0)), button.size())
            if rect.contains(cursor_position):
                return button
        return None

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        widget = self.childAt(event.pos())
        while widget is not None:
            if (
                widget is self.logo_label
                or widget is self.settings_button
                or widget is self.close_button
                or widget in self.menu_buttons
                or widget is self.web_search_edit
            ):
                event.ignore()
                return
            widget = widget.parentWidget()
        self.open_blank_toolbar_context(event.globalPos())
        event.accept()

    def open_blank_toolbar_context(self, position: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        self.install_menu_lifetime_hooks(menu)
        menu.addAction("Add Top-Level Menu...", self.blank_add_top_level_menu)
        menu.addAction("Add Launcher...", self.blank_add_launcher)
        menu.addSeparator()
        profiles_menu = menu.addMenu("Profiles")
        profiles_menu.aboutToShow.connect(lambda: self.manager.populate_profiles_menu(profiles_menu))
        self.manager.populate_profiles_menu(profiles_menu)
        menu.addAction("Toolbar Settings...", self.open_settings)
        menu.addAction("Help", self.open_help)
        menu.addAction("Hide Toolbar", self.manager.hide_toolbars)
        menu.addSeparator()
        menu.addAction("Exit", self.exit_toolbar)
        self.show_menu(self.configured_screen())
        self.dialog_open = True
        try:
            menu.exec(position)
        finally:
            self.dialog_open = False

    def blank_add_top_level_menu(self) -> None:
        self.dialog_open = True
        try:
            name, ok = QtWidgets.QInputDialog.getText(self, "Add Top-Level Menu", "Menu name:")
            if ok:
                self.config.setdefault("menus", []).append({"name": name.strip() or "Menu", "type": "menu", "items": []})
                self.commit_config()
        finally:
            self.dialog_open = False

    def blank_add_launcher(self) -> None:
        self.dialog_open = True
        try:
            dialog = LauncherEditorDialog(
                {"type": "launcher"},
                self,
                global_appearance=self.config["appearance"],
                top_level=True,
                profile_id=self.current_profile_id(),
                asset_context=self.asset_context(),
            )
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                next_config = copy.deepcopy(self.config)
                item = dialog.result_item()
                if insert_launcher_items(next_config, [-1], [item]):
                    self.config = next_config
                    self.commit_config()
        finally:
            self.dialog_open = False

    def open_help(self) -> None:
        open_ToolBar2_help(self)

    def clear_drag_state(self) -> None:
        self.drag_open_timer.stop()
        self.drag_open_button = None
        self.drag_open_menu = None
        self.drag_open_action = None
        QtWidgets.QToolTip.hideText()
        if self.drag_highlight_button is not None:
            self.drag_highlight_button.setDown(False)
            self.drag_highlight_button = None

    def highlight_drag_button(self, button: QtWidgets.QPushButton | None) -> None:
        if self.drag_highlight_button is button:
            return
        if self.drag_highlight_button is not None:
            self.drag_highlight_button.setDown(False)
        self.drag_highlight_button = button
        if button is not None:
            button.setDown(True)

    def schedule_drag_open_top_menu(self, button: QtWidgets.QPushButton | None) -> None:
        if button is None:
            self.drag_open_timer.stop()
            self.drag_open_button = None
            return
        menu_id = str(button.property("menu_id") or "")
        menu_config = find_menu_by_id(self.config, menu_id)
        if menu_config is None or menu_config.get("type") == "top_launcher" or not bool(menu_config.get("enabled", True)):
            self.drag_open_timer.stop()
            self.drag_open_button = None
            return
        if self.drag_open_button is button and self.drag_open_timer.isActive():
            return
        if self.active_toolbar_menu_id == menu_id:
            self.drag_open_timer.stop()
            self.drag_open_button = None
            return
        self.drag_open_button = button
        self.drag_open_menu = None
        self.drag_open_action = None
        self.drag_open_timer.start(250)

    def schedule_drag_open_submenu(self, menu: QtWidgets.QMenu, action: QtGui.QAction | None) -> None:
        if action is None or action.menu() is None:
            self.drag_open_timer.stop()
            self.drag_open_menu = None
            self.drag_open_action = None
            return
        if self.drag_open_menu is menu and self.drag_open_action is action and self.drag_open_timer.isActive():
            return
        submenu = action.menu()
        if submenu is not None and submenu.isVisible():
            self.drag_open_timer.stop()
            self.drag_open_menu = None
            self.drag_open_action = None
            return
        self.drag_open_button = None
        self.drag_open_menu = menu
        self.drag_open_action = action
        self.drag_open_timer.start(250)

    def open_drag_candidate(self) -> None:
        if self.drag_open_button is not None:
            button = self.drag_open_button
            self.drag_open_button = None
            self.open_toolbar_menu_by_id(button, str(button.property("menu_id") or ""))
            return
        if self.drag_open_menu is not None and self.drag_open_action is not None:
            menu = self.drag_open_menu
            action = self.drag_open_action
            self.drag_open_menu = None
            self.drag_open_action = None
            submenu = action.menu()
            if submenu is None:
                return
            rect = menu.actionGeometry(action)
            submenu.popup(menu.mapToGlobal(QtCore.QPoint(rect.right(), rect.top())))

    def top_level_button_at(self, position: QtCore.QPoint) -> QtWidgets.QPushButton | None:
        widget = self.childAt(position)
        while widget is not None:
            if isinstance(widget, QtWidgets.QPushButton) and widget in self.menu_buttons:
                return widget
            widget = widget.parentWidget()
        return None

    def ctrl_held(self) -> bool:
        return bool(QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.KeyboardModifier.ControlModifier)

    def is_folder_drop_launcher(self, launcher: dict | None) -> bool:
        return bool(
            launcher is not None
            and bool(launcher.get("enabled", True))
            and bool(launcher.get("accept_dropped_files", False))
            and str(launcher.get("target_type") or "Auto Detect") == "Folder"
        )

    def folder_drop_action(self, launcher: dict) -> str:
        action = str(launcher.get("folder_drop_action") or "move").strip().lower()
        return action if action in {"move", "copy", "ask"} else "move"

    def folder_drop_feedback_text(self, launcher: dict) -> str:
        name = str(launcher.get("name") or "folder")
        action = self.folder_drop_action(launcher)
        if action == "copy":
            return f"Copy to {name}"
        if action == "ask":
            return f"Move or copy to {name}"
        return f"Move to {name}"

    def drag_feedback_text(self, launcher: dict | None) -> str:
        if self.ctrl_held():
            return "Ctrl held: Add as shortcut"
        if self.is_folder_drop_launcher(launcher):
            return self.folder_drop_feedback_text(launcher or {})
        if (
            launcher is None
            or not bool(launcher.get("enabled", True))
            or not bool(launcher.get("accept_dropped_files", False))
            or not self.is_drop_run_launcher(launcher)
        ):
            return "Add as shortcut"
        return f"Run with {launcher.get('name', 'Launcher')}"

    def show_drag_feedback(self, text: str, global_position: QtCore.QPoint) -> None:
        QtWidgets.QToolTip.showText(global_position + QtCore.QPoint(16, 16), text, self)

    def is_drop_run_launcher(self, launcher: dict) -> bool:
        target_type = str(launcher.get("target_type") or "Auto Detect")
        target = str(launcher.get("target") or "")
        suffix = Path(os.path.expandvars(os.path.expanduser(target))).suffix.lower()
        if target_type in {"Program", "Command Script", "PowerShell Script", "Python Script"}:
            return True
        return suffix in {".exe", ".bat", ".cmd", ".ps1", ".py", ".pyw"}

    def choose_folder_transfer_action(self, launcher: dict) -> str | None:
        action = self.folder_drop_action(launcher)
        if action in {"move", "copy"}:
            return action
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Dropped Items")
        box.setText(f"Drop items into {launcher.get('name', 'this folder')}?")
        move_button = box.addButton("Move", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        copy_button = box.addButton("Copy", QtWidgets.QMessageBox.ButtonRole.ActionRole)
        box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(move_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is move_button:
            return "move"
        if clicked is copy_button:
            return "copy"
        return None

    def expanded_folder_target(self, launcher: dict) -> Path:
        target = os.path.expandvars(os.path.expanduser(str(launcher.get("target") or "")))
        return Path(target)

    def handle_folder_launcher_drop(self, launcher: dict, paths: list[str]) -> bool:
        if self.ctrl_held() or not self.is_folder_drop_launcher(launcher):
            return False
        action = self.choose_folder_transfer_action(launcher)
        if action is None:
            return True
        destination = self.expanded_folder_target(launcher)
        if not destination.exists() or not destination.is_dir():
            QtWidgets.QMessageBox.warning(
                self,
                "Folder Drop",
                f"Destination folder does not exist:\n{destination}",
            )
            return True
        transfers = self.prepare_folder_transfers(paths, destination)
        if transfers is None:
            return True
        if not transfers:
            return True
        self.start_folder_transfer(transfers, action, destination, str(launcher.get("name") or destination.name or "folder"))
        return True

    def prepare_folder_transfers(self, paths: list[str], destination_folder: Path) -> list[dict] | None:
        transfers: list[dict] = []
        apply_to_all = False
        remembered_choice = ""
        for path in paths:
            source = Path(os.path.expandvars(os.path.expanduser(path)))
            if not source.exists():
                QtWidgets.QMessageBox.warning(self, "Folder Drop", f"Source does not exist:\n{source}")
                continue
            destination = destination_folder / source.name
            replace = False
            if destination.exists():
                choice, apply_to_all = self.resolve_folder_drop_conflict(
                    source,
                    destination,
                    len(paths) > 1,
                    remembered_choice if apply_to_all else "",
                )
                if apply_to_all and choice:
                    remembered_choice = choice
                if choice == "cancel":
                    return None
                if choice == "skip":
                    continue
                if choice == "replace":
                    if self.same_filesystem_item(source, destination):
                        destination = self.unique_destination_path(destination)
                    else:
                        replace = True
                elif choice == "keep_both":
                    destination = self.unique_destination_path(destination)
            transfers.append(
                {
                    "source": str(source),
                    "destination": str(destination),
                    "replace": replace,
                }
            )
        return transfers

    def same_filesystem_item(self, first: Path, second: Path) -> bool:
        try:
            return first.resolve() == second.resolve()
        except OSError:
            return os.path.normcase(os.path.abspath(str(first))) == os.path.normcase(os.path.abspath(str(second)))

    def resolve_folder_drop_conflict(
        self,
        source: Path,
        destination: Path,
        allow_apply_to_all: bool,
        remembered_choice: str = "",
    ) -> tuple[str, bool]:
        if remembered_choice:
            return remembered_choice, True
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Item Already Exists")
        apply_window_icon(dialog)
        layout = QtWidgets.QVBoxLayout(dialog)
        label = QtWidgets.QLabel(
            f"An item named \"{destination.name}\" already exists in the destination folder."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        source_label = QtWidgets.QLabel(f"Source: {source}")
        source_label.setWordWrap(True)
        layout.addWidget(source_label)
        apply_check = QtWidgets.QCheckBox("Apply to all conflicts")
        apply_check.setVisible(allow_apply_to_all)
        layout.addWidget(apply_check)
        buttons = QtWidgets.QHBoxLayout()
        selected = {"choice": "cancel"}
        for text, choice in (
            ("Replace", "replace"),
            ("Keep Both", "keep_both"),
            ("Skip", "skip"),
            ("Cancel", "cancel"),
        ):
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(lambda _checked=False, value=choice: (selected.__setitem__("choice", value), dialog.accept()))
            buttons.addWidget(button)
        layout.addLayout(buttons)
        dialog.exec()
        return selected["choice"], apply_check.isChecked() if allow_apply_to_all else False

    def unique_destination_path(self, destination: Path) -> Path:
        parent = destination.parent
        stem = destination.stem if destination.suffix else destination.name
        suffix = destination.suffix
        counter = 2
        while True:
            candidate = parent / f"{stem} ({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def start_folder_transfer(
        self,
        transfers: list[dict],
        action: str,
        destination_folder: Path,
        destination_name: str,
    ) -> None:
        progress = QtWidgets.QProgressDialog(
            "Preparing transfer...",
            "",
            0,
            0,
            self,
        )
        progress.setWindowTitle("Folder Drop")
        progress.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        self.dialog_open = True
        thread = QtCore.QThread(self)
        worker = FolderTransferWorker(transfers, action)
        worker.moveToThread(thread)
        self.folder_transfer_threads.append((thread, worker))
        worker.progress.connect(lambda name: progress.setLabelText(name))
        worker.finished.connect(
            lambda completed, errors, transfer_thread=thread, transfer_worker=worker, dialog=progress, verb=action, folder=destination_folder, label=destination_name:
            self.finish_folder_transfer(transfer_thread, transfer_worker, dialog, verb, folder, label, completed, errors)
        )
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)
        thread.start()

    def finish_folder_transfer(
        self,
        thread: QtCore.QThread,
        worker: FolderTransferWorker,
        progress: QtWidgets.QProgressDialog,
        action: str,
        destination_folder: Path,
        destination_name: str,
        completed: int,
        errors: list[str],
    ) -> None:
        progress.close()
        self.dialog_open = False
        if (thread, worker) in self.folder_transfer_threads:
            self.folder_transfer_threads.remove((thread, worker))
        if completed:
            verb = "Moved" if action == "move" else "Copied"
            self.manager.show_tray_message(f"{verb} {completed} items to {destination_name}")
        if errors:
            QtWidgets.QMessageBox.warning(
                self,
                "Folder Drop",
                "Some items could not be transferred:\n\n" + "\n".join(errors[:8]),
            )

    def handle_top_level_button_drag_move(
        self,
        button: QtWidgets.QPushButton | None,
        global_position: QtCore.QPoint,
        has_local_paths: bool = True,
    ) -> None:
        if button is None:
            self.highlight_drag_button(None)
            self.schedule_drag_open_top_menu(None)
            self.show_drag_feedback("Add as shortcut", global_position)
            return
        menu_config = find_menu_by_id(self.config, str(button.property("menu_id") or ""))
        if menu_config is not None and menu_config.get("type") == "top_launcher":
            launcher = self.top_launcher_as_launcher_item(menu_config)
            folder_drop = has_local_paths and self.is_folder_drop_launcher(launcher)
            self.highlight_drag_button(button if bool(menu_config.get("enabled", True)) and (folder_drop or self.is_drop_run_launcher(launcher)) else None)
            self.schedule_drag_open_top_menu(None)
            self.show_drag_feedback(
                self.drag_feedback_text(launcher) if has_local_paths else "Add as shortcut",
                global_position,
            )
            return
        self.highlight_drag_button(None)
        self.schedule_drag_open_top_menu(button)
        self.show_drag_feedback("Add as shortcut", global_position)

    def handle_top_level_button_drop(
        self,
        button: QtWidgets.QPushButton,
        paths: list[str],
        local_paths: list[str] | None = None,
    ) -> bool:
        menu_config = find_menu_by_id(self.config, str(button.property("menu_id") or ""))
        if menu_config is not None and menu_config.get("type") == "top_launcher":
            launcher = self.top_launcher_as_launcher_item(menu_config)
            if local_paths and self.handle_folder_launcher_drop(launcher, local_paths):
                return True
            if (
                not self.ctrl_held()
                and bool(menu_config.get("enabled", True))
                and bool(launcher.get("accept_dropped_files", False))
                and self.is_drop_run_launcher(launcher)
            ):
                launch_item_with_args(launcher, paths, self)
                return True
            return self.show_dropped_items_dialog(paths, None)
        preselected = button.property("menu_path")
        return self.show_dropped_items_dialog(paths, preselected if isinstance(preselected, list) else None)

    def handle_menu_drag_moved(
        self,
        menu: QtWidgets.QMenu,
        position: QtCore.QPoint,
        global_position: QtCore.QPoint,
        mime_data: QtCore.QMimeData,
    ) -> None:
        if not extract_targets_from_mime_data(mime_data):
            return
        self.drag_active = True
        self.highlight_drag_button(None)
        action = menu.actionAt(position)
        menu.setActiveAction(action)
        launcher = self.launcher_from_action(action)
        has_local_paths = bool(extract_local_paths_from_mime_data(mime_data))
        self.show_drag_feedback(
            self.drag_feedback_text(launcher) if has_local_paths or not self.is_folder_drop_launcher(launcher) else "Add as shortcut",
            global_position,
        )
        data = action.data() if action is not None else None
        item_type = str(data.get("item_type") or "") if isinstance(data, dict) else ""
        if item_type in {"submenu", "folder_menu"}:
            self.schedule_drag_open_submenu(menu, action)
        else:
            self.schedule_drag_open_submenu(menu, None)

    def handle_menu_drag_dropped(
        self,
        menu: QtWidgets.QMenu,
        position: QtCore.QPoint,
        global_position: QtCore.QPoint,
        mime_data: QtCore.QMimeData,
    ) -> None:
        paths = extract_targets_from_mime_data(mime_data)
        self.drag_active = False
        self.clear_drag_state()
        if not paths:
            return
        action = menu.actionAt(position)
        launcher = self.launcher_from_action(action)
        local_paths = extract_local_paths_from_mime_data(mime_data)
        if launcher is not None and local_paths and self.handle_folder_launcher_drop(launcher, local_paths):
            self.close_active_toolbar_menu()
            return
        if (
            launcher is not None
            and not self.ctrl_held()
            and bool(launcher.get("accept_dropped_files", False))
            and self.is_drop_run_launcher(launcher)
        ):
            launch_item_with_args(launcher, paths, self)
            self.close_active_toolbar_menu()
            return
        if self.action_represents_launcher(action):
            destination_path = self.destination_path_from_menu_drop(menu, None)
            self.show_dropped_items_dialog(paths, destination_path)
            return
        destination_path = self.destination_path_from_menu_drop(menu, action)
        self.show_dropped_items_dialog(paths, destination_path)

    def handle_menu_drag_left(self, menu: QtWidgets.QMenu) -> None:
        menu.setActiveAction(None)

    def launcher_from_action(self, action: QtGui.QAction | None) -> dict | None:
        if action is None:
            return None
        data = action.data()
        if not isinstance(data, dict) or data.get("item_type") != "launcher":
            return None
        item = find_any_item_by_id(self.config, str(data.get("item_id") or ""))
        if item is None or item.get("type") != "launcher" or not bool(item.get("enabled", True)):
            return None
        return item

    def action_represents_launcher(self, action: QtGui.QAction | None) -> bool:
        if action is None:
            return False
        data = action.data()
        return isinstance(data, dict) and data.get("item_type") == "launcher"

    def destination_path_from_menu_drop(self, menu: QtWidgets.QMenu, action: QtGui.QAction | None) -> list[int] | None:
        if action is not None:
            data = action.data()
            if isinstance(data, dict) and data.get("item_type") == "submenu":
                path = self.config_path_for_id(str(data.get("item_id") or ""))
                if path is not None:
                    return path
        container_id = str(menu.property("container_id") or "")
        return self.config_path_for_id(container_id)

    def config_path_for_id(self, item_id: str) -> list[int] | None:
        if not item_id:
            return None
        for index, menu in enumerate(self.config.get("menus", [])):
            if menu.get("id") == item_id:
                return [index]
            path = self.config_path_for_id_in_items(menu.get("items", []), item_id, [index])
            if path is not None:
                return path
        return None

    def config_path_for_id_in_items(self, items: list[dict], item_id: str, parent_path: list[int]) -> list[int] | None:
        for index, item in enumerate(items):
            path = [*parent_path, index]
            if item.get("id") == item_id:
                return path
            if item.get("type") == "submenu":
                found = self.config_path_for_id_in_items(item.get("items", []), item_id, path)
                if found is not None:
                    return found
        return None

    def show_dropped_items_dialog(self, paths: list[str], preselected: list[int] | None) -> bool:
        destinations = list_menu_destinations(self.config)
        self.drop_dialog_open = True
        try:
            dialog = DroppedItemsDialog(paths, destinations, preselected, self)
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                self.add_dropped_items(dialog.result_items())
                return True
        finally:
            self.drop_dialog_open = False
        return False

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if extract_targets_from_mime_data(event.mimeData()):
            self.drag_active = True
            self.show_menu(self.configured_screen())
            self.accept_copy_drop(event)
            return
        event.ignore()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if extract_targets_from_mime_data(event.mimeData()):
            self.drag_active = True

            local_position = event.position().toPoint()
            global_position = self.mapToGlobal(local_position)

            button = self.top_level_button_at(local_position)
            self.handle_top_level_button_drag_move(
                button,
                global_position,
                bool(extract_local_paths_from_mime_data(event.mimeData())),
            )
            self.accept_copy_drop(event)
            return

        event.ignore()

    def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent) -> None:
        self.drag_active = False
        self.clear_drag_state()
        event.accept()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        self.drag_active = False
        self.clear_drag_state()
        paths = extract_targets_from_mime_data(event.mimeData())
        if not paths:
            event.ignore()
            return

        button = self.top_level_button_at(event.position().toPoint())
        local_paths = extract_local_paths_from_mime_data(event.mimeData())
        if button is not None and self.handle_top_level_button_drop(button, paths, local_paths):
            self.accept_copy_drop(event)
            return

        preselected = self.drop_menu_path(event.position().toPoint())
        if self.show_dropped_items_dialog(paths, preselected):
            self.accept_copy_drop(event)
            return
        event.ignore()

    def drop_menu_path(self, position: QtCore.QPoint) -> list[int] | None:
        widget = self.childAt(position)
        while widget is not None:
            path = widget.property("menu_path")
            if isinstance(path, list):
                return path
            widget = widget.parentWidget()
        return None

    def add_dropped_items(self, results: list[dict]) -> None:
        next_config = copy.deepcopy(self.config)
        for result in results:
            item = copy.deepcopy(result.get("item") or {})
            add_mode = str(result.get("add_mode") or "")
            if add_mode in {"top_level", "top_level_folder_menu"}:
                if item.get("type") == "launcher":
                    insert_launcher_items(next_config, [-1], [item])
                else:
                    next_config.setdefault("menus", []).append(item)
                continue
            destination_path = copy.deepcopy(result.get("destination_path"))
            destination_id = str(result.get("destination_id") or "")
            if not isinstance(destination_path, list) or not valid_menu_destination_at_path(next_config, destination_path, destination_id):
                QtWidgets.QMessageBox.warning(self, "Invalid Destination", "Choose a menu or submenu destination.")
                return
            if not insert_launcher_items(next_config, destination_path, [item]):
                QtWidgets.QMessageBox.warning(self, "Invalid Destination", "Choose a menu or submenu destination.")
                return
        self.config = next_config
        self.commit_config()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        event.accept()
