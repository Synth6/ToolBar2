from __future__ import annotations

import copy

from PyQt6 import QtCore, QtGui, QtWidgets

from app_icon import apply_window_icon
from config_manager import validate_button_style, validate_menu
from icon_utilities import (
    AssetContext,
    IconPreviewLabel,
    folder_icon,
    import_icon_from_mime_data,
    import_menu_icon_file,
    import_menu_icon_image,
    import_menu_icon_url,
    menu_button_icon,
)


class FolderMenuPropertiesDialog(QtWidgets.QDialog):
    def __init__(
        self,
        menu: dict,
        parent: QtWidgets.QWidget | None = None,
        profile_id: str | None = None,
        asset_context: AssetContext | None = None,
        top_level: bool = False,
        button_fallbacks: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.profile_id = profile_id
        self.asset_context = asset_context
        self.top_level = top_level
        self.button_fallbacks = button_fallbacks
        self.menu = validate_menu(copy.deepcopy(menu), top_level=self.top_level, button_fallbacks=self.button_fallbacks)

        self.setWindowTitle("Edit Folder Menu")
        apply_window_icon(self)
        self.resize(520, 520 if self.top_level else 360)

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.name_edit = QtWidgets.QLineEdit(str(self.menu.get("name") or "Folder"))
        self.path_edit = QtWidgets.QLineEdit(str(self.menu.get("folder_path") or ""))
        browse = QtWidgets.QPushButton("Browse")
        browse.clicked.connect(self.browse_folder)
        path_row = QtWidgets.QHBoxLayout()
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse)

        self.include_files_check = QtWidgets.QCheckBox("Include files")
        self.include_files_check.setChecked(bool(self.menu.get("include_files", True)))
        self.include_folders_check = QtWidgets.QCheckBox("Include folders")
        self.include_folders_check.setChecked(bool(self.menu.get("include_folders", True)))
        self.show_open_folder_check = QtWidgets.QCheckBox("Show Open This Folder")
        self.show_open_folder_check.setChecked(bool(self.menu.get("show_open_folder_action", True)))

        self.icon_path_edit = QtWidgets.QLineEdit(str(self.menu.get("icon_path") or ""))
        self.icon_path_edit.setReadOnly(True)
        self.icon_path_edit.setPlaceholderText("Default folder icon")
        self.icon_managed = bool(self.menu.get("icon_managed", False))
        self.icon_only_check = QtWidgets.QCheckBox("Icon only")
        self.icon_only_check.setChecked(bool(self.menu.get("icon_only", False)))
        self.icon_preview = IconPreviewLabel()
        self.icon_preview.iconDropped.connect(self.import_dropped_icon)

        choose_icon_button = QtWidgets.QPushButton("Choose Icon")
        choose_icon_button.clicked.connect(self.choose_icon)
        default_icon_button = QtWidgets.QPushButton("Use Default Folder Icon")
        default_icon_button.clicked.connect(self.use_default_icon)
        remove_icon_button = QtWidgets.QPushButton("Remove Icon")
        remove_icon_button.clicked.connect(self.remove_icon)
        icon_buttons = QtWidgets.QHBoxLayout()
        icon_buttons.addWidget(choose_icon_button)
        icon_buttons.addWidget(default_icon_button)
        icon_buttons.addWidget(remove_icon_button)

        form.addRow("Name", self.name_edit)
        form.addRow("Folder path", path_row)
        form.addRow("", self.include_files_check)
        form.addRow("", self.include_folders_check)
        form.addRow("", self.show_open_folder_check)
        form.addRow("Icon", self.icon_path_edit)
        form.addRow("Preview", self.icon_preview)
        form.addRow("", icon_buttons)
        form.addRow("", self.icon_only_check)

        self.use_custom_check: QtWidgets.QCheckBox | None = None
        self.color_buttons: dict[str, QtWidgets.QPushButton] = {}
        if self.top_level:
            self.use_custom_check = QtWidgets.QCheckBox("Use custom toolbar button colors")
            self.use_custom_check.setChecked(bool(self.menu["button_style"]["use_custom_colors"]))
            form.addRow("", self.use_custom_check)

            labels = {
                "background": "Button background",
                "hover": "Button hover",
                "text": "Button text",
                "border": "Button border",
            }
            for key, label in labels.items():
                button = QtWidgets.QPushButton()
                button.clicked.connect(lambda checked=False, field=key: self.pick_color(field))
                self.color_buttons[key] = button
                form.addRow(label, button)

        self.preview_button = QtWidgets.QPushButton()
        self.preview_button.setMinimumHeight(36)
        self.preview_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        form.addRow("Button preview", self.preview_button)

        if self.top_level:
            reset_button = QtWidgets.QPushButton("Reset Colors to Global Defaults")
            reset_button.clicked.connect(self.reset_colors_to_global)
            layout.addWidget(reset_button, 0)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.name_edit.textChanged.connect(self.update_preview)
        self.icon_path_edit.textChanged.connect(self.update_preview)
        self.icon_only_check.toggled.connect(self.update_preview)
        if self.use_custom_check is not None:
            self.use_custom_check.toggled.connect(self.update_controls)
            self.populate_colors()
            self.update_controls()
        else:
            self.update_preview()

    def global_style_values(self) -> dict[str, str]:
        return self.button_fallbacks or {
            "background": "#3b3b3b",
            "hover": "#505050",
            "text": "#ffffff",
            "border": "#606060",
        }

    def populate_colors(self) -> None:
        style = self.menu.get("button_style", {})
        for key, button in self.color_buttons.items():
            value = str(style.get(key) or self.global_style_values()[key])
            button.setProperty("color_value", value)
            self.update_color_button(button, value)

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

    def browse_folder(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose Folder", self.path_edit.text().strip())
        if path:
            self.path_edit.setText(path)

    def choose_icon(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose Folder Menu Icon",
            self.icon_path_edit.text().strip(),
            "Icon files (*.png *.jpg *.jpeg *.webp *.ico *.svg *.exe);;All files (*.*)",
        )
        if path:
            self.import_icon_file(path)

    def use_default_icon(self) -> None:
        self.icon_path_edit.clear()
        self.icon_managed = False

    def remove_icon(self) -> None:
        self.icon_path_edit.clear()
        self.icon_managed = False

    def import_icon_file(self, path: str) -> None:
        try:
            managed_path = import_menu_icon_file(path, self.menu["id"], self.profile_id, self.asset_context)
        except (OSError, ValueError) as exc:
            self.show_icon_error(str(exc))
            return
        self.icon_managed = True
        self.icon_path_edit.setText(managed_path)
        self.update_preview()

    def import_icon_image(self, image: QtGui.QImage) -> None:
        try:
            managed_path = import_menu_icon_image(image, self.menu["id"], self.profile_id, self.asset_context)
        except (OSError, ValueError) as exc:
            self.show_icon_error(str(exc))
            return
        self.icon_managed = True
        self.icon_path_edit.setText(managed_path)
        self.update_preview()

    def import_icon_url(self, url: str) -> None:
        try:
            managed_path = import_menu_icon_url(url, self.menu["id"], self.profile_id, self.asset_context)
        except (OSError, ValueError) as exc:
            self.show_icon_error(str(exc))
            return
        self.icon_managed = True
        self.icon_path_edit.setText(managed_path)
        self.update_preview()

    def import_dropped_icon(self, mime: QtCore.QMimeData) -> None:
        if not import_icon_from_mime_data(mime, self.import_icon_file, self.import_icon_image, self.import_icon_url):
            self.show_icon_error("Drop a supported image, EXE file, or web image URL.")

    def show_icon_error(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Icon Import Failed", message or "That icon could not be imported.")

    def update_controls(self) -> None:
        enabled = bool(self.use_custom_check and self.use_custom_check.isChecked())
        for button in self.color_buttons.values():
            button.setEnabled(enabled)
        self.update_preview()

    def current_icon(self) -> QtGui.QIcon:
        icon = menu_button_icon(self.icon_path_edit.text().strip())
        if not icon.isNull():
            return icon
        return folder_icon(self)

    def update_icon_preview(self, icon: QtGui.QIcon) -> None:
        if icon.isNull():
            self.icon_preview.setPixmap(QtGui.QPixmap())
            self.icon_preview.setText("Drop image here")
            return
        self.icon_preview.setText("")
        self.icon_preview.setPixmap(icon.pixmap(28, 28))

    def update_preview(self) -> None:
        menu_name = self.name_edit.text().strip() or "Folder"
        icon = self.current_icon()
        if self.icon_only_check.isChecked() and not icon.isNull():
            self.preview_button.setText("")
            self.preview_button.setToolTip(menu_name)
        else:
            self.preview_button.setText(menu_name)
            self.preview_button.setToolTip("")
        self.preview_button.setIcon(icon)
        self.preview_button.setIconSize(QtCore.QSize(22, 22))
        self.update_icon_preview(icon)
        values = self.current_style_values() if self.use_custom_check and self.use_custom_check.isChecked() else self.global_style_values()
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

    def current_style_values(self) -> dict[str, str]:
        return {key: str(button.property("color_value")) for key, button in self.color_buttons.items()}

    def result_menu(self) -> dict:
        menu = copy.deepcopy(self.menu)
        menu["name"] = self.name_edit.text().strip() or "Folder"
        menu["folder_path"] = self.path_edit.text().strip()
        menu["include_files"] = self.include_files_check.isChecked()
        menu["include_folders"] = self.include_folders_check.isChecked()
        menu["show_open_folder_action"] = self.show_open_folder_check.isChecked()
        menu["icon_path"] = self.icon_path_edit.text().strip()
        menu["icon_managed"] = self.icon_managed and bool(menu["icon_path"])
        menu["icon_only"] = self.icon_only_check.isChecked()
        if self.top_level:
            style_values = self.current_style_values()
            style_values["use_custom_colors"] = bool(self.use_custom_check and self.use_custom_check.isChecked())
            menu["button_style"] = validate_button_style(style_values, self.global_style_values())
        return validate_menu(menu, top_level=self.top_level, button_fallbacks=self.button_fallbacks)
