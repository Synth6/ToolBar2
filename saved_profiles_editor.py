from __future__ import annotations

import copy
from pathlib import Path
from typing import Callable

from PyQt6 import QtCore, QtWidgets

from config_manager import (
    expand_profile_asset_paths,
    load_all_user_profile_data,
    default_config,
    new_profile_id,
    profile_json_from_runtime,
)
from menu_config_helpers import assign_new_ids_recursive


class ProfileListWidget(QtWidgets.QListWidget):
    zipDropped = QtCore.pyqtSignal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QtCore.QEvent) -> None:
        if self.zip_path_from_mime(event.mimeData()):
            self.setProperty("zipDragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QtCore.QEvent) -> None:
        if self.zip_path_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event: QtCore.QEvent) -> None:
        self.clear_zip_drag_highlight()
        event.accept()

    def dropEvent(self, event: QtCore.QEvent) -> None:
        path = self.zip_path_from_mime(event.mimeData())
        self.clear_zip_drag_highlight()
        if path:
            self.zipDropped.emit(path)
            event.acceptProposedAction()
            return
        event.ignore()

    def clear_zip_drag_highlight(self) -> None:
        self.setProperty("zipDragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def zip_path_from_mime(self, mime_data: QtCore.QMimeData) -> str:
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if Path(path).suffix.lower() == ".zip":
                return path
        return ""


class SavedProfilesEditorWidget(QtWidgets.QWidget):
    activeProfileChanged = QtCore.pyqtSignal(str)

    def __init__(
        self,
        config: dict,
        current_profile_callback: Callable[[str, str, str | None], dict],
        load_profile_callback: Callable[[dict], bool],
        import_profiles_callback: Callable[[str | None], None] | None = None,
        export_selected_callback: Callable[[str], None] | None = None,
        export_all_callback: Callable[[], None] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.active_profile_id = str(config.get("active_user_profile_id") or "")
        self._profiles, self._errors = load_all_user_profile_data()
        if not self._profiles:
            self._profiles = [profile_json_from_runtime(config, localize_assets=False)]
        self._deleted_ids: set[str] = set()
        self._dirty = False
        self.current_profile_callback = current_profile_callback
        self.load_profile_callback = load_profile_callback
        self.import_profiles_callback = import_profiles_callback
        self.export_selected_callback = export_selected_callback
        self.export_all_callback = export_all_callback
        self.loading_profile = False

        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel("Saved Toolbar Profiles")
        heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(heading)

        body = QtWidgets.QHBoxLayout()
        layout.addLayout(body, 1)

        left = QtWidgets.QVBoxLayout()
        self.profile_list = ProfileListWidget()
        self.profile_list.currentItemChanged.connect(self.on_selection_changed)
        self.profile_list.itemDoubleClicked.connect(lambda _item: self.activate_selected_profile())
        self.profile_list.zipDropped.connect(self.import_from_zip)
        self.profile_list.setStyleSheet(
            """
            QListWidget[zipDragActive="true"] {
                border: 2px solid palette(highlight);
                background-color: palette(alternate-base);
            }
            """
        )
        left.addWidget(self.profile_list, 1)

        list_buttons = QtWidgets.QHBoxLayout()
        self.new_button = QtWidgets.QPushButton("New")
        self.save_current_button = QtWidgets.QPushButton("Save Current As...")
        self.import_button = QtWidgets.QPushButton("Import...")
        self.export_selected_button = QtWidgets.QPushButton("Export Selected...")
        self.export_all_button = QtWidgets.QPushButton("Export All...")
        self.new_button.clicked.connect(self.new_profile)
        self.save_current_button.clicked.connect(self.save_current_as)
        self.import_button.clicked.connect(lambda _checked=False: self.import_from_zip(None))
        self.export_selected_button.clicked.connect(self.export_selected)
        self.export_all_button.clicked.connect(self.export_all)
        list_buttons.addWidget(self.new_button)
        list_buttons.addWidget(self.save_current_button)
        list_buttons.addWidget(self.import_button)
        list_buttons.addWidget(self.export_selected_button)
        list_buttons.addWidget(self.export_all_button)
        left.addLayout(list_buttons)
        body.addLayout(left, 1)

        right = QtWidgets.QVBoxLayout()
        form = QtWidgets.QFormLayout()
        self.name_edit = QtWidgets.QLineEdit()
        self.description_edit = QtWidgets.QPlainTextEdit()
        self.description_edit.setPlaceholderText("Optional")
        self.description_edit.setMaximumHeight(90)
        self.name_edit.editingFinished.connect(self.apply_name_edit)
        self.description_edit.textChanged.connect(self.apply_description_edit)
        form.addRow("Name", self.name_edit)
        form.addRow("Description", self.description_edit)
        right.addLayout(form)

        self.update_button = QtWidgets.QPushButton("Update From Current")
        self.load_button = QtWidgets.QPushButton("Load Into Current Toolbar")
        self.duplicate_button = QtWidgets.QPushButton("Duplicate")
        self.rename_button = QtWidgets.QPushButton("Rename")
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.update_button.clicked.connect(self.update_from_current)
        self.load_button.clicked.connect(self.load_into_current_toolbar)
        self.duplicate_button.clicked.connect(self.duplicate_profile)
        self.rename_button.clicked.connect(self.rename_profile)
        self.delete_button.clicked.connect(self.delete_profile)
        for button in (
            self.update_button,
            self.load_button,
            self.duplicate_button,
            self.rename_button,
            self.delete_button,
        ):
            right.addWidget(button)
        right.addStretch()
        body.addLayout(right, 2)

        self.refresh_profiles()

    def refresh_config(self, config: dict) -> None:
        selected_id = self.selected_profile_id()
        self.active_profile_id = str(config.get("active_user_profile_id") or "")
        self._profiles, self._errors = load_all_user_profile_data()
        if not self._profiles:
            self._profiles = [profile_json_from_runtime(config, localize_assets=False)]
        self._deleted_ids = set()
        self._dirty = False
        self.refresh_profiles(selected_id)

    def profiles(self) -> list[dict]:
        return self._profiles

    def current_profiles(self) -> list[dict]:
        self.apply_name_edit()
        self.apply_description_edit()
        return copy.deepcopy(self._profiles)

    def deleted_profile_ids(self) -> set[str]:
        return set(self._deleted_ids)

    def upsert_profile(self, profile: dict) -> None:
        profile_id = str(profile.get("profile_id") or "")
        for index, existing in enumerate(self._profiles):
            if str(existing.get("profile_id") or "") == profile_id:
                self._profiles[index] = copy.deepcopy(profile)
                self.mark_dirty()
                self.refresh_profiles(profile_id)
                return
        self._profiles.append(copy.deepcopy(profile))
        self.mark_dirty()
        self.refresh_profiles(profile_id)

    def set_active_profile(self, profile_id: str) -> None:
        self.active_profile_id = str(profile_id or "")
        self.refresh_profiles(self.active_profile_id)
        active = self.profile_by_id(self.active_profile_id)
        self.activeProfileChanged.emit(str(active.get("name") or "Default") if active else "Default")

    def profile_by_id(self, profile_id: str) -> dict | None:
        for profile in self.profiles():
            if str(profile.get("profile_id") or "") == str(profile_id or ""):
                return profile
        return None

    def has_unsaved_changes(self) -> bool:
        return self._dirty

    def mark_saved(self) -> None:
        self._dirty = False

    def mark_dirty(self) -> None:
        self._dirty = True

    def refresh_profiles(self, selected_id: str | None = None) -> None:
        self.loading_profile = True
        self.profile_list.clear()
        selected_row = -1
        for error in getattr(self, "_errors", []):
            item = QtWidgets.QListWidgetItem(error)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, "")
            item.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            self.profile_list.addItem(item)
        for row, profile in enumerate(self.profiles()):
            name = str(profile.get("name") or "Saved Toolbar Profile")
            if str(profile.get("profile_id") or "") == self.active_profile_id:
                name = f"{name} (Active)"
            item = QtWidgets.QListWidgetItem(name)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(profile.get("profile_id") or ""))
            self.profile_list.addItem(item)
            if selected_id and item.data(QtCore.Qt.ItemDataRole.UserRole) == selected_id:
                selected_row = row
        if selected_row >= 0:
            self.profile_list.setCurrentRow(selected_row)
        elif self.profile_list.count():
            self.profile_list.setCurrentRow(0)
        self.loading_profile = False
        self.populate_selected_profile()
        self.update_import_export_buttons()

    def selected_profile_id(self) -> str | None:
        item = self.profile_list.currentItem()
        if item is None:
            return None
        profile_id = str(item.data(QtCore.Qt.ItemDataRole.UserRole) or "")
        return profile_id or None

    def selected_profile(self) -> dict | None:
        profile_id = self.selected_profile_id()
        if not profile_id:
            return None
        for profile in self.profiles():
            if str(profile.get("profile_id") or "") == profile_id:
                return profile
        return None

    def on_selection_changed(self, *_args: object) -> None:
        if not self.loading_profile:
            self.populate_selected_profile()

    def populate_selected_profile(self) -> None:
        profile = self.selected_profile()
        has_profile = profile is not None
        self.loading_profile = True
        self.name_edit.setEnabled(has_profile)
        self.description_edit.setEnabled(has_profile)
        self.name_edit.setText(str(profile.get("name") or "") if profile else "")
        self.description_edit.setPlainText(str(profile.get("description") or "") if profile else "")
        self.loading_profile = False
        for button in (
            self.update_button,
            self.load_button,
            self.duplicate_button,
            self.rename_button,
            self.delete_button,
        ):
            button.setEnabled(has_profile)
        self.update_import_export_buttons()

    def update_import_export_buttons(self) -> None:
        has_profile = self.selected_profile() is not None
        if hasattr(self, "export_selected_button"):
            self.export_selected_button.setEnabled(has_profile)
        if hasattr(self, "export_all_button"):
            self.export_all_button.setEnabled(bool(self.profiles()))

    def import_from_zip(self, path: str | None) -> None:
        if self.import_profiles_callback is not None:
            self.import_profiles_callback(path)

    def export_selected(self) -> None:
        profile_id = self.selected_profile_id()
        if profile_id and self.export_selected_callback is not None:
            self.export_selected_callback(profile_id)

    def export_all(self) -> None:
        if self.export_all_callback is not None:
            self.export_all_callback()

    def add_imported_profiles(self, profiles: list[dict], selected_profile_id: str = "") -> None:
        for profile in profiles:
            self.profiles().append(copy.deepcopy(profile))
        self.mark_dirty()
        self.refresh_profiles(selected_profile_id or (str(profiles[0].get("profile_id") or "") if profiles else ""))

    def apply_imported_profiles(self, profiles: list[dict], selected_profile_id: str = "") -> None:
        for profile in profiles:
            profile_id = str(profile.get("profile_id") or "")
            replaced = False
            for index, existing in enumerate(self.profiles()):
                if str(existing.get("profile_id") or "") == profile_id:
                    self.profiles()[index] = copy.deepcopy(profile)
                    replaced = True
                    break
            if not replaced:
                self.profiles().append(copy.deepcopy(profile))
        self.mark_dirty()
        self.refresh_profiles(selected_profile_id or (str(profiles[0].get("profile_id") or "") if profiles else ""))

    def profile_name_exists(self, name: str, excluded_id: str | None = None) -> bool:
        normalized = name.strip().casefold()
        return any(
            str(profile.get("name") or "").strip().casefold() == normalized
            and str(profile.get("profile_id") or "") != str(excluded_id or "")
            for profile in self.profiles()
        )

    def require_unique_name(self, name: str, excluded_id: str | None = None) -> str | None:
        name = name.strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Saved Toolbar Profiles", "Profile names cannot be blank.")
            return None
        if self.profile_name_exists(name, excluded_id):
            QtWidgets.QMessageBox.warning(self, "Saved Toolbar Profiles", "Profile names must be unique.")
            return None
        return name

    def ask_profile_name(self, title: str, current: str = "", excluded_id: str | None = None) -> str | None:
        name, ok = QtWidgets.QInputDialog.getText(self, title, "Profile name:", text=current)
        if not ok:
            return None
        return self.require_unique_name(name, excluded_id)

    def new_profile(self) -> None:
        name = self.ask_profile_name("New Saved Toolbar Profile")
        if not name:
            return
        profile = profile_json_from_runtime(
            {
                **default_config(),
                "active_user_profile_id": new_profile_id(),
                "user_profile_name": name,
            },
            localize_assets=False,
        )
        profile["name"] = name
        self.profiles().append(profile)
        self.mark_dirty()
        self.refresh_profiles(profile["profile_id"])

    def save_current_as(self) -> None:
        name = self.ask_profile_name("Save Current Toolbar As")
        if not name:
            return
        profile = self.current_profile_callback(name, "", None)
        self.profiles().append(profile)
        self.mark_dirty()
        self.refresh_profiles(profile["profile_id"])

    def update_from_current(self) -> None:
        profile = self.selected_profile()
        if profile is None:
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Update Saved Toolbar Profile",
            f"Replace '{profile.get('name', 'Saved Toolbar Profile')}' with the current toolbar settings?",
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        updated = self.current_profile_callback(
            str(profile.get("name") or "Saved Toolbar Profile"),
            str(profile.get("description") or ""),
            str(profile.get("profile_id") or ""),
        )
        index = self.profiles().index(profile)
        self.profiles()[index] = updated
        self.mark_dirty()
        self.refresh_profiles(updated["profile_id"])

    def load_into_current_toolbar(self) -> None:
        self.activate_selected_profile()

    def activate_selected_profile(self) -> None:
        profile = self.selected_profile()
        if profile is None:
            return
        if self.active_profile_id:
            active = self.profile_by_id(self.active_profile_id)
            if active is not None:
                snapshot = self.current_profile_callback(
                    str(active.get("name") or "Default"),
                    str(active.get("description") or ""),
                    self.active_profile_id,
                )
                index = self.profiles().index(active)
                self.profiles()[index] = snapshot
                self.mark_dirty()
        selected_id = str(profile.get("profile_id") or "")
        if self.load_profile_callback(copy.deepcopy(profile)):
            self.set_active_profile(selected_id)

    def duplicate_profile(self) -> None:
        profile = self.selected_profile()
        if profile is None:
            return
        duplicate = copy.deepcopy(profile)
        expand_profile_asset_paths(duplicate)
        duplicate["profile_id"] = new_profile_id()
        duplicate["name"] = self.unique_copy_name(str(profile.get("name") or "Saved Toolbar Profile"))
        self.assign_new_profile_item_ids(duplicate)
        self.profiles().append(duplicate)
        self.mark_dirty()
        self.refresh_profiles(duplicate["profile_id"])

    def unique_copy_name(self, name: str) -> str:
        base = f"{name} Copy"
        candidate = base
        index = 2
        while self.profile_name_exists(candidate):
            candidate = f"{base} {index}"
            index += 1
        return candidate

    def assign_new_profile_item_ids(self, profile: dict) -> None:
        for menu in profile.get("menus", []):
            if isinstance(menu, dict):
                assign_new_ids_recursive(menu)
        logo = profile.get("logo", {})
        if isinstance(logo, dict):
            launcher = logo.get("left_click_launcher")
            if isinstance(launcher, dict):
                assign_new_ids_recursive(launcher)
            for item in logo.get("menu_items", []):
                if isinstance(item, dict):
                    assign_new_ids_recursive(item)

    def rename_profile(self) -> None:
        profile = self.selected_profile()
        if profile is None:
            return
        name = self.ask_profile_name(
            "Rename Saved Toolbar Profile",
            str(profile.get("name") or ""),
            str(profile.get("profile_id") or ""),
        )
        if not name:
            return
        profile["name"] = name
        self.mark_dirty()
        if str(profile.get("profile_id") or "") == self.active_profile_id:
            self.activeProfileChanged.emit(name)
        self.refresh_profiles(str(profile.get("profile_id") or ""))

    def apply_name_edit(self) -> None:
        if self.loading_profile:
            return
        profile = self.selected_profile()
        if profile is None:
            return
        old_name = str(profile.get("name") or "")
        name = self.require_unique_name(self.name_edit.text(), str(profile.get("profile_id") or ""))
        if not name:
            self.name_edit.setText(old_name)
            return
        if profile.get("name") == name:
            return
        profile["name"] = name
        self.mark_dirty()
        if str(profile.get("profile_id") or "") == self.active_profile_id:
            self.activeProfileChanged.emit(name)
        item = self.profile_list.currentItem()
        if item is not None:
            item.setText(name)

    def apply_description_edit(self) -> None:
        if self.loading_profile:
            return
        profile = self.selected_profile()
        if profile is not None:
            description = self.description_edit.toPlainText()
            if profile.get("description") != description:
                profile["description"] = description
                self.mark_dirty()

    def delete_profile(self) -> None:
        profile = self.selected_profile()
        if profile is None:
            return
        if len(self.profiles()) <= 1:
            QtWidgets.QMessageBox.warning(self, "Saved Toolbar Profiles", "At least one saved toolbar profile is required.")
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Delete Saved Toolbar Profile",
            f"Delete '{profile.get('name', 'Saved Toolbar Profile')}'?",
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        profile_id = str(profile.get("profile_id") or "")
        if profile_id:
            self._deleted_ids.add(profile_id)
        self.profiles().remove(profile)
        self.mark_dirty()
        self.refresh_profiles()
