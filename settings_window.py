from __future__ import annotations

import copy
import logging
import uuid
from datetime import date
from pathlib import Path
from typing import Callable

from PyQt6 import QtCore, QtGui, QtWidgets

from app_icon import apply_window_icon
from config_manager import (
    DEFAULT_CONFIG,
    commit_user_profile_records,
    copy_monitor_profile,
    default_config,
    delete_staging_session,
    effective_config_for_monitor,
    ensure_monitor_profile,
    profile_json_from_runtime,
    profile_for_monitor,
    list_user_profile_records,
    reset_monitor_profile,
    root_config_from_runtime,
    runtime_config_from_profile_json,
    update_monitor_profile,
    validate_config,
)
from logo_editor_dialog import LogoEditorWidget
from menu_editor import MenuEditorWidget
from icon_utilities import AssetContext
from help_utils import open_ToolBar2_help
from item_transfer_dialog import ItemTransferDialog
from monitor_utils import connected_monitor_ids, index_for_monitor_id, monitor_display_name, monitor_id, monitor_metadata
from profile_package_manager import (
    export_profile_package,
    import_profile_package_plan_to_staging,
    inspect_profile_package_detailed,
)
from profile_import_dialog import ProfileImportDialog
from saved_profiles_editor import SavedProfilesEditorWidget
from startup_manager import startup_supported
from toolbar_item_transfer import (
    ToolbarRef,
    TransferDestination,
    clone_item_for_destination,
    destination_containers,
    insert_item,
    item_at_path as transfer_item_at_path,
    remove_item_at_path,
    sibling_positions,
)


logger = logging.getLogger(__name__)

COLOR_FIELDS = {
    "toolbar_background": "Toolbar background",
    "button_background": "Button background",
    "button_hover": "Button hover",
    "button_text": "Button text",
    "menu_background": "Menu background",
    "menu_text": "Menu text",
    "border_color": "Border color",
}

LAUNCH_TYPES = [
    "Auto Detect",
    "Program",
    "Python Script",
    "File",
    "Folder",
    "Website",
]

MONITOR_MODE_CHOICES = [
    ("One monitor", "single"),
    ("Selected monitors - same toolbar", "selected_shared"),
    ("All connected monitors - same toolbar", "all_shared"),
    ("Selected monitors - unique toolbar on each", "per_monitor"),
]


class CollapsibleSection(QtWidgets.QWidget):
    def __init__(
        self,
        title: str,
        expanded: bool = True,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.header = QtWidgets.QToolButton()
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.clicked.connect(self.set_expanded)

        self.content = QtWidgets.QWidget()
        self._content_layout = QtWidgets.QVBoxLayout(self.content)
        self._content_layout.setContentsMargins(18, 4, 0, 10)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.content)

        self.set_expanded(expanded)

    def content_layout(self) -> QtWidgets.QVBoxLayout:
        return self._content_layout

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)
        self.header.setArrowType(
            QtCore.Qt.ArrowType.DownArrow
            if expanded
            else QtCore.Qt.ArrowType.RightArrow
        )
        self.content.setVisible(expanded)


class MonitorIdentificationOverlay(QtWidgets.QWidget):
    def __init__(
        self,
        screen: QtGui.QScreen,
        monitor_number: int,
        display_name: str,
        resolution: str,
        is_primary: bool,
        stable_monitor_id: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.target_screen = screen
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        frame = QtWidgets.QFrame()
        frame.setObjectName("monitorIdentificationFrame")
        frame.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        frame.setStyleSheet(
            """
            QFrame#monitorIdentificationFrame {
                background-color: rgba(0, 0, 0, 210);
                border: 2px solid rgba(255, 255, 255, 225);
                border-radius: 14px;
            }
            QLabel {
                color: white;
                background: transparent;
            }
            QLabel#monitorNumber {
                font-weight: 800;
            }
            QLabel#monitorDetail {
                color: rgba(255, 255, 255, 210);
            }
            QLabel#monitorId {
                color: rgba(255, 255, 255, 150);
            }
            """
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(frame)

        content_layout = QtWidgets.QVBoxLayout(frame)
        content_layout.setContentsMargins(28, 22, 28, 22)
        content_layout.setSpacing(6)

        heading = QtWidgets.QLabel(f"MONITOR {monitor_number}")
        heading.setObjectName("monitorNumber")
        heading.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        heading_font = heading.font()
        heading_font.setPointSize(30)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        content_layout.addWidget(heading)

        name_label = QtWidgets.QLabel(display_name)
        name_label.setObjectName("monitorDetail")
        name_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        detail_font = name_label.font()
        detail_font.setPointSize(15)
        detail_font.setBold(True)
        name_label.setFont(detail_font)
        content_layout.addWidget(name_label)

        resolution_label = QtWidgets.QLabel(resolution)
        resolution_label.setObjectName("monitorDetail")
        resolution_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        resolution_label.setFont(detail_font)
        content_layout.addWidget(resolution_label)

        if is_primary:
            primary_label = QtWidgets.QLabel("Primary")
            primary_label.setObjectName("monitorDetail")
            primary_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            primary_label.setFont(detail_font)
            content_layout.addWidget(primary_label)

        if stable_monitor_id:
            id_label = QtWidgets.QLabel(self.elide_monitor_id(stable_monitor_id))
            id_label.setObjectName("monitorId")
            id_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            id_label.setWordWrap(True)
            id_font = id_label.font()
            id_font.setPointSize(9)
            id_label.setFont(id_font)
            content_layout.addWidget(id_label)

        self.position_on_screen()

    def elide_monitor_id(self, stable_monitor_id: str) -> str:
        if len(stable_monitor_id) <= 72:
            return stable_monitor_id
        return f"{stable_monitor_id[:34]}...{stable_monitor_id[-34:]}"

    def position_on_screen(self) -> None:
        geometry = self.target_screen.availableGeometry()
        target_width = max(300, min(520, int(geometry.width() * 0.36)))
        self.setFixedWidth(target_width)
        self.adjustSize()
        size = self.sizeHint()
        self.resize(target_width, size.height())
        x = geometry.x() + (geometry.width() - self.width()) // 2
        y = geometry.y() + (geometry.height() - self.height()) // 2
        self.move(x, y)


class SettingsWindow(QtWidgets.QDialog):
    def __init__(
        self,
        config: dict,
        save_callback: Callable[[dict], dict | None],
        preview_callback: Callable[[dict, str, str], None],
        rollback_preview_callback: Callable[[], None],
        preview_working_config_callback: Callable[[dict], None] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.save_callback = save_callback
        self.preview_callback = preview_callback
        self.rollback_preview_callback = rollback_preview_callback
        self.preview_working_config_callback = preview_working_config_callback
        self.config = validate_config(copy.deepcopy(config), self.screen_count(), self.connected_monitor_ids())
        self.selected_item: QtWidgets.QTreeWidgetItem | None = None
        self.loading_selection = False
        self.loading_monitors = False
        self.loading_profile_selector = False
        self.loading_appearance = False
        self.loading_behavior = False
        self.preview_active = False
        self.preview_rolled_back = False
        self.active_profile_monitor_id = ""
        self.staging_session_id = uuid.uuid4().hex
        self.saved_baseline_config = copy.deepcopy(self.config)
        self.saved_baseline_profiles: list[dict] = []
        self.pending_active_profile_replacement: dict | None = None
        self.identification_overlays: list[MonitorIdentificationOverlay] = []
        self.menu_editor: MenuEditorWidget | None = None
        self.working_preview_timer = QtCore.QTimer(self)
        self.working_preview_timer.setSingleShot(True)
        self.working_preview_timer.setInterval(75)
        self.working_preview_timer.timeout.connect(self.send_working_preview)
        self.appearance_preview_timer = QtCore.QTimer(self)
        self.appearance_preview_timer.setSingleShot(True)
        self.appearance_preview_timer.setInterval(75)
        self.appearance_preview_timer.timeout.connect(self.send_working_preview)

        self.update_window_title()
        apply_window_icon(self)
        self.resize(760, 560)

        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self.settings_shell = QtWidgets.QFrame()
        self.settings_shell.setObjectName("settingsShell")
        self.settings_shell.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_StyledBackground,
            True,
        )
        self.settings_shell.setAutoFillBackground(True)
        outer_layout.addWidget(self.settings_shell)

        self.root_layout = QtWidgets.QVBoxLayout(self.settings_shell)
        self.root_layout.setContentsMargins(10, 10, 10, 10)
        self.root_layout.setSpacing(8)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self.tabs.tabBar().setObjectName("settingsTabBar")
        self.tabs.tabBar().setAttribute(
            QtCore.Qt.WidgetAttribute.WA_StyledBackground,
            True,
        )
        self.tabs.currentChanged.connect(self.on_main_tab_changed)
        self.root_layout.addWidget(self.tabs)

        self.build_appearance_tab()
        self.build_behavior_tab()
        self.build_profile_selector()
        self.build_saved_profiles_tab()
        self.build_logo_tab()
        self.build_menus_tab()

        self.settings_action_bar = QtWidgets.QWidget()
        self.settings_action_bar.setObjectName("settingsActionBar")
        self.settings_action_bar.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_StyledBackground,
            True,
        )
        self.settings_action_bar_layout = QtWidgets.QHBoxLayout(self.settings_action_bar)
        self.settings_action_bar_layout.setContentsMargins(8, 6, 8, 6)
        if hasattr(self, "logo_add_item_button"):
            self.settings_action_bar_layout.addWidget(self.logo_add_item_button)
        self.help_button = QtWidgets.QPushButton("Help")
        self.save_button = QtWidgets.QPushButton("Save")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.help_button.clicked.connect(self.open_help)
        self.save_button.clicked.connect(self.save)
        self.cancel_button.clicked.connect(self.reject)
        self.settings_action_bar_layout.addStretch()
        self.settings_action_bar_layout.addWidget(self.help_button)
        self.settings_action_bar_layout.addWidget(self.save_button)
        self.settings_action_bar_layout.addWidget(self.cancel_button)
        self.root_layout.addWidget(self.settings_action_bar)

        self.apply_neutral_settings_panels()

        self.refresh_from_config(self.config)
        if hasattr(self, "saved_profiles_editor"):
            self.saved_baseline_profiles = self.saved_profiles_editor.current_profiles()

    def build_profile_selector(self) -> None:
        self.profile_group = QtWidgets.QGroupBox("Editing toolbar for")
        self.profile_group.setObjectName("profileGroup")
        self.profile_group.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_StyledBackground,
            True,
        )
        layout = QtWidgets.QHBoxLayout(self.profile_group)
        self.profile_combo = QtWidgets.QComboBox()
        self.profile_combo.currentIndexChanged.connect(self.on_profile_selection_changed)
        self.copy_profile_button = QtWidgets.QPushButton("Copy Toolbar From...")
        self.reset_profile_button = QtWidgets.QPushButton("Reset This Toolbar")
        self.copy_profile_button.clicked.connect(self.copy_profile_from)
        self.reset_profile_button.clicked.connect(self.reset_current_profile)
        layout.addWidget(self.profile_combo, 1)
        layout.addWidget(self.copy_profile_button)
        layout.addWidget(self.reset_profile_button)
        self.tabs.currentChanged.connect(lambda _index: self.update_profile_selector_visibility())
        self.root_layout.insertWidget(1, self.profile_group)

    def open_help(self) -> None:
        open_ToolBar2_help(self)

    def default_settings_panel_color(self) -> str:
        color = QtWidgets.QApplication.palette().color(
            QtGui.QPalette.ColorRole.Window
        )
        return color.name() if color.isValid() else "#202020"

    def apply_neutral_settings_panels(self) -> None:
        panel_color = self.default_settings_panel_color()

        self.profile_group.setStyleSheet(
            f"""
            QGroupBox#profileGroup {{
                background-color: {panel_color};
                border: 1px solid palette(mid);
                border-radius: 5px;
                margin-top: 8px;
                padding-top: 8px;
            }}
            QGroupBox#profileGroup::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }}
            """
        )

        self.settings_action_bar.setStyleSheet(
            f"""
            QWidget#settingsActionBar {{
                background-color: {panel_color};
                border-radius: 5px;
            }}
            """
        )

        self.tabs.tabBar().setStyleSheet(
            f"""
            QTabBar#settingsTabBar {{
                background-color: {panel_color};
            }}

            QTabBar#settingsTabBar::tab {{
                background-color: palette(button);
                color: palette(button-text);
                border: 1px solid palette(mid);
                padding: 6px 12px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}

            QTabBar#settingsTabBar::tab:selected {{
                background-color: palette(window);
            }}

            QTabBar#settingsTabBar::tab:hover {{
                background-color: palette(midlight);
            }}
            """
        )

    def active_toolbar_background(self) -> str:
        fallback = str(DEFAULT_CONFIG["appearance"]["toolbar_background"])
        value = ""
        if hasattr(self, "color_buttons"):
            button = self.color_buttons.get("toolbar_background")
            if button is not None:
                value = str(button.property("color_value") or "")
        if not value:
            toolbar_config = self.active_toolbar_config()
            appearance = toolbar_config.get("appearance", {})
            if isinstance(appearance, dict):
                value = str(appearance.get("toolbar_background", fallback) or fallback)
        color = QtGui.QColor(value)
        if not color.isValid():
            color = QtGui.QColor(fallback)
        return color.name()

    def active_toolbar_opacity(self) -> float:
        if hasattr(self, "opacity_spin"):
            value = self.opacity_spin.value()
        else:
            appearance = self.active_toolbar_config().get("appearance", {})
            value = appearance.get(
                "opacity",
                DEFAULT_CONFIG["appearance"].get("opacity", 1.0),
            )

        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 1.0

        return max(0.0, min(1.0, value))

    def blended_settings_background(self) -> str:
        foreground = QtGui.QColor(self.active_toolbar_background())
        background = QtGui.QColor(
            DEFAULT_CONFIG["appearance"].get(
                "toolbar_background",
                "#202020",
            )
        )

        if not foreground.isValid():
            foreground = QtGui.QColor("#202020")
        if not background.isValid():
            background = QtGui.QColor("#202020")

        amount = min(self.active_toolbar_opacity(), 0.65)

        red = round(
            foreground.red() * amount
            + background.red() * (1.0 - amount)
        )
        green = round(
            foreground.green() * amount
            + background.green() * (1.0 - amount)
        )
        blue = round(
            foreground.blue() * amount
            + background.blue() * (1.0 - amount)
        )

        return QtGui.QColor(red, green, blue).name()

    def apply_active_toolbar_background(self) -> None:
        color_value = self.blended_settings_background()
        self.settings_shell.setStyleSheet(
            f"""
            QFrame#settingsShell {{
                background-color: {color_value};
            }}
            """
        )
        style = self.settings_shell.style()
        style.unpolish(self.settings_shell)
        style.polish(self.settings_shell)
        self.settings_shell.setAutoFillBackground(True)
        self.settings_shell.update()
        self.apply_neutral_settings_panels()

    def screen_count(self) -> int:
        return len(QtGui.QGuiApplication.screens())

    def connected_monitor_ids(self) -> list[str]:
        return connected_monitor_ids()

    def refresh_from_config(self, config: dict) -> None:
        self.config = validate_config(copy.deepcopy(config), self.screen_count(), self.connected_monitor_ids())
        self.update_window_title()
        self.ensure_active_profile_selection()
        self.populate_behavior()
        self.populate_profile_selector()
        self.populate_appearance()
        if self.menu_editor is not None:
            self.menu_editor.refresh_config(self.active_toolbar_config(), self.active_profile_id(), self.asset_context())
        self.populate_logo_tab()
        if (
            hasattr(self, "saved_profiles_editor")
            and not (
                self.isVisible()
                and self.saved_profiles_editor.has_unsaved_changes()
            )
        ):
            self.saved_profiles_editor.refresh_config(self.config)
        self.update_profile_selector_visibility()
        if not self.isVisible():
            self.saved_baseline_config = copy.deepcopy(self.config)
            if hasattr(self, "saved_profiles_editor"):
                self.saved_baseline_profiles = self.saved_profiles_editor.current_profiles()

    def update_window_title(self) -> None:
        name = str(getattr(self, "config", {}).get("user_profile_name") or "Default").strip() or "Default"
        self.setWindowTitle(f"Toolbar Settings - {name}")

    def build_appearance_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)

        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_content = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        colors_section = CollapsibleSection("Colors and Transparency", expanded=True)
        colors_form = QtWidgets.QFormLayout()
        self.color_buttons: dict[str, QtWidgets.QPushButton] = {}
        for key, label in COLOR_FIELDS.items():
            button = QtWidgets.QPushButton()
            button.clicked.connect(lambda checked=False, field=key: self.pick_color(field))
            self.color_buttons[key] = button
            colors_form.addRow(label, button)

        self.opacity_spin = QtWidgets.QDoubleSpinBox()
        self.opacity_spin.setRange(0.00, 1.00)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setDecimals(2)
        self.opacity_spin.setToolTip(
            "Controls only the toolbar background. Buttons, text, logo, gear, and menus remain fully opaque."
        )
        self.opacity_spin.valueChanged.connect(
            lambda _value: self.apply_active_toolbar_background()
        )
        self.opacity_spin.valueChanged.connect(self.schedule_appearance_preview)
        colors_form.addRow("Toolbar background opacity", self.opacity_spin)
        colors_section.content_layout().addLayout(colors_form)

        size_section = CollapsibleSection("Size and Spacing", expanded=False)
        size_form = QtWidgets.QFormLayout()
        self.toolbar_height_spin = self.int_spin(16, 240)
        self.toolbar_height_spin.setToolTip(
            "Supports compact toolbars down to 16 pixels. Buttons, icons, text, logo, and toolbar controls scale to fit."
        )
        self.button_height_spin = self.int_spin(12, 96)
        self.button_height_spin.setToolTip(
            "The requested button height. The displayed button is automatically reduced when the toolbar is too small."
        )
        self.corner_radius_spin = self.int_spin(0, 24)
        self.horizontal_padding_spin = self.int_spin(0, 100)
        self.horizontal_padding_spin.setToolTip(
            "Controls the empty space at the far left and right edges of the toolbar."
        )
        self.vertical_padding_spin = self.int_spin(0, 60)
        self.vertical_padding_spin.setToolTip(
            "Controls equal inside spacing at the top and bottom of the toolbar. "
            "This padding may be reduced automatically when the toolbar is too short."
        )
        self.menu_button_spacing_spin = self.int_spin(0, 50)
        self.menu_button_spacing_spin.setToolTip(
            "Controls the space between top-level toolbar menu buttons."
        )
        self.menu_alignment_combo = QtWidgets.QComboBox()
        self.menu_alignment_combo.addItem("Left", "left")
        self.menu_alignment_combo.addItem("Center", "center")
        self.menu_alignment_combo.addItem("Right", "right")
        self.menu_alignment_combo.setToolTip("Controls where the top-level toolbar buttons appear.")
        self.auto_toolbar_width_check = QtWidgets.QCheckBox("Auto toolbar width")
        self.auto_toolbar_width_check.setToolTip("Use the current automatic full-monitor toolbar width.")
        self.toolbar_width_spin = self.int_spin(300, 3000)
        self.toolbar_width_spin.setToolTip("Sets the toolbar width when automatic width is turned off.")
        self.horizontal_alignment_combo = QtWidgets.QComboBox()
        self.horizontal_alignment_combo.addItem("Left", "left")
        self.horizontal_alignment_combo.addItem("Center", "center")
        self.horizontal_alignment_combo.addItem("Right", "right")
        self.horizontal_alignment_combo.setToolTip("Positions a custom-width toolbar on the selected monitor.")
        self.horizontal_offset_spin = self.int_spin(-3000, 3000)
        self.horizontal_offset_spin.setToolTip("Fine-tunes the toolbar's horizontal position in pixels.")
        for spin in (
            self.toolbar_height_spin,
            self.button_height_spin,
            self.corner_radius_spin,
            self.horizontal_padding_spin,
            self.vertical_padding_spin,
            self.menu_button_spacing_spin,
            self.toolbar_width_spin,
            self.horizontal_offset_spin,
        ):
            spin.valueChanged.connect(self.schedule_appearance_preview)
        self.auto_toolbar_width_check.toggled.connect(self.update_toolbar_width_controls)
        self.auto_toolbar_width_check.toggled.connect(self.schedule_appearance_preview)
        self.menu_alignment_combo.currentIndexChanged.connect(self.schedule_appearance_preview)
        self.horizontal_alignment_combo.currentIndexChanged.connect(self.schedule_appearance_preview)
        size_form.addRow("Toolbar height", self.toolbar_height_spin)
        size_form.addRow("", self.auto_toolbar_width_check)
        size_form.addRow("Toolbar width", self.toolbar_width_spin)
        size_form.addRow("Horizontal alignment", self.horizontal_alignment_combo)
        size_form.addRow("Horizontal offset", self.horizontal_offset_spin)
        size_form.addRow("Button height", self.button_height_spin)
        size_form.addRow("Corner radius", self.corner_radius_spin)
        size_form.addRow("Left/right edge padding", self.horizontal_padding_spin)
        size_form.addRow("Top/bottom edge padding", self.vertical_padding_spin)
        size_form.addRow("Menu button spacing", self.menu_button_spacing_spin)
        size_form.addRow("Top menu position", self.menu_alignment_combo)
        size_section.content_layout().addLayout(size_form)

        controls_section = CollapsibleSection("Toolbar Controls", expanded=False)
        controls_form = QtWidgets.QFormLayout()
        self.show_settings_button_check = QtWidgets.QCheckBox("Show Settings gear")
        self.show_settings_button_check.setToolTip(
            "Show the Settings gear on this toolbar. Settings remain available from the toolbar right-click menu and system tray."
        )
        self.show_exit_button_check = QtWidgets.QCheckBox("Show Exit button")
        self.show_exit_button_check.setToolTip(
            "Show the red Exit button on this toolbar. Exit remains available from the toolbar right-click menu and system tray."
        )
        self.show_web_search_bar_check = QtWidgets.QCheckBox("Show Web Search bar")
        self.web_search_width_spin = self.int_spin(100, 500)
        self.web_search_placeholder_edit = QtWidgets.QLineEdit()
        self.web_search_placeholder_edit.setPlaceholderText("Search the web...")
        self.web_search_engine_combo = QtWidgets.QComboBox()
        for label in ("Google", "Bing", "DuckDuckGo", "Yahoo", "Custom"):
            self.web_search_engine_combo.addItem(label, label)
        self.web_search_custom_url_edit = QtWidgets.QLineEdit()
        self.web_search_custom_url_edit.setPlaceholderText("https://example.com/search?q={query}")
        self.web_search_custom_url_edit.setToolTip(
            "Used only when Search engine is Custom. Include {query} where the encoded search text should go."
        )
        self.show_settings_button_check.toggled.connect(self.schedule_appearance_preview)
        self.show_exit_button_check.toggled.connect(self.schedule_appearance_preview)
        self.show_web_search_bar_check.toggled.connect(self.schedule_appearance_preview)
        self.show_web_search_bar_check.toggled.connect(self.sync_web_search_controls_to_menu_editor)
        self.web_search_width_spin.valueChanged.connect(self.schedule_appearance_preview)
        self.web_search_width_spin.valueChanged.connect(self.sync_web_search_controls_to_menu_editor)
        self.web_search_placeholder_edit.textChanged.connect(self.schedule_appearance_preview)
        self.web_search_placeholder_edit.textChanged.connect(self.sync_web_search_controls_to_menu_editor)
        self.web_search_engine_combo.currentIndexChanged.connect(self.update_web_search_custom_url_state)
        self.web_search_engine_combo.currentIndexChanged.connect(self.schedule_appearance_preview)
        self.web_search_engine_combo.currentIndexChanged.connect(self.sync_web_search_controls_to_menu_editor)
        self.web_search_custom_url_edit.textChanged.connect(self.schedule_appearance_preview)
        self.web_search_custom_url_edit.textChanged.connect(self.sync_web_search_controls_to_menu_editor)
        controls_form.addRow("", self.show_settings_button_check)
        controls_form.addRow("", self.show_exit_button_check)
        controls_form.addRow("", self.show_web_search_bar_check)
        controls_form.addRow("Search bar width", self.web_search_width_spin)
        controls_form.addRow("Placeholder text", self.web_search_placeholder_edit)
        controls_form.addRow("Search engine", self.web_search_engine_combo)
        controls_form.addRow("Custom search URL", self.web_search_custom_url_edit)
        controls_section.content_layout().addLayout(controls_form)

        self.appearance_sections = [
            colors_section,
            size_section,
            controls_section,
        ]
        for section in self.appearance_sections:
            section.header.toggled.connect(
                lambda expanded, current=section: self.on_appearance_section_toggled(current, expanded)
            )

        scroll_layout.addWidget(colors_section)
        scroll_layout.addWidget(size_section)
        scroll_layout.addWidget(controls_section)
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)
        self.reset_appearance_button = QtWidgets.QPushButton("Reset Appearance to Defaults")
        self.reset_appearance_button.clicked.connect(self.reset_appearance)
        layout.addWidget(self.reset_appearance_button, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        self.tabs.addTab(tab, "Appearance")

    def update_toolbar_width_controls(self, *_args: object) -> None:
        if not hasattr(self, "toolbar_width_spin"):
            return
        custom_width = not self.auto_toolbar_width_check.isChecked()
        self.toolbar_width_spin.setEnabled(custom_width)

    def sync_web_search_controls_to_menu_editor(self, *_args: object) -> None:
        if self.loading_appearance or not hasattr(self, "menu_editor"):
            return
        appearance = self.menu_editor.config.setdefault("appearance", {})
        was_enabled = bool(appearance.get("show_web_search_bar", False))
        appearance["show_web_search_bar"] = self.show_web_search_bar_check.isChecked()
        appearance["web_search_width"] = self.web_search_width_spin.value()
        appearance["web_search_placeholder"] = self.web_search_placeholder_edit.text().strip() or "Search the web..."
        appearance["web_search_engine"] = str(self.web_search_engine_combo.currentData() or "Google")
        appearance["web_search_custom_url"] = self.web_search_custom_url_edit.text().strip()
        if was_enabled != appearance["show_web_search_bar"]:
            self.menu_editor.populate_tree()

    def update_web_search_custom_url_state(self, *_args: object) -> None:
        custom_selected = str(self.web_search_engine_combo.currentData() or "Google") == "Custom"
        self.web_search_custom_url_edit.setEnabled(custom_selected)

    def build_behavior_tab(self) -> None:
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)

        self.monitor_mode_combo = QtWidgets.QComboBox()
        for label, value in MONITOR_MODE_CHOICES:
            self.monitor_mode_combo.addItem(label, value)
        self.monitor_mode_combo.currentIndexChanged.connect(self.on_monitor_mode_changed)
        self.monitor_list = QtWidgets.QListWidget()
        self.monitor_list.setMinimumHeight(110)
        self.monitor_list.itemChanged.connect(self.on_monitor_item_changed)
        monitor_buttons = QtWidgets.QHBoxLayout()
        self.identify_monitors_button = QtWidgets.QPushButton("Identify Monitors")
        self.assign_imported_toolbar_button = QtWidgets.QPushButton("Assign Imported Toolbar...")
        self.select_all_monitors_button = QtWidgets.QPushButton("Select All")
        self.select_none_monitors_button = QtWidgets.QPushButton("Select None")
        self.identify_monitors_button.clicked.connect(self.identify_monitors)
        self.assign_imported_toolbar_button.clicked.connect(self.assign_imported_toolbar)
        self.select_all_monitors_button.clicked.connect(self.select_all_monitors)
        self.select_none_monitors_button.clicked.connect(self.select_no_monitors)
        monitor_buttons.addWidget(self.identify_monitors_button)
        monitor_buttons.addWidget(self.assign_imported_toolbar_button)
        monitor_buttons.addWidget(self.select_all_monitors_button)
        monitor_buttons.addWidget(self.select_none_monitors_button)
        monitor_buttons.addStretch()
        self.trigger_height_spin = self.int_spin(1, 30)
        self.hide_delay_spin = self.int_spin(100, 5000)
        self.hide_delay_spin.setSingleStep(50)
        self.animation_duration_spin = self.int_spin(0, 2000)
        self.animation_duration_spin.setSingleStep(50)
        self.open_menus_on_hover_check = QtWidgets.QCheckBox("Open toolbar menus on hover")
        self.hover_delay_spin = self.int_spin(0, 1000)
        self.hover_delay_spin.setSingleStep(50)
        self.confirm_before_exit_check = QtWidgets.QCheckBox("Confirm before exiting")
        self.start_with_windows_check = QtWidgets.QCheckBox("Start ToolBar2 with Windows")
        for widget in (
            self.trigger_height_spin,
            self.hide_delay_spin,
            self.animation_duration_spin,
            self.hover_delay_spin,
        ):
            widget.valueChanged.connect(self.schedule_working_preview)
        self.open_menus_on_hover_check.toggled.connect(self.schedule_working_preview)
        self.confirm_before_exit_check.toggled.connect(self.schedule_working_preview)
        self.start_with_windows_check.toggled.connect(self.schedule_working_preview)
        if startup_supported():
            self.start_with_windows_check.setEnabled(True)
            self.start_with_windows_check.setToolTip("Start ToolBar2 automatically when you sign in to Windows.")
        else:
            self.start_with_windows_check.setEnabled(False)
            self.start_with_windows_check.setToolTip("Available when running the compiled ToolBar2.exe.")

        form.addRow("Toolbar mode", self.monitor_mode_combo)
        form.addRow("Monitors", self.monitor_list)
        form.addRow("", monitor_buttons)
        form.addRow("Trigger height", self.trigger_height_spin)
        form.addRow("Hide delay (ms)", self.hide_delay_spin)
        form.addRow("Animation duration (ms)", self.animation_duration_spin)
        form.addRow("", self.open_menus_on_hover_check)
        form.addRow("Hover delay (ms)", self.hover_delay_spin)
        form.addRow("", self.confirm_before_exit_check)
        form.addRow("", self.start_with_windows_check)

        self.tabs.addTab(tab, "Behavior")

    def on_appearance_section_toggled(
        self,
        selected_section: CollapsibleSection,
        expanded: bool,
    ) -> None:
        if not expanded:
            return

        for section in self.appearance_sections:
            if section is not selected_section:
                section.set_expanded(False)

    def build_logo_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.logo_tab = tab
        toolbar_config = self.active_toolbar_config()
        self.logo_editor_widget = LogoEditorWidget(
            toolbar_config["logo"],
            int(toolbar_config.get("logo", {}).get("height", DEFAULT_CONFIG["logo"]["height"])),
            tab,
            profile_id=self.active_profile_id(),
            asset_context=self.asset_context(),
            transfer_callback=self.transfer_logo_menu_item,
        )
        self.logo_add_item_button = self.logo_editor_widget.menu_editor.add_item_button
        self.logo_add_item_button.hide()
        self.tabs.currentChanged.connect(lambda _index: self.update_logo_add_item_button_visibility())
        self.logo_editor_widget.tabs.currentChanged.connect(lambda _index: self.update_logo_add_item_button_visibility())
        self.logo_editor_widget.configurationChanged.connect(self.schedule_working_preview)
        layout.addWidget(self.logo_editor_widget)
        self.tabs.addTab(tab, "Logo")

    def build_saved_profiles_tab(self) -> None:
        self.saved_profiles_editor = SavedProfilesEditorWidget(
            self.config,
            self.current_saved_toolbar_profile,
            self.load_saved_toolbar_profile,
            self.import_profile_package,
            self.export_selected_profile_package,
            self.export_all_profile_packages,
            self,
        )
        self.saved_profiles_editor.activeProfileChanged.connect(self.on_active_profile_name_changed)
        self.tabs.addTab(self.saved_profiles_editor, "Profiles")

    def sanitize_export_filename(self, name: str) -> str:
        cleaned = "".join(char if char.isalnum() or char in {" ", "-", "_"} else "_" for char in name.strip())
        cleaned = " ".join(cleaned.split()).strip()
        return cleaned or "ToolBar2-Profile"

    def require_committed_profiles_for_export(self) -> bool:
        if self.has_unsaved_changes():
            QtWidgets.QMessageBox.warning(
                self,
                "Export Profiles",
                "Save your current Settings changes before exporting profiles.",
            )
            return False
        return True

    def export_selected_profile_package(self, profile_id: str) -> None:
        if not self.require_committed_profiles_for_export():
            return
        profile = self.saved_profiles_editor.profile_by_id(profile_id)
        profile_name = str(profile.get("name") or profile_id) if profile else profile_id
        suggested = f"{self.sanitize_export_filename(profile_name)}.ToolBar2-profile.zip"
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Selected Profile",
            suggested,
            "ToolBar2 profile package (*.zip)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        result = export_profile_package(
            destination,
            [profile_id],
            str(self.config.get("active_user_profile_id") or ""),
        )
        self.show_profile_export_result(result)

    def export_all_profile_packages(self) -> None:
        if not self.require_committed_profiles_for_export():
            return
        suggested = f"ToolBar2-Profiles-{date.today().isoformat()}.zip"
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export All Profiles",
            suggested,
            "ToolBar2 profile package (*.zip)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        profile_ids = [
            str(record.get("profile_id") or "")
            for record in list_user_profile_records()
            if str(record.get("profile_id") or "").strip()
        ]
        result = export_profile_package(
            destination,
            profile_ids,
            str(self.config.get("active_user_profile_id") or ""),
        )
        self.show_profile_export_result(result)

    def show_profile_export_result(self, result) -> None:
        if not result.success:
            QtWidgets.QMessageBox.warning(
                self,
                "Export Profiles",
                "\n".join(result.errors) or "The profile export failed.",
            )
            return
        message = f"Exported {result.exported_count} profile{'s' if result.exported_count != 1 else ''}."
        if result.warnings:
            message += "\n\nSkipped:\n" + "\n".join(result.warnings)
            QtWidgets.QMessageBox.warning(self, "Export Profiles", message)
        else:
            QtWidgets.QMessageBox.information(self, "Export Profiles", message)

    def import_profile_package(self, zip_path: str | None = None) -> None:
        if not zip_path:
            zip_path, _filter = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Import Profiles",
                "",
                "ToolBar2 profile package (*.zip)",
            )
        if not zip_path:
            return
        existing_profiles = self.saved_profiles_editor.current_profiles()
        inspection = inspect_profile_package_detailed(Path(zip_path))
        if not inspection.success:
            QtWidgets.QMessageBox.warning(
                self,
                "Import Profiles",
                "\n".join(inspection.errors) or "The profile package could not be inspected.",
            )
            return
        dialog = ProfileImportDialog(
            inspection,
            existing_profiles,
            self.connected_monitor_options(),
            str(self.config.get("active_user_profile_id") or ""),
            self,
        )
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        result = import_profile_package_plan_to_staging(
            Path(zip_path),
            self.staging_session_id,
            existing_profiles,
            dialog.import_plans(),
        )
        if not result.success:
            QtWidgets.QMessageBox.warning(
                self,
                "Import Profiles",
                "\n".join(result.errors) or "The profile package could not be imported.",
            )
            return
        self.saved_profiles_editor.apply_imported_profiles(
            result.imported_profiles,
            result.selected_profile_id,
        )
        active_id = str(self.config.get("active_user_profile_id") or "")
        self.pending_active_profile_replacement = next(
            (
                copy.deepcopy(profile)
                for profile in result.imported_profiles
                if str(profile.get("profile_id") or "") == active_id
            ),
            None,
        )
        message = "\n".join(
            [
                f"Imported as new: {result.imported_as_new}",
                f"Replaced: {result.replaced}",
                f"Skipped: {result.skipped}",
                f"Unmapped monitor toolbars: {result.unmapped_monitor_toolbars}",
                f"Missing launcher targets left unchanged: {result.missing_targets_left}",
                "",
                "Click the main Settings Save button to commit these imports.",
            ]
        )
        if result.warnings:
            message += "\n\nWarnings:\n" + "\n".join(result.warnings)
        QtWidgets.QMessageBox.information(self, "Import Profiles", message)

    def connected_monitor_options(self) -> list[dict]:
        options: list[dict] = []
        primary_screen = QtGui.QGuiApplication.primaryScreen()
        for index, screen in enumerate(QtGui.QGuiApplication.screens()):
            screen_id = monitor_id(screen)
            metadata = monitor_metadata(screen, index)
            options.append(
                {
                    "monitor_id": screen_id,
                    "label": monitor_display_name(screen, index),
                    "metadata": metadata,
                    "primary": screen == primary_screen,
                }
            )
        return options

    def current_toolbar_key(self) -> str:
        if self.current_monitor_mode() == "per_monitor" and self.active_profile_monitor_id:
            return self.active_profile_monitor_id
        return "shared"

    def current_toolbar_label(self) -> str:
        if self.current_toolbar_key() == "shared":
            return "Shared Toolbar"
        known = self.config.get("monitoring", {}).get("known_monitors", {})
        metadata = known.get(self.active_profile_monitor_id, {}) if isinstance(known, dict) else {}
        if isinstance(metadata, dict):
            return str(metadata.get("display_name") or self.active_profile_monitor_id)
        return self.active_profile_monitor_id

    def working_profiles_for_transfer(self) -> list[tuple[str, str]]:
        profiles = self.saved_profiles_editor.current_profiles() if hasattr(self, "saved_profiles_editor") else []
        active_id = str(self.config.get("active_user_profile_id") or "")
        active_name = str(self.config.get("user_profile_name") or "Default")
        found_active = False
        result: list[tuple[str, str]] = []
        for profile in profiles:
            profile_id = str(profile.get("profile_id") or "")
            if not profile_id:
                continue
            if profile_id == active_id:
                found_active = True
                result.append((active_name, profile_id))
            else:
                result.append((str(profile.get("name") or profile_id), profile_id))
        if active_id and not found_active:
            result.insert(0, (active_name, active_id))
        return result

    def get_working_profile(self, profile_id: str) -> dict | None:
        active_id = str(self.config.get("active_user_profile_id") or "")
        if profile_id == active_id:
            self.write_current_forms_to_active_config()
            return profile_json_from_runtime(self.config, localize_assets=False)
        if not hasattr(self, "saved_profiles_editor"):
            return None
        profile = self.saved_profiles_editor.profile_by_id(profile_id)
        return copy.deepcopy(profile) if profile is not None else None

    def update_working_profile(self, profile_data: dict) -> None:
        profile_id = str(profile_data.get("profile_id") or "")
        active_id = str(self.config.get("active_user_profile_id") or "")
        if profile_id == active_id:
            self.config = runtime_config_from_profile_json(
                root_config_from_runtime(self.config),
                profile_data,
                self.screen_count(),
                self.connected_monitor_ids(),
            )
            self.load_active_toolbar_forms()
            return
        self.saved_profiles_editor.apply_imported_profiles([profile_data], profile_id)

    def runtime_from_working_profile(self, profile_id: str) -> dict | None:
        profile = self.get_working_profile(profile_id)
        if profile is None:
            return None
        return runtime_config_from_profile_json(
            root_config_from_runtime(self.config),
            profile,
            self.screen_count(),
            self.connected_monitor_ids(),
        )

    def profile_from_runtime(self, runtime_config: dict) -> dict:
        return profile_json_from_runtime(runtime_config, localize_assets=False)

    def toolbar_refs_for_profile(self, profile_id: str) -> list[ToolbarRef]:
        runtime = self.runtime_from_working_profile(profile_id)
        if runtime is None:
            return []
        profile_name = str(runtime.get("user_profile_name") or profile_id)
        mode = str(runtime.get("monitoring", {}).get("mode") or "single")
        refs: list[ToolbarRef] = []
        if mode != "per_monitor":
            refs.append(ToolbarRef(profile_id, profile_name, "shared", "Shared Toolbar", None))
            return refs
        known = runtime.get("monitoring", {}).get("known_monitors", {})
        for monitor_id_value, profile in runtime.get("toolbar_profiles", {}).items():
            label = str(monitor_id_value)
            metadata = known.get(monitor_id_value, {}) if isinstance(known, dict) else {}
            if isinstance(metadata, dict):
                label = str(metadata.get("display_name") or label)
            if monitor_id_value not in connected_monitor_ids():
                label = f"{label} - Not currently connected"
            monitor_profile_id = str(profile.get("profile_id") or "") if isinstance(profile, dict) else None
            refs.append(ToolbarRef(profile_id, profile_name, str(monitor_id_value), label, monitor_profile_id))
        return refs or [ToolbarRef(profile_id, profile_name, "shared", "Shared Toolbar", None)]

    def toolbar_config_for_ref(self, runtime: dict, ref: ToolbarRef) -> dict:
        if ref.toolbar_key != "shared":
            ensure_monitor_profile(runtime, ref.toolbar_key)
            return effective_config_for_monitor(runtime, ref.toolbar_key)
        return runtime

    def store_toolbar_config_for_ref(self, runtime: dict, ref: ToolbarRef, toolbar_config: dict) -> None:
        if ref.toolbar_key != "shared":
            update_monitor_profile(runtime, ref.toolbar_key, toolbar_config)
            return
        for key in ("appearance", "behavior", "logo", "menus"):
            runtime[key] = copy.deepcopy(toolbar_config[key])

    def destination_containers_for_ref(self, ref: ToolbarRef) -> list[tuple[str, list[int]]]:
        runtime = self.runtime_from_working_profile(ref.profile_id)
        if runtime is None:
            return []
        return destination_containers(self.toolbar_config_for_ref(runtime, ref))

    def positions_for_ref(self, ref: ToolbarRef, container_path: list[int] | None) -> list[tuple[str, str, list[int] | None]]:
        runtime = self.runtime_from_working_profile(ref.profile_id)
        if runtime is None:
            return []
        return sibling_positions(self.toolbar_config_for_ref(runtime, ref), container_path)

    def transfer_toolbar_item(self, mode: str, source_path: list[int], source_item: dict) -> None:
        self.write_current_forms_to_active_config()
        source_profile_id = str(self.config.get("active_user_profile_id") or "")
        source_profile_name = str(self.config.get("user_profile_name") or "Default")
        source_toolbar_key = self.current_toolbar_key()
        top_level = len(source_path) == 1
        dialog = ItemTransferDialog(
            mode,
            source_profile_name,
            self.current_toolbar_label(),
            str(source_item.get("name") or "Separator" if source_item.get("type") == "separator" else source_item.get("name") or "Item"),
            (source_profile_id, source_toolbar_key),
            self.toolbar_refs_for_profile,
            self.destination_containers_for_ref,
            self.positions_for_ref,
            self.working_profiles_for_transfer(),
            top_level,
            self,
        )
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        destinations = dialog.destinations()
        try:
            if mode == "move":
                self.move_toolbar_item(source_profile_id, source_toolbar_key, source_path, source_item, destinations)
            else:
                self.copy_toolbar_item(source_item, destinations)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Transfer Failed", str(exc) or "The item could not be transferred.")
            return
        verb = "Moved" if mode == "move" else "Copied"
        QtWidgets.QMessageBox.information(
            self,
            f"{verb} Item",
            f"{verb} \"{source_item.get('name', 'Item')}\" to {len(destinations)} toolbar{'s' if len(destinations) != 1 else ''}.",
        )
        self.load_active_toolbar_forms()
        self.schedule_working_preview()

    def transfer_logo_menu_item(self, mode: str, source_path: list[int], source_item: dict) -> None:
        self.write_current_forms_to_active_config()
        source_profile_id = str(self.config.get("active_user_profile_id") or "")
        source_profile_name = str(self.config.get("user_profile_name") or "Default")
        dialog = ItemTransferDialog(
            mode,
            source_profile_name,
            "Logo Click Menu",
            str(source_item.get("name") or "Separator" if source_item.get("type") == "separator" else source_item.get("name") or "Item"),
            (source_profile_id, f"logo:{self.current_toolbar_key()}"),
            self.toolbar_refs_for_profile,
            self.destination_containers_for_ref,
            self.positions_for_ref,
            self.working_profiles_for_transfer(),
            False,
            self,
        )
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        destinations = dialog.destinations()
        before_config = copy.deepcopy(self.config)
        before_profiles = self.saved_profiles_editor.current_profiles() if hasattr(self, "saved_profiles_editor") else []
        try:
            self.copy_toolbar_item(source_item, destinations)
            if mode == "move":
                self.remove_logo_menu_item_at_path(source_path)
        except Exception as exc:
            self.config = before_config
            if hasattr(self, "saved_profiles_editor"):
                self.saved_profiles_editor._profiles = before_profiles
                self.saved_profiles_editor.mark_dirty()
                self.saved_profiles_editor.refresh_profiles(str(self.config.get("active_user_profile_id") or ""))
            QtWidgets.QMessageBox.warning(self, "Transfer Failed", str(exc) or "The item could not be transferred.")
            return
        verb = "Moved" if mode == "move" else "Copied"
        QtWidgets.QMessageBox.information(
            self,
            f"{verb} Item",
            f"{verb} \"{source_item.get('name', 'Item')}\" to {len(destinations)} toolbar{'s' if len(destinations) != 1 else ''}.",
        )
        self.load_active_toolbar_forms()
        self.schedule_working_preview()

    def remove_logo_menu_item_at_path(self, path: list[int]) -> None:
        toolbar_config = self.active_toolbar_config()
        items = toolbar_config.setdefault("logo", {}).setdefault("menu_items", [])
        if not path:
            raise ValueError("Source item no longer exists.")
        parent_items = items
        for index in path[:-1]:
            item = parent_items[index]
            parent_items = item.setdefault("items", [])
        removed = parent_items.pop(path[-1])
        if not isinstance(removed, dict):
            raise ValueError("Source item could not be removed.")
        self.store_active_toolbar_config(toolbar_config)

    def copy_toolbar_item(self, source_item: dict, destinations: list[TransferDestination]) -> None:
        errors: list[str] = []
        for destination in destinations:
            try:
                runtime = self.runtime_from_working_profile(destination.toolbar.profile_id)
                if runtime is None:
                    raise ValueError("Destination profile no longer exists.")
                toolbar = self.toolbar_config_for_ref(runtime, destination.toolbar)
                context = AssetContext(
                    destination.toolbar.profile_id,
                    destination.toolbar.monitor_profile_id,
                    self.staging_session_id,
                )
                clone = clone_item_for_destination(source_item, context)
                insert_item(toolbar, clone, destination)
                self.store_toolbar_config_for_ref(runtime, destination.toolbar, toolbar)
                self.update_working_profile(self.profile_from_runtime(runtime))
            except Exception as exc:
                errors.append(f"{destination.toolbar.profile_name} -> {destination.toolbar.toolbar_label}: {exc}")
        if errors:
            raise ValueError("Some destinations failed:\n" + "\n".join(errors))

    def move_toolbar_item(
        self,
        source_profile_id: str,
        source_toolbar_key: str,
        source_path: list[int],
        source_item: dict,
        destinations: list[TransferDestination],
    ) -> None:
        if len(destinations) != 1:
            raise ValueError("Move requires one destination.")
        before_profiles = self.saved_profiles_editor.current_profiles() if hasattr(self, "saved_profiles_editor") else []
        before_config = copy.deepcopy(self.config)
        try:
            self.copy_toolbar_item(source_item, destinations)
            source_runtime = self.runtime_from_working_profile(source_profile_id)
            if source_runtime is None:
                raise ValueError("Source profile no longer exists.")
            source_ref = ToolbarRef(source_profile_id, "", source_toolbar_key, "")
            toolbar = self.toolbar_config_for_ref(source_runtime, source_ref)
            if transfer_item_at_path(toolbar, source_path) is None:
                raise ValueError("Source item no longer exists.")
            if remove_item_at_path(toolbar, source_path) is None:
                raise ValueError("Source item could not be removed.")
            self.store_toolbar_config_for_ref(source_runtime, source_ref, toolbar)
            self.update_working_profile(self.profile_from_runtime(source_runtime))
        except Exception:
            self.config = before_config
            if hasattr(self, "saved_profiles_editor"):
                self.saved_profiles_editor._profiles = before_profiles
                self.saved_profiles_editor.mark_dirty()
                self.saved_profiles_editor.refresh_profiles(str(self.config.get("active_user_profile_id") or ""))
            raise

    def on_active_profile_name_changed(self, name: str) -> None:
        self.config["user_profile_name"] = str(name or "Default")
        self.update_window_title()

    def on_main_tab_changed(self, _index: int) -> None:
        if (
            hasattr(self, "saved_profiles_editor")
            and self.tabs.currentWidget() is self.saved_profiles_editor
            and not self.saved_profiles_editor.has_unsaved_changes()
        ):
            self.saved_profiles_editor.refresh_config(self.config)

    def populate_logo_tab(self) -> None:
        if not hasattr(self, "logo_editor_widget"):
            return
        toolbar_config = self.active_toolbar_config()
        self.logo_editor_widget.profile_id = self.active_profile_id()
        self.logo_editor_widget.asset_context = self.asset_context()
        self.logo_editor_widget.transfer_callback = self.transfer_logo_menu_item
        self.logo_editor_widget.menu_editor.transfer_callback = self.transfer_logo_menu_item
        self.logo_editor_widget.set_logo_config(
            toolbar_config["logo"],
            int(toolbar_config.get("logo", {}).get("height", DEFAULT_CONFIG["logo"]["height"])),
        )
        self.update_logo_add_item_button_visibility()

    def count_logo_items(self, items: list[dict]) -> int:
        total = 0
        for item in items:
            total += 1
            if item.get("type") == "submenu":
                total += self.count_logo_items(item.get("items", []))
        return total

    def update_logo_add_item_button_visibility(self) -> None:
        if not hasattr(self, "logo_add_item_button"):
            return
        show_button = (
            self.tabs.currentWidget() is getattr(self, "logo_tab", None)
            and self.logo_editor_widget.tabs.currentIndex() == 1
        )
        self.logo_add_item_button.setVisible(show_button)

    def build_menus_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        self.menu_editor = MenuEditorWidget(
            self.active_toolbar_config(),
            tab,
            profile_id=self.active_profile_id(),
            asset_context=self.asset_context(),
            transfer_callback=self.transfer_toolbar_item,
        )
        self.menu_editor.configurationChanged.connect(self.on_menu_editor_configuration_changed)
        layout.addWidget(self.menu_editor)
        self.tabs.addTab(tab, "Menus")

    def on_menu_editor_configuration_changed(self) -> None:
        if not hasattr(self, "menu_editor"):
            return
        appearance = self.menu_editor.config.get("appearance", {})
        self.loading_appearance = True
        try:
            self.show_web_search_bar_check.setChecked(
                bool(appearance.get("show_web_search_bar", False))
            )
            self.web_search_width_spin.setValue(
                int(appearance.get("web_search_width", 180))
            )
            self.web_search_placeholder_edit.setText(
                str(appearance.get("web_search_placeholder") or "Search the web...")
            )
            engine_index = self.web_search_engine_combo.findData(
                appearance.get("web_search_engine", "Google")
            )
            self.web_search_engine_combo.setCurrentIndex(max(0, engine_index))
            self.web_search_custom_url_edit.setText(
                str(appearance.get("web_search_custom_url") or "")
            )
        finally:
            self.loading_appearance = False
        self.update_web_search_custom_url_state()
        self.schedule_working_preview()

    def current_saved_toolbar_profile(
        self,
        name: str,
        description: str,
        profile_id: str | None,
    ) -> dict:
        self.write_current_forms_to_active_config()
        config = copy.deepcopy(self.config)
        config["active_user_profile_id"] = profile_id or config.get("active_user_profile_id") or ""
        config["user_profile_name"] = name
        config["user_profile_description"] = description
        return profile_json_from_runtime(config, localize_assets=False)

    def load_saved_toolbar_profile(self, profile: dict) -> bool:
        self.write_current_forms_to_active_config()
        try:
            self.config = runtime_config_from_profile_json(
                root_config_from_runtime(self.config),
                profile,
                self.screen_count(),
                self.connected_monitor_ids(),
            )
            self.ensure_active_profile_selection()
            self.populate_behavior()
            self.populate_profile_selector()
            self.load_active_toolbar_forms()
            if hasattr(self, "saved_profiles_editor"):
                self.saved_profiles_editor.upsert_profile(profile_json_from_runtime(self.config, localize_assets=False))
            self.update_window_title()
            self.preview_working_config()
            return True
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Load Saved Toolbar Profile", str(exc) or "The profile could not be loaded.")
            return False

    def preview_working_config(self) -> None:
        self.write_current_forms_to_active_config()
        self.send_working_preview()

    def schedule_working_preview(self, *_args: object) -> None:
        if self.loading_appearance or self.loading_behavior or self.loading_monitors or self.loading_profile_selector:
            return
        self.working_preview_timer.start()

    def send_working_preview(self) -> None:
        self.working_preview_timer.stop()
        if self.loading_appearance or self.loading_behavior or self.loading_monitors or self.loading_profile_selector:
            return
        self.write_current_forms_to_active_config()
        self.sync_monitor_selection_from_controls()
        self.preview_active = True
        self.preview_rolled_back = False
        if self.preview_working_config_callback is not None:
            preview_config = copy.deepcopy(self.config)
            preview_config.setdefault("monitoring", {})["settings_live_preview"] = True
            self.preview_working_config_callback(preview_config)

    def int_spin(self, minimum: int, maximum: int) -> QtWidgets.QSpinBox:
        spin = QtWidgets.QSpinBox()
        spin.setRange(minimum, maximum)
        return spin

    def populate_appearance(self) -> None:
        appearance = self.active_toolbar_config()["appearance"]
        self.loading_appearance = True
        try:
            for key, button in self.color_buttons.items():
                button.setProperty("color_value", appearance[key])
                self.update_color_button(button, appearance[key])
            self.opacity_spin.setValue(appearance["opacity"])
            self.toolbar_height_spin.setValue(appearance["toolbar_height"])
            self.button_height_spin.setValue(appearance["button_height"])
            self.corner_radius_spin.setValue(appearance["corner_radius"])
            self.horizontal_padding_spin.setValue(appearance["horizontal_padding"])
            self.vertical_padding_spin.setValue(int(appearance.get("vertical_padding", 4)))
            self.menu_button_spacing_spin.setValue(appearance["menu_button_spacing"])
            self.auto_toolbar_width_check.setChecked(bool(appearance.get("auto_toolbar_width", True)))
            self.toolbar_width_spin.setValue(int(appearance.get("toolbar_width", 1000)))
            horizontal_alignment_index = self.horizontal_alignment_combo.findData(
                appearance.get("horizontal_alignment", "center")
            )
            self.horizontal_alignment_combo.setCurrentIndex(max(0, horizontal_alignment_index))
            self.horizontal_offset_spin.setValue(int(appearance.get("horizontal_offset", 0)))
            alignment_index = self.menu_alignment_combo.findData(
                appearance.get("menu_alignment", "center")
            )
            self.menu_alignment_combo.setCurrentIndex(max(0, alignment_index))
            self.show_settings_button_check.setChecked(
                bool(appearance.get("show_settings_button", True))
            )
            self.show_exit_button_check.setChecked(
                bool(appearance.get("show_exit_button", False))
            )
            self.show_web_search_bar_check.setChecked(
                bool(appearance.get("show_web_search_bar", False))
            )
            self.web_search_width_spin.setValue(
                int(appearance.get("web_search_width", 180))
            )
            self.web_search_placeholder_edit.setText(
                str(appearance.get("web_search_placeholder") or "Search the web...")
            )
            engine_index = self.web_search_engine_combo.findData(
                appearance.get("web_search_engine", "Google")
            )
            self.web_search_engine_combo.setCurrentIndex(max(0, engine_index))
            self.web_search_custom_url_edit.setText(
                str(appearance.get("web_search_custom_url") or "")
            )
        finally:
            self.loading_appearance = False
        self.update_web_search_custom_url_state()
        self.update_toolbar_width_controls()
        self.apply_active_toolbar_background()

    def current_appearance_from_form(self) -> dict:
        appearance = copy.deepcopy(self.active_toolbar_config()["appearance"])
        for key, button in self.color_buttons.items():
            appearance[key] = button.property("color_value")
        appearance["opacity"] = self.opacity_spin.value()
        appearance["toolbar_height"] = self.toolbar_height_spin.value()
        appearance["button_height"] = self.button_height_spin.value()
        appearance["corner_radius"] = self.corner_radius_spin.value()
        appearance["horizontal_padding"] = self.horizontal_padding_spin.value()
        appearance["vertical_padding"] = self.vertical_padding_spin.value()
        appearance["menu_button_spacing"] = self.menu_button_spacing_spin.value()
        appearance["auto_toolbar_width"] = self.auto_toolbar_width_check.isChecked()
        appearance["toolbar_width"] = self.toolbar_width_spin.value()
        appearance["horizontal_alignment"] = str(self.horizontal_alignment_combo.currentData() or "center")
        appearance["horizontal_offset"] = self.horizontal_offset_spin.value()
        appearance["show_settings_button"] = self.show_settings_button_check.isChecked()
        appearance["show_exit_button"] = self.show_exit_button_check.isChecked()
        appearance["show_web_search_bar"] = self.show_web_search_bar_check.isChecked()
        appearance["web_search_width"] = self.web_search_width_spin.value()
        appearance["web_search_placeholder"] = self.web_search_placeholder_edit.text().strip() or "Search the web..."
        appearance["web_search_engine"] = str(self.web_search_engine_combo.currentData() or "Google")
        appearance["web_search_custom_url"] = self.web_search_custom_url_edit.text().strip()
        if hasattr(self, "menu_alignment_combo"):
            appearance["menu_alignment"] = str(self.menu_alignment_combo.currentData() or "center")
        return appearance

    def schedule_appearance_preview(self, *_args: object) -> None:
        if self.loading_appearance:
            return
        self.schedule_working_preview()

    def send_appearance_preview(self) -> None:
        appearance = self.current_appearance_from_form()
        self.preview_active = True
        self.preview_rolled_back = False
        self.preview_callback(
            appearance,
            self.current_monitor_mode(),
            self.active_profile_monitor_id,
        )

    def ensure_active_profile_selection(self) -> None:
        selected_ids = [
            str(item) for item in self.config.get("monitoring", {}).get("selected_monitor_ids", [])
            if str(item or "").strip()
        ]
        if self.active_profile_monitor_id not in selected_ids:
            self.active_profile_monitor_id = selected_ids[0] if selected_ids else ""

    def active_profile_id(self) -> str | None:
        if self.current_monitor_mode() != "per_monitor" or not self.active_profile_monitor_id:
            return None
        profile = ensure_monitor_profile(self.config, self.active_profile_monitor_id)
        return str(profile.get("profile_id") or "")

    def asset_context(self) -> AssetContext:
        return AssetContext(
            str(self.config.get("active_user_profile_id") or "default"),
            self.active_profile_id(),
            self.staging_session_id,
        )

    def active_toolbar_config(self) -> dict:
        if self.current_monitor_mode() == "per_monitor" and self.active_profile_monitor_id:
            ensure_monitor_profile(self.config, self.active_profile_monitor_id)
            return effective_config_for_monitor(self.config, self.active_profile_monitor_id)
        return self.config

    def store_active_toolbar_config(self, toolbar_config: dict) -> None:
        if self.current_monitor_mode() == "per_monitor" and self.active_profile_monitor_id:
            update_monitor_profile(self.config, self.active_profile_monitor_id, toolbar_config)
            return
        for key in ("appearance", "behavior", "logo", "menus"):
            if key in toolbar_config:
                self.config[key] = copy.deepcopy(toolbar_config[key])

    def populate_profile_selector(self) -> None:
        if not hasattr(self, "profile_combo"):
            return
        selected_ids = self.checked_monitor_ids() or [
            str(item) for item in self.config.get("monitoring", {}).get("selected_monitor_ids", [])
            if str(item or "").strip()
        ]
        self.loading_profile_selector = True
        self.profile_combo.clear()
        known = self.config.get("monitoring", {}).get("known_monitors", {})
        connected = set(connected_monitor_ids())
        for monitor_id_value in self.unique_monitor_ids(selected_ids):
            if self.current_monitor_mode() == "per_monitor":
                ensure_monitor_profile(self.config, monitor_id_value)
            label = monitor_id_value
            metadata = known.get(monitor_id_value, {}) if isinstance(known, dict) else {}
            if isinstance(metadata, dict):
                label = str(metadata.get("display_name") or label)
            if monitor_id_value not in connected:
                label = f"{label} - Not currently connected"
            self.profile_combo.addItem(label, monitor_id_value)
        index = self.profile_combo.findData(self.active_profile_monitor_id)
        if index < 0 and self.profile_combo.count():
            index = 0
            self.active_profile_monitor_id = str(self.profile_combo.itemData(0) or "")
        self.profile_combo.setCurrentIndex(index)
        self.loading_profile_selector = False
        enabled = self.current_monitor_mode() == "per_monitor" and bool(self.active_profile_monitor_id)
        self.copy_profile_button.setEnabled(enabled)
        self.reset_profile_button.setEnabled(enabled)

    def select_profile_monitor(self, monitor_id: str) -> None:
        if self.current_monitor_mode() != "per_monitor":
            return
        index = self.profile_combo.findData(monitor_id)
        if index < 0:
            return
        self.profile_combo.setCurrentIndex(index)

    def update_profile_selector_visibility(self) -> None:
        if hasattr(self, "profile_group"):
            self.profile_group.setVisible(self.current_monitor_mode() == "per_monitor")

    def on_profile_selection_changed(self) -> None:
        if self.loading_profile_selector:
            return
        self.write_current_forms_to_active_config()
        self.active_profile_monitor_id = str(self.profile_combo.currentData() or "")
        self.load_active_toolbar_forms()
        self.schedule_working_preview()

    def copy_profile_from(self) -> None:
        if not self.active_profile_monitor_id:
            return
        self.write_current_forms_to_active_config()
        sources = []
        known = self.config.get("monitoring", {}).get("known_monitors", {})
        for monitor_id_value, profile in self.config.get("toolbar_profiles", {}).items():
            if monitor_id_value == self.active_profile_monitor_id or not isinstance(profile, dict):
                continue
            label = monitor_id_value
            metadata = known.get(monitor_id_value, {}) if isinstance(known, dict) else {}
            if isinstance(metadata, dict):
                label = str(metadata.get("display_name") or label)
            sources.append((label, monitor_id_value))
        if not sources:
            QtWidgets.QMessageBox.information(self, "Copy Toolbar", "No other monitor profiles are available.")
            return
        labels = [label for label, _monitor_id in sources]
        label, ok = QtWidgets.QInputDialog.getItem(self, "Copy Toolbar From", "Source toolbar:", labels, 0, False)
        if not ok:
            return
        source_monitor_id = sources[labels.index(label)][1]
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Replace Toolbar Profile",
            "Replace this monitor's toolbar with the selected profile?",
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            copy_monitor_profile(self.config, source_monitor_id, self.active_profile_monitor_id)
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "Copy Failed", str(exc) or "The toolbar profile could not be copied.")
            return
        self.load_active_toolbar_forms()
        self.schedule_working_preview()

    def reset_current_profile(self) -> None:
        if not self.active_profile_monitor_id:
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Reset This Toolbar",
            "Reset this monitor's toolbar to the current shared toolbar?",
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            reset_monitor_profile(self.config, self.active_profile_monitor_id)
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "Reset Failed", str(exc) or "The toolbar profile could not be reset.")
            return
        self.load_active_toolbar_forms()
        self.schedule_working_preview()

    def load_active_toolbar_forms(self) -> None:
        self.populate_appearance()
        self.populate_behavior_values()
        if self.menu_editor is not None:
            self.menu_editor.refresh_config(self.active_toolbar_config(), self.active_profile_id(), self.asset_context())
        self.populate_logo_tab()

    def populate_behavior_values(self) -> None:
        self.loading_behavior = True
        behavior = self.active_toolbar_config()["behavior"]
        try:
            self.trigger_height_spin.setValue(behavior["trigger_height"])
            self.hide_delay_spin.setValue(behavior["hide_delay_ms"])
            self.animation_duration_spin.setValue(behavior["animation_duration_ms"])
            self.open_menus_on_hover_check.setChecked(behavior["open_menus_on_hover"])
            self.hover_delay_spin.setValue(behavior["menu_hover_delay_ms"])
            self.confirm_before_exit_check.setChecked(behavior["confirm_before_exit"])
            application = self.config.get("application", {})
            if isinstance(application, dict):
                self.start_with_windows_check.setChecked(bool(application.get("start_with_windows", False)))
            else:
                self.start_with_windows_check.setChecked(False)
        finally:
            self.loading_behavior = False

    def populate_behavior(self) -> None:
        self.loading_monitors = True
        monitoring = self.config.get("monitoring", {})
        mode = str(monitoring.get("mode") or "single")
        if mode not in {"single", "selected_shared", "all_shared", "per_monitor"}:
            mode = "single"
        mode_index = self.monitor_mode_combo.findData(mode)
        self.monitor_mode_combo.setCurrentIndex(max(0, mode_index))

        selected_ids = [str(item) for item in monitoring.get("selected_monitor_ids", []) if str(item or "").strip()]
        screens = QtGui.QGuiApplication.screens()
        if not selected_ids:
            screen_index = self.config["behavior"]["screen_index"]
            if 0 <= screen_index < len(screens):
                selected_ids = [monitor_id(screens[screen_index])]
        self.rebuild_monitor_list(screens, monitoring.get("known_monitors", {}), selected_ids)
        self.loading_monitors = False
        self.update_monitor_controls()
        self.populate_behavior_values()

    def rebuild_monitor_list(
        self,
        screens: list[QtGui.QScreen],
        known_monitors: dict,
        selected_ids: list[str],
    ) -> None:
        self.monitor_list.clear()
        connected_ids: set[str] = set()
        for index, screen in enumerate(screens):
            screen_id = monitor_id(screen)
            connected_ids.add(screen_id)
            item = QtWidgets.QListWidgetItem(monitor_display_name(screen, index))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, screen_id)
            item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, True)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if screen_id in selected_ids
                else QtCore.Qt.CheckState.Unchecked
            )
            self.monitor_list.addItem(item)

        disconnected_ids = [
            screen_id
            for screen_id in selected_ids
            if screen_id and screen_id not in connected_ids
        ]
        if not disconnected_ids:
            return

        header = QtWidgets.QListWidgetItem("Disconnected saved monitors:")
        header.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
        self.monitor_list.addItem(header)
        for screen_id in disconnected_ids:
            metadata = known_monitors.get(screen_id, {}) if isinstance(known_monitors, dict) else {}
            display_name = metadata.get("display_name", screen_id) if isinstance(metadata, dict) else screen_id
            item = QtWidgets.QListWidgetItem(f"{display_name} - Not currently connected")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, screen_id)
            item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, False)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Checked)
            self.monitor_list.addItem(item)

    def refresh_monitor_list(
        self,
        connected_screens: list[QtGui.QScreen],
        known_monitors: dict,
        preserve_unsaved: bool = True,
    ) -> None:
        mode = self.current_monitor_mode() if preserve_unsaved else str(self.config.get("monitoring", {}).get("mode") or "single")
        selected_ids = self.checked_monitor_ids() if preserve_unsaved else [
            str(item) for item in self.config.get("monitoring", {}).get("selected_monitor_ids", [])
            if str(item or "").strip()
        ]
        self.loading_monitors = True
        mode_index = self.monitor_mode_combo.findData(mode if mode in {"single", "selected_shared", "all_shared", "per_monitor"} else "single")
        self.monitor_mode_combo.setCurrentIndex(max(0, mode_index))
        self.rebuild_monitor_list(connected_screens, known_monitors, selected_ids)
        self.loading_monitors = False
        self.update_monitor_controls()

    def current_monitor_mode(self) -> str:
        return str(self.monitor_mode_combo.currentData() or "single")

    def checked_monitor_ids(self) -> list[str]:
        ids: list[str] = []
        for index in range(self.monitor_list.count()):
            item = self.monitor_list.item(index)
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                screen_id = str(item.data(QtCore.Qt.ItemDataRole.UserRole) or "")
                if screen_id:
                    ids.append(screen_id)
        return ids

    def unique_monitor_ids(self, monitor_ids: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for screen_id in monitor_ids:
            if screen_id and screen_id not in seen:
                seen.add(screen_id)
                result.append(screen_id)
        return result

    def first_connected_monitor_id(self) -> str:
        ids = connected_monitor_ids()
        return ids[0] if ids else ""

    def set_only_monitor_checked(self, selected_item: QtWidgets.QListWidgetItem) -> None:
        self.loading_monitors = True
        for index in range(self.monitor_list.count()):
            item = self.monitor_list.item(index)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if item is selected_item
                else QtCore.Qt.CheckState.Unchecked
            )
        self.loading_monitors = False

    def ensure_one_monitor_checked(self) -> None:
        if self.checked_monitor_ids() or self.monitor_list.count() == 0:
            return
        self.monitor_list.item(0).setCheckState(QtCore.Qt.CheckState.Checked)

    def on_monitor_mode_changed(self) -> None:
        if self.loading_monitors:
            return
        self.write_current_forms_to_active_config()
        self.update_monitor_controls()
        if self.current_monitor_mode() == "per_monitor":
            for monitor_id_value in self.checked_monitor_ids():
                ensure_monitor_profile(self.config, monitor_id_value)
            self.ensure_active_profile_selection()
        self.populate_profile_selector()
        self.update_profile_selector_visibility()
        self.load_active_toolbar_forms()
        self.schedule_working_preview()

    def on_monitor_item_changed(self, item: QtWidgets.QListWidgetItem) -> None:
        if self.loading_monitors:
            return
        self.write_current_forms_to_active_config()
        if self.current_monitor_mode() != "single":
            previous_active_monitor_id = self.active_profile_monitor_id
            self.sync_monitor_selection_from_controls()
            if self.current_monitor_mode() == "per_monitor":
                checked_ids = self.checked_monitor_ids()
                if previous_active_monitor_id not in checked_ids:
                    self.active_profile_monitor_id = checked_ids[0] if checked_ids else ""
                self.populate_profile_selector()
                self.load_active_toolbar_forms()
            else:
                self.populate_profile_selector()
            self.schedule_working_preview()
            return
        if item.checkState() == QtCore.Qt.CheckState.Checked:
            self.set_only_monitor_checked(item)
        else:
            self.ensure_one_monitor_checked()
        self.sync_monitor_selection_from_controls()
        self.populate_profile_selector()
        self.schedule_working_preview()

    def update_monitor_controls(self) -> None:
        mode = self.current_monitor_mode()
        all_mode = mode == "all_shared"
        self.monitor_list.setEnabled(not all_mode)
        self.identify_monitors_button.setEnabled(self.screen_count() > 0)
        unmapped = self.config.get("unmapped_monitor_profiles", [])
        self.assign_imported_toolbar_button.setEnabled(
            mode == "per_monitor"
            and bool(self.active_profile_monitor_id)
            and isinstance(unmapped, list)
            and bool(unmapped)
        )
        self.select_all_monitors_button.setEnabled(not all_mode and mode != "single")
        self.select_none_monitors_button.setEnabled(not all_mode and mode != "single")
        if mode == "single":
            checked = self.checked_monitor_ids()
            if len(checked) > 1:
                for index in range(self.monitor_list.count()):
                    item = self.monitor_list.item(index)
                    if str(item.data(QtCore.Qt.ItemDataRole.UserRole) or "") == checked[0]:
                        self.set_only_monitor_checked(item)
                        break
            self.ensure_one_monitor_checked()

    def close_identification_overlays(self) -> None:
        overlays = list(self.identification_overlays)
        self.identification_overlays.clear()
        for overlay in overlays:
            try:
                overlay.close()
                overlay.deleteLater()
            except RuntimeError:
                pass

    def _remove_identification_overlay(self, overlay: MonitorIdentificationOverlay) -> None:
        self._remove_identification_overlay_reference(overlay)
        try:
            overlay.close()
            overlay.deleteLater()
        except RuntimeError:
            pass

    def identification_display_name(self, screen: QtGui.QScreen, index: int) -> str:
        checklist_name = monitor_display_name(screen, index)
        prefix = f"Monitor {index + 1} - "
        if checklist_name.startswith(prefix):
            checklist_name = checklist_name[len(prefix):]
        primary_suffix = " - Primary"
        if checklist_name.endswith(primary_suffix):
            checklist_name = checklist_name[: -len(primary_suffix)]
        parts = checklist_name.split(" - ", 1)
        if len(parts) == 2:
            return parts[1].strip() or checklist_name
        return str(screen.name() or monitor_id(screen) or "Unknown").strip()

    def identify_monitors(self) -> None:
        self.close_identification_overlays()
        primary_screen = QtGui.QGuiApplication.primaryScreen()
        for index, screen in enumerate(QtGui.QGuiApplication.screens()):
            geometry = screen.geometry()
            screen_id = monitor_id(screen)
            overlay = MonitorIdentificationOverlay(
                screen=screen,
                monitor_number=index + 1,
                display_name=self.identification_display_name(screen, index),
                resolution=f"{geometry.width()} × {geometry.height()}",
                is_primary=screen == primary_screen,
                stable_monitor_id=screen_id,
            )
            self.identification_overlays.append(overlay)
            overlay.destroyed.connect(
                lambda _object=None, current=overlay: self._remove_identification_overlay_reference(current)
            )
            overlay.show()
            QtCore.QTimer.singleShot(
                1000,
                lambda current=overlay: self._remove_identification_overlay(current),
            )

    def _remove_identification_overlay_reference(
        self,
        overlay: MonitorIdentificationOverlay,
    ) -> None:
        if overlay in self.identification_overlays:
            self.identification_overlays.remove(overlay)

    def assign_imported_toolbar(self) -> None:
        if self.current_monitor_mode() != "per_monitor" or not self.active_profile_monitor_id:
            return
        unmapped = self.config.get("unmapped_monitor_profiles", [])
        if not isinstance(unmapped, list) or not unmapped:
            QtWidgets.QMessageBox.information(self, "Assign Imported Toolbar", "No imported monitor toolbars are available.")
            return
        labels = []
        valid_items = []
        for item in unmapped:
            if not isinstance(item, dict) or not isinstance(item.get("toolbar"), dict):
                continue
            metadata = item.get("source_monitor_metadata", {})
            label = str(item.get("source_monitor_id") or "Imported monitor")
            if isinstance(metadata, dict):
                label = str(metadata.get("display_name") or label)
            labels.append(label)
            valid_items.append(item)
        if not valid_items:
            return
        label, ok = QtWidgets.QInputDialog.getItem(
            self,
            "Assign Imported Toolbar",
            "Imported toolbar:",
            labels,
            0,
            False,
        )
        if not ok:
            return
        index = labels.index(label)
        selected = valid_items[index]
        self.write_current_forms_to_active_config()
        self.config.setdefault("toolbar_profiles", {})[self.active_profile_monitor_id] = copy.deepcopy(selected["toolbar"])
        self.config["unmapped_monitor_profiles"] = [item for item in unmapped if item is not selected]
        monitoring = self.config.setdefault("monitoring", {})
        selected_ids = self.unique_monitor_ids([
            *[str(item) for item in monitoring.get("selected_monitor_ids", [])],
            self.active_profile_monitor_id,
        ])
        monitoring["selected_monitor_ids"] = selected_ids
        self.populate_profile_selector()
        self.load_active_toolbar_forms()
        self.schedule_working_preview()
        self.update_monitor_controls()

    def select_all_monitors(self) -> None:
        if self.current_monitor_mode() == "single":
            self.ensure_one_monitor_checked()
            return
        self.write_current_forms_to_active_config()
        self.loading_monitors = True
        for index in range(self.monitor_list.count()):
            self.monitor_list.item(index).setCheckState(QtCore.Qt.CheckState.Checked)
        self.loading_monitors = False
        self.sync_monitor_selection_from_controls()
        if self.current_monitor_mode() == "per_monitor":
            if self.active_profile_monitor_id not in self.checked_monitor_ids():
                self.active_profile_monitor_id = self.checked_monitor_ids()[0] if self.checked_monitor_ids() else ""
            self.populate_profile_selector()
            self.load_active_toolbar_forms()
        self.schedule_working_preview()

    def select_no_monitors(self) -> None:
        if self.current_monitor_mode() == "single":
            self.ensure_one_monitor_checked()
            return
        self.write_current_forms_to_active_config()
        self.loading_monitors = True
        for index in range(self.monitor_list.count()):
            self.monitor_list.item(index).setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.loading_monitors = False
        self.sync_monitor_selection_from_controls()
        if self.current_monitor_mode() == "per_monitor":
            self.active_profile_monitor_id = ""
            self.populate_profile_selector()
            self.load_active_toolbar_forms()
        self.schedule_working_preview()

    def validate_monitor_selection(self) -> bool:
        mode = self.current_monitor_mode()
        if mode in {"single", "selected_shared", "per_monitor"} and not self.checked_monitor_ids():
            QtWidgets.QMessageBox.warning(self, "Monitor Required", "Select at least one monitor.")
            return False
        return True

    def populate_menu_tree(self) -> None:
        self.menu_tree.clear()
        for menu in self.config["menus"]:
            menu_item = QtWidgets.QTreeWidgetItem([menu.get("name", "Menu")])
            menu_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, menu)
            self.menu_tree.addTopLevelItem(menu_item)
            for launcher in menu.get("items", []):
                child = QtWidgets.QTreeWidgetItem([launcher.get("name", "Launcher")])
                child.setData(0, QtCore.Qt.ItemDataRole.UserRole, launcher)
                menu_item.addChild(child)
            menu_item.setExpanded(True)
        if self.menu_tree.topLevelItemCount():
            self.menu_tree.setCurrentItem(self.menu_tree.topLevelItem(0))

    def pick_color(self, field: str) -> None:
        current = self.color_buttons[field].property("color_value")
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(current), self, COLOR_FIELDS[field])
        if color.isValid():
            value = color.name()
            self.color_buttons[field].setProperty("color_value", value)
            self.update_color_button(self.color_buttons[field], value)
            if field == "toolbar_background":
                self.apply_active_toolbar_background()
            self.schedule_working_preview()

    def update_color_button(self, button: QtWidgets.QPushButton, value: str) -> None:
        button.setText(value)
        button.setStyleSheet(f"background-color: {value}; color: {self.readable_text_color(value)};")

    def readable_text_color(self, value: str) -> str:
        color = QtGui.QColor(value)
        if not color.isValid():
            return "#000000"
        brightness = (color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000
        return "#000000" if brightness > 150 else "#ffffff"

    def reset_appearance(self) -> None:
        toolbar_config = self.active_toolbar_config()
        toolbar_config["appearance"] = copy.deepcopy(DEFAULT_CONFIG["appearance"])
        self.store_active_toolbar_config(toolbar_config)
        self.populate_appearance()
        self.schedule_working_preview()

    def write_current_forms_to_active_config(self) -> None:
        if not hasattr(self, "trigger_height_spin"):
            return
        toolbar_config = self.active_toolbar_config()
        appearance = toolbar_config["appearance"]
        for key, button in self.color_buttons.items():
            appearance[key] = button.property("color_value")
        appearance["opacity"] = self.opacity_spin.value()
        appearance["toolbar_height"] = self.toolbar_height_spin.value()
        appearance["button_height"] = self.button_height_spin.value()
        appearance["corner_radius"] = self.corner_radius_spin.value()
        appearance["horizontal_padding"] = self.horizontal_padding_spin.value()
        appearance["vertical_padding"] = self.vertical_padding_spin.value()
        appearance["menu_button_spacing"] = self.menu_button_spacing_spin.value()
        appearance["menu_alignment"] = str(self.menu_alignment_combo.currentData() or "center")
        appearance["auto_toolbar_width"] = self.auto_toolbar_width_check.isChecked()
        appearance["toolbar_width"] = self.toolbar_width_spin.value()
        appearance["horizontal_alignment"] = str(self.horizontal_alignment_combo.currentData() or "center")
        appearance["horizontal_offset"] = self.horizontal_offset_spin.value()
        appearance["show_settings_button"] = self.show_settings_button_check.isChecked()
        appearance["show_exit_button"] = self.show_exit_button_check.isChecked()
        appearance["show_web_search_bar"] = self.show_web_search_bar_check.isChecked()
        appearance["web_search_width"] = self.web_search_width_spin.value()
        appearance["web_search_placeholder"] = self.web_search_placeholder_edit.text().strip() or "Search the web..."
        appearance["web_search_engine"] = str(self.web_search_engine_combo.currentData() or "Google")
        appearance["web_search_custom_url"] = self.web_search_custom_url_edit.text().strip()

        behavior = toolbar_config["behavior"]
        behavior["trigger_height"] = self.trigger_height_spin.value()
        behavior["hide_delay_ms"] = self.hide_delay_spin.value()
        behavior["animation_duration_ms"] = self.animation_duration_spin.value()
        behavior["open_menus_on_hover"] = self.open_menus_on_hover_check.isChecked()
        behavior["menu_hover_delay_ms"] = self.hover_delay_spin.value()
        behavior["confirm_before_exit"] = self.confirm_before_exit_check.isChecked()

        if hasattr(self, "logo_editor_widget"):
            toolbar_config["logo"] = self.logo_editor_widget.result_logo()

        if self.menu_editor is not None:
            self.menu_editor.config.setdefault("appearance", {}).update(
                {
                    "show_web_search_bar": appearance.get("show_web_search_bar", False),
                    "web_search_width": appearance.get("web_search_width", 180),
                    "web_search_placeholder": appearance.get("web_search_placeholder", "Search the web..."),
                    "web_search_engine": appearance.get("web_search_engine", "Google"),
                    "web_search_custom_url": appearance.get("web_search_custom_url", ""),
                }
            )
            menu_config = self.menu_editor.current_config()
            toolbar_config["menus"] = menu_config["menus"]
            menu_appearance = menu_config.get("appearance", {})
            for key in (
                "show_web_search_bar",
                "web_search_width",
                "web_search_placeholder",
                "web_search_engine",
                "web_search_custom_url",
                "web_search_position",
            ):
                toolbar_config["appearance"][key] = menu_appearance.get(
                    key,
                    toolbar_config["appearance"].get(key),
                )
        self.store_active_toolbar_config(toolbar_config)

    def monitor_selection_from_controls(self) -> tuple[str, list[str], str]:
        mode = self.current_monitor_mode()
        checked_ids = self.checked_monitor_ids()
        if mode == "single":
            selected_ids = checked_ids[:1]
        elif mode in {"selected_shared", "per_monitor"}:
            connected_ids = connected_monitor_ids()
            disconnected_saved_ids = [
                str(item) for item in self.config.get("monitoring", {}).get("selected_monitor_ids", [])
                if str(item or "").strip() and str(item) not in connected_ids
            ]
            selected_ids = self.unique_monitor_ids([*checked_ids, *disconnected_saved_ids])
        else:
            selected_ids = checked_ids or [
                str(item) for item in self.config.get("monitoring", {}).get("selected_monitor_ids", [])
                if str(item or "").strip()
            ]
            if not selected_ids:
                first_id = self.first_connected_monitor_id()
                selected_ids = [first_id] if first_id else []
        if mode == "all_shared":
            connected_ids = connected_monitor_ids()
            primary_screen = QtGui.QGuiApplication.primaryScreen()
            primary_id = monitor_id(primary_screen) if primary_screen is not None else ""
            legacy_monitor_id = primary_id if primary_id in connected_ids else self.first_connected_monitor_id()
        else:
            legacy_monitor_id = selected_ids[0] if selected_ids else self.first_connected_monitor_id()
        return mode, self.unique_monitor_ids(selected_ids), legacy_monitor_id

    def sync_monitor_selection_from_controls(self) -> None:
        behavior = self.config["behavior"]
        mode, selected_ids, legacy_monitor_id = self.monitor_selection_from_controls()
        behavior["screen_index"] = index_for_monitor_id(legacy_monitor_id)
        if behavior["screen_index"] is None:
            behavior["screen_index"] = 0
        self.config["monitoring"] = {
            **self.config.get("monitoring", {}),
            "mode": mode,
            "selected_monitor_ids": selected_ids,
        }
        if mode == "per_monitor":
            for monitor_id_value in selected_ids:
                ensure_monitor_profile(self.config, monitor_id_value)
        known_monitors = self.config["monitoring"].get("known_monitors")
        if not isinstance(known_monitors, dict):
            known_monitors = {}
            self.config["monitoring"]["known_monitors"] = known_monitors
        for index, screen in enumerate(QtGui.QGuiApplication.screens()):
            screen_id = monitor_id(screen)
            if screen_id:
                existing = known_monitors.get(screen_id, {})
                metadata = monitor_metadata(screen, index)
                known_monitors[screen_id] = {**existing, **metadata} if isinstance(existing, dict) else metadata
                geometry = screen.geometry()
                screen_snapshot = {
                    "screen_name": str(screen.name() or ""),
                    "screen_geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                }
                if screen_id == legacy_monitor_id:
                    behavior.update(screen_snapshot)
                profile = profile_for_monitor(self.config, screen_id)
                if isinstance(profile, dict):
                    profile.setdefault("behavior", {}).update(screen_snapshot)

    def collect_config(self) -> dict:
        self.write_current_forms_to_active_config()
        self.sync_monitor_selection_from_controls()
        if startup_supported():
            self.config.setdefault("application", {})["start_with_windows"] = (
                self.start_with_windows_check.isChecked()
            )
        return validate_config(self.config, self.screen_count(), self.connected_monitor_ids())

    def save(self) -> None:
        if not self.validate_monitor_selection():
            return
        self.appearance_preview_timer.stop()
        self.working_preview_timer.stop()
        if self.pending_active_profile_replacement is not None:
            self.config = runtime_config_from_profile_json(
                root_config_from_runtime(self.config),
                self.pending_active_profile_replacement,
                self.screen_count(),
                self.connected_monitor_ids(),
            )
        else:
            self.config = self.collect_config()
        if hasattr(self, "saved_profiles_editor") and self.pending_active_profile_replacement is None:
            self.saved_profiles_editor.upsert_profile(profile_json_from_runtime(self.config, localize_assets=False))
        logger.debug(
            "saving user profiles count=%s names=%s",
            len(self.saved_profiles_editor.current_profiles()) if hasattr(self, "saved_profiles_editor") else 0,
            [
                profile.get("name")
                for profile in self.saved_profiles_editor.current_profiles()
            ] if hasattr(self, "saved_profiles_editor") else [],
        )
        try:
            saved_config = self.save_callback(self.config)
            if hasattr(self, "saved_profiles_editor"):
                commit_user_profile_records(
                    self.saved_profiles_editor.current_profiles(),
                    self.saved_profiles_editor.deleted_profile_ids(),
                )
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Config Save Failed",
                str(exc) or "The toolbar configuration could not be saved.",
            )
            return
        if isinstance(saved_config, dict):
            self.config = validate_config(saved_config, self.screen_count(), self.connected_monitor_ids())
        delete_staging_session(self.staging_session_id)
        self.staging_session_id = uuid.uuid4().hex
        if hasattr(self, "saved_profiles_editor"):
            self.saved_profiles_editor.mark_saved()
        self.refresh_from_config(self.config)
        if hasattr(self, "saved_profiles_editor"):
            self.saved_profiles_editor.mark_saved()
            self.saved_profiles_editor.set_active_profile(str(self.config.get("active_user_profile_id") or ""))
            self.saved_baseline_profiles = self.saved_profiles_editor.current_profiles()
        self.saved_baseline_config = copy.deepcopy(self.config)
        self.update_window_title()
        self.preview_active = False
        self.preview_rolled_back = True
        self.pending_active_profile_replacement = None
        self.save_button.setText("Saved")
        QtCore.QTimer.singleShot(1200, lambda: self.save_button.setText("Save"))

    def on_selection_changed(
        self,
        current: QtWidgets.QTreeWidgetItem | None,
        previous: QtWidgets.QTreeWidgetItem | None,
    ) -> None:
        if previous is not None:
            self.apply_editor_to_item(previous)
        self.selected_item = current
        self.load_editor(current)

    def selected_data(self) -> dict | None:
        if self.selected_item is None:
            return None
        data = self.selected_item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def selected_top_menu(self) -> tuple[int, dict] | None:
        item = self.selected_item
        if item is None:
            return None
        if item.parent() is not None:
            item = item.parent()
        index = self.menu_tree.indexOfTopLevelItem(item)
        if index < 0:
            return None
        return index, self.config["menus"][index]

    def load_editor(self, item: QtWidgets.QTreeWidgetItem | None) -> None:
        self.loading_selection = True
        data = item.data(0, QtCore.Qt.ItemDataRole.UserRole) if item is not None else None
        is_launcher = isinstance(data, dict) and data.get("type") == "launcher"
        for widget in (
            self.name_edit,
            self.target_edit,
            self.type_combo,
            self.arguments_edit,
            self.working_dir_edit,
            self.browse_button,
            self.edit_item_button,
        ):
            widget.setEnabled(is_launcher)

        if is_launcher:
            self.name_edit.setText(data.get("name", ""))
            self.target_edit.setText(data.get("target", ""))
            self.type_combo.setCurrentText(data.get("target_type", "Auto Detect"))
            self.arguments_edit.setText(data.get("arguments", ""))
            self.working_dir_edit.setText(data.get("working_directory", ""))
        else:
            self.name_edit.clear()
            self.target_edit.clear()
            self.type_combo.setCurrentIndex(0)
            self.arguments_edit.clear()
            self.working_dir_edit.clear()
        self.loading_selection = False

    def apply_editor_to_selected(self) -> None:
        if self.selected_item is not None:
            self.apply_editor_to_item(self.selected_item)

    def apply_editor_to_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
        if self.loading_selection:
            return
        data = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict) or data.get("type") != "launcher":
            return
        data["name"] = self.name_edit.text().strip() or "Launcher"
        data["target"] = self.target_edit.text().strip()
        data["target_type"] = self.type_combo.currentText()
        data["arguments"] = self.arguments_edit.text().strip()
        data["working_directory"] = self.working_dir_edit.text().strip()
        item.setText(0, data["name"])

    def add_top_level_menu(self) -> None:
        self.apply_editor_to_selected()
        name, ok = QtWidgets.QInputDialog.getText(self, "Add Menu", "Menu name:")
        if not ok:
            return
        menu = {"name": name.strip() or "Menu", "type": "menu", "items": []}
        self.config["menus"].append(menu)
        self.populate_menu_tree()
        self.menu_tree.setCurrentItem(self.menu_tree.topLevelItem(self.menu_tree.topLevelItemCount() - 1))

    def rename_selected_menu(self) -> None:
        selected = self.selected_top_menu()
        if selected is None:
            return
        index, menu = selected
        name, ok = QtWidgets.QInputDialog.getText(self, "Rename Menu", "Menu name:", text=menu["name"])
        if ok:
            menu["name"] = name.strip() or "Menu"
            self.menu_tree.topLevelItem(index).setText(0, menu["name"])

    def delete_selected(self) -> None:
        item = self.selected_item
        if item is None:
            return
        if item.parent() is None:
            index = self.menu_tree.indexOfTopLevelItem(item)
            if index >= 0:
                self.config["menus"].pop(index)
        else:
            parent_index = self.menu_tree.indexOfTopLevelItem(item.parent())
            child_index = item.parent().indexOfChild(item)
            if parent_index >= 0 and child_index >= 0:
                self.config["menus"][parent_index]["items"].pop(child_index)
        self.populate_menu_tree()

    def move_selected(self, direction: int) -> None:
        selected = self.selected_top_menu()
        if selected is None:
            return
        index, _menu = selected
        new_index = index + direction
        if not 0 <= new_index < len(self.config["menus"]):
            return
        self.config["menus"][index], self.config["menus"][new_index] = (
            self.config["menus"][new_index],
            self.config["menus"][index],
        )
        self.populate_menu_tree()
        self.menu_tree.setCurrentItem(self.menu_tree.topLevelItem(new_index))

    def add_launcher_item(self) -> None:
        selected = self.selected_top_menu()
        if selected is None:
            return
        index, menu = selected
        self.apply_editor_to_selected()
        launcher = {
            "name": "New Launcher",
            "type": "launcher",
            "target": "",
            "target_type": "Auto Detect",
            "arguments": "",
            "working_directory": "",
        }
        menu.setdefault("items", []).append(launcher)
        self.populate_menu_tree()
        parent = self.menu_tree.topLevelItem(index)
        child = parent.child(parent.childCount() - 1)
        self.menu_tree.setCurrentItem(child)

    def delete_selected_launcher(self) -> None:
        item = self.selected_item
        if item is None or item.parent() is None:
            return
        self.delete_selected()

    def browse_target(self) -> None:
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(self, "Choose Target")
        if path:
            self.target_edit.setText(path)

    def has_unsaved_changes(self) -> bool:
        current_config = self.collect_config()
        baseline_config = validate_config(
            copy.deepcopy(self.saved_baseline_config),
            self.screen_count(),
            self.connected_monitor_ids(),
        )
        if current_config != baseline_config:
            return True
        if not hasattr(self, "saved_profiles_editor"):
            return False
        if self.saved_profiles_editor.has_unsaved_changes():
            return True
        return self.saved_profiles_editor.current_profiles() != self.saved_baseline_profiles

    def discard_working_session_and_refresh(self, config: dict) -> None:
        self.appearance_preview_timer.stop()
        self.working_preview_timer.stop()
        self.close_identification_overlays()
        if self.preview_active and not self.preview_rolled_back:
            self.preview_rolled_back = True
        delete_staging_session(self.staging_session_id)
        self.staging_session_id = uuid.uuid4().hex
        self.preview_active = False
        self.preview_rolled_back = True
        self.pending_active_profile_replacement = None
        self.config = validate_config(
            copy.deepcopy(config),
            self.screen_count(),
            self.connected_monitor_ids(),
        )
        self.refresh_from_config(self.config)
        if hasattr(self, "saved_profiles_editor"):
            self.saved_profiles_editor.refresh_config(self.config)
            self.saved_profiles_editor.mark_saved()
            self.saved_profiles_editor.set_active_profile(str(self.config.get("active_user_profile_id") or ""))
            self.saved_baseline_profiles = self.saved_profiles_editor.current_profiles()
        self.saved_baseline_config = copy.deepcopy(self.config)
        self.update_window_title()

    def reject(self) -> None:
        delete_staging_session(self.staging_session_id)
        self.close_identification_overlays()
        self.config = copy.deepcopy(self.saved_baseline_config)
        self.rollback_preview_once()
        super().reject()

    def rollback_preview_once(self) -> None:
        self.appearance_preview_timer.stop()
        self.working_preview_timer.stop()
        if self.preview_active and not self.preview_rolled_back:
            self.preview_rolled_back = True
            self.rollback_preview_callback()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        delete_staging_session(self.staging_session_id)
        self.close_identification_overlays()
        self.rollback_preview_once()
        super().closeEvent(event)
