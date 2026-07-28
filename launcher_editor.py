from __future__ import annotations

import copy

from PyQt6 import QtCore, QtGui, QtWidgets

from app_icon import apply_window_icon
from config_manager import DEFAULT_CONFIG, LAUNCH_TARGET_TYPES, PYTHON_MODES, validate_button_style, validate_item
from icon_utilities import (
    IconPreviewLabel,
    AssetContext,
    custom_icon,
    icon_for_item,
    import_icon_from_mime_data,
    import_launcher_icon_file,
    import_launcher_icon_image,
    import_launcher_icon_url,
)
from target_detection import detect_target


class LauncherEditorDialog(QtWidgets.QDialog):
    def __init__(
        self,
        item: dict | None = None,
        parent: QtWidgets.QWidget | None = None,
        global_appearance: dict | None = None,
        top_level: bool = False,
        profile_id: str | None = None,
        asset_context: AssetContext | None = None,
    ) -> None:
        super().__init__(parent)
        self.item = validate_item(copy.deepcopy(item or {"type": "launcher"}))
        self.global_appearance = global_appearance or DEFAULT_CONFIG["appearance"]
        self.top_level = top_level
        self.profile_id = profile_id
        self.asset_context = asset_context
        self.name_manually_edited = bool(self.item.get("name"))

        self.setWindowTitle("Launcher Item")
        apply_window_icon(self)
        self.resize(620, 360)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.name_edit = QtWidgets.QLineEdit(self.item["name"])
        self.target_edit = QtWidgets.QLineEdit(self.item["target"])
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItems(sorted(LAUNCH_TARGET_TYPES))
        self.type_combo.setCurrentText(self.item["target_type"])
        self.arguments_edit = QtWidgets.QLineEdit(self.item["arguments"])
        self.working_dir_edit = QtWidgets.QLineEdit(self.item["working_directory"])
        self.python_mode_combo = QtWidgets.QComboBox()
        self.python_mode_combo.addItems(sorted(PYTHON_MODES))
        self.python_mode_combo.setCurrentText(self.item["python_mode"])
        self.enabled_check = QtWidgets.QCheckBox("Enabled")
        self.enabled_check.setChecked(self.item["enabled"])
        self.accept_dropped_files_check = QtWidgets.QCheckBox("Accept dropped files")
        self.accept_dropped_files_check.setChecked(bool(self.item.get("accept_dropped_files", False)))
        self.folder_drop_action_combo = QtWidgets.QComboBox()
        self.folder_drop_action_combo.addItem("Move to this folder", "move")
        self.folder_drop_action_combo.addItem("Copy to this folder", "copy")
        self.folder_drop_action_combo.addItem("Ask each time", "ask")
        folder_drop_action = str(self.item.get("folder_drop_action") or "move")
        action_index = self.folder_drop_action_combo.findData(folder_drop_action)
        self.folder_drop_action_combo.setCurrentIndex(max(0, action_index))
        self.icon_only_check = QtWidgets.QCheckBox("Icon only")
        self.icon_only_check.setChecked(bool(self.item.get("icon_only", False)))
        self.use_custom_check = QtWidgets.QCheckBox("Use custom toolbar button colors")
        self.use_custom_check.setChecked(bool(self.item.get("button_style", {}).get("use_custom_colors", False)))
        self.icon_edit = QtWidgets.QLineEdit(self.item["icon"])
        self.icon_edit.setReadOnly(True)
        self.icon_edit.setPlaceholderText("Use target icon")
        self.icon_preview = IconPreviewLabel()
        self.icon_preview.iconDropped.connect(self.import_dropped_icon)

        target_row = self.row_with_button(self.target_edit, "Browse Target", self.browse_target)
        cwd_row = self.row_with_button(self.working_dir_edit, "Browse Working Directory", self.browse_working_directory)
        icon_buttons = QtWidgets.QHBoxLayout()
        choose_icon = QtWidgets.QPushButton("Choose Icon")
        use_target_icon = QtWidgets.QPushButton("Use Target Icon")
        choose_icon.clicked.connect(self.choose_icon)
        use_target_icon.clicked.connect(self.use_target_icon)
        icon_buttons.addWidget(choose_icon)
        icon_buttons.addWidget(use_target_icon)

        form.addRow("Display name", self.name_edit)
        form.addRow("Target", target_row)
        form.addRow("Target type", self.type_combo)
        form.addRow("Arguments", self.arguments_edit)
        form.addRow("Working directory", cwd_row)
        form.addRow("Python execution mode", self.python_mode_combo)
        form.addRow("", self.enabled_check)
        form.addRow("", self.accept_dropped_files_check)
        self.folder_drop_action_label = QtWidgets.QLabel("When items are dropped")
        form.addRow(self.folder_drop_action_label, self.folder_drop_action_combo)
        form.addRow("Icon", self.icon_edit)
        form.addRow("Preview", self.icon_preview)
        form.addRow("", icon_buttons)
        if self.top_level:
            form.addRow("", self.icon_only_check)
            form.addRow("", self.use_custom_check)

            self.color_buttons: dict[str, QtWidgets.QPushButton] = {}
            labels = {
                "background": "Button background",
                "hover": "Button hover",
                "text": "Button text",
                "border": "Button border",
            }
            style = validate_button_style(self.item.get("button_style"), self.global_style_values())
            for key, label in labels.items():
                button = QtWidgets.QPushButton()
                button.clicked.connect(lambda checked=False, field=key: self.pick_color(field))
                button.setProperty("color_value", style[key])
                self.update_color_button(button, style[key])
                self.color_buttons[key] = button
                form.addRow(label, button)

            self.preview_button = QtWidgets.QPushButton(self.item["name"])
            self.preview_button.setMinimumHeight(36)
            self.preview_button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            form.addRow("Button preview", self.preview_button)

            reset_button = QtWidgets.QPushButton("Reset Colors to Global Defaults")
            reset_button.clicked.connect(self.reset_colors_to_global)
            layout.addWidget(reset_button, 0)
        else:
            self.color_buttons = {}
            self.preview_button = None

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.name_edit.textEdited.connect(self.mark_name_edited)
        self.target_edit.textChanged.connect(self.target_changed)
        self.type_combo.currentTextChanged.connect(self.update_python_mode_state)
        self.type_combo.currentTextChanged.connect(self.update_preview)
        self.type_combo.currentTextChanged.connect(self.update_drop_controls)
        self.accept_dropped_files_check.toggled.connect(self.update_drop_controls)
        self.icon_edit.textChanged.connect(self.update_preview)
        self.name_edit.textChanged.connect(self.update_preview)
        self.icon_only_check.toggled.connect(self.update_preview)
        self.use_custom_check.toggled.connect(self.update_controls)
        self.update_python_mode_state()
        self.update_drop_controls()
        self.update_controls()

    def row_with_button(self, line_edit: QtWidgets.QLineEdit, text: str, callback) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(line_edit)
        button = QtWidgets.QPushButton(text)
        button.clicked.connect(callback)
        row.addWidget(button)
        return row

    def mark_name_edited(self) -> None:
        self.name_manually_edited = True

    def target_changed(self, text: str) -> None:
        detected = detect_target(text)
        if self.type_combo.currentText() == "Auto Detect":
            detected_type = detected["target_type"]
            if detected_type in LAUNCH_TARGET_TYPES:
                self.type_combo.blockSignals(True)
                self.type_combo.setCurrentText(detected_type)
                self.type_combo.blockSignals(False)
        if not self.name_manually_edited:
            self.name_edit.setText(detected["name"])
        if "arguments" in detected:
            self.arguments_edit.setText(str(detected.get("arguments") or ""))
        if "working_directory" in detected:
            self.working_dir_edit.setText(str(detected.get("working_directory") or ""))
        self.update_python_mode_state()
        self.update_preview()

    def update_python_mode_state(self) -> None:
        self.python_mode_combo.setEnabled(self.type_combo.currentText() == "Python Script")

    def update_drop_controls(self) -> None:
        is_folder = self.type_combo.currentText() == "Folder"
        self.accept_dropped_files_check.setText(
            "Accept dropped items" if is_folder else "Accept dropped files"
        )
        self.folder_drop_action_label.setVisible(is_folder)
        self.folder_drop_action_combo.setVisible(is_folder)
        self.folder_drop_action_combo.setEnabled(
            is_folder and self.accept_dropped_files_check.isChecked()
        )

    def update_preview(self) -> None:
        icon = self.current_icon()
        if icon.isNull():
            self.icon_preview.setPixmap(QtGui.QPixmap())
            self.icon_preview.setText("Drop image here")
        else:
            self.icon_preview.setText("")
            self.icon_preview.setPixmap(icon.pixmap(28, 28))
        if not self.top_level or self.preview_button is None:
            return

        launcher_name = self.name_edit.text().strip() or "Launcher"
        if self.icon_only_check.isChecked() and not icon.isNull():
            self.preview_button.setText("")
            self.preview_button.setToolTip(launcher_name)
        else:
            self.preview_button.setText(launcher_name)
            self.preview_button.setToolTip("")
        self.preview_button.setIcon(icon)
        self.preview_button.setIconSize(QtCore.QSize(22, 22))
        values = self.current_style_values() if self.use_custom_check.isChecked() else self.global_style_values()
        self.preview_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {values["background"]};
                color: {values["text"]};
                border: 1px solid {values["border"]};
                border-radius: 6px;
                padding: 0 18px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {values["hover"]};
            }}
            """
        )

    def update_controls(self) -> None:
        if not self.top_level:
            self.update_preview()
            return
        enabled = self.use_custom_check.isChecked()
        for button in self.color_buttons.values():
            button.setEnabled(enabled)
        self.update_preview()

    def global_style_values(self) -> dict[str, str]:
        defaults = DEFAULT_CONFIG["appearance"]
        return {
            "background": self.global_appearance.get("button_background", defaults["button_background"]),
            "hover": self.global_appearance.get("button_hover", defaults["button_hover"]),
            "text": self.global_appearance.get("button_text", defaults["button_text"]),
            "border": self.global_appearance.get("border_color", defaults["border_color"]),
        }

    def pick_color(self, field: str) -> None:
        current = self.color_buttons[field].property("color_value")
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(current), self, "Choose Color")
        if color.isValid():
            value = color.name()
            self.color_buttons[field].setProperty("color_value", value)
            self.update_color_button(self.color_buttons[field], value)
            self.update_preview()

    def update_color_button(self, button: QtWidgets.QPushButton, value: str) -> None:
        button.setText(value)
        button.setStyleSheet(f"background-color: {value}; color: {self.readable_text_color(value)};")

    def readable_text_color(self, value: str) -> str:
        color = QtGui.QColor(value)
        if not color.isValid():
            return "#000000"
        brightness = (color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000
        return "#000000" if brightness > 150 else "#ffffff"

    def reset_colors_to_global(self) -> None:
        for key, value in self.global_style_values().items():
            self.color_buttons[key].setProperty("color_value", value)
            self.update_color_button(self.color_buttons[key], value)
        self.update_preview()

    def current_style_values(self) -> dict[str, str]:
        return {key: str(button.property("color_value")) for key, button in self.color_buttons.items()}

    def current_icon(self) -> QtGui.QIcon:
        icon_path = self.icon_edit.text().strip()
        icon = custom_icon(icon_path)
        if icon_path and not icon.isNull():
            return icon
        return icon_for_item(
            {
                "type": "launcher",
                "target": self.target_edit.text().strip(),
                "target_type": self.type_combo.currentText(),
                "icon": "",
            },
            self,
        )

    def browse_target(self) -> None:
        target_type = self.type_combo.currentText()
        if target_type == "Folder":
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose Target Folder")
            if path:
                self.target_edit.setText(path)
            return
        if target_type in {"Website", "Command"}:
            self.target_edit.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose Target")
        if path:
            self.target_edit.setText(path)

    def browse_working_directory(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose Working Directory")
        if path:
            self.working_dir_edit.setText(path)

    def choose_icon(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose Launcher Icon",
            self.icon_edit.text().strip(),
            "Icon files (*.png *.jpg *.jpeg *.webp *.ico *.svg *.exe);;All files (*.*)",
        )
        if path:
            self.import_icon_file(path)

    def use_target_icon(self) -> None:
        self.icon_edit.clear()

    def import_icon_file(self, path: str) -> None:
        try:
            managed_path = import_launcher_icon_file(path, self.item["id"], self.profile_id, self.asset_context)
        except (OSError, ValueError) as exc:
            self.show_icon_error(str(exc))
            return
        self.icon_edit.setText(managed_path)
        self.update_preview()

    def import_icon_image(self, image: QtGui.QImage) -> None:
        try:
            managed_path = import_launcher_icon_image(image, self.item["id"], self.profile_id, self.asset_context)
        except (OSError, ValueError) as exc:
            self.show_icon_error(str(exc))
            return
        self.icon_edit.setText(managed_path)
        self.update_preview()

    def import_icon_url(self, url: str) -> None:
        try:
            managed_path = import_launcher_icon_url(url, self.item["id"], self.profile_id, self.asset_context)
        except (OSError, ValueError) as exc:
            self.show_icon_error(str(exc))
            return
        self.icon_edit.setText(managed_path)
        self.update_preview()

    def import_dropped_icon(self, mime: QtCore.QMimeData) -> None:
        if not import_icon_from_mime_data(
            mime,
            self.import_icon_file,
            self.import_icon_image,
            self.import_icon_url,
        ):
            self.show_icon_error("Drop a supported image, EXE file, or web image URL.")

    def show_icon_error(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Icon Import Failed", message or "That icon could not be imported.")

    def result_item(self) -> dict:
        item = {
            **self.item,
            "name": self.name_edit.text().strip() or "Launcher",
            "type": "launcher",
            "target": self.target_edit.text().strip(),
            "target_type": self.type_combo.currentText(),
            "arguments": self.arguments_edit.text().strip(),
            "working_directory": self.working_dir_edit.text().strip(),
            "python_mode": self.python_mode_combo.currentText(),
            "enabled": self.enabled_check.isChecked(),
            "accept_dropped_files": self.accept_dropped_files_check.isChecked(),
            "folder_drop_action": str(self.folder_drop_action_combo.currentData() or "move"),
            "icon": self.icon_edit.text().strip(),
        }
        if self.top_level:
            style_values = self.current_style_values()
            style_values["use_custom_colors"] = self.use_custom_check.isChecked()
            item["icon_only"] = self.icon_only_check.isChecked()
            item["button_style"] = validate_button_style(style_values, self.global_style_values())
        return validate_item(item)

    def accept(self) -> None:
        if not self.target_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Missing Target", "Choose or enter a target before saving.")
            self.target_edit.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
            self.target_edit.selectAll()
            return
        super().accept()
