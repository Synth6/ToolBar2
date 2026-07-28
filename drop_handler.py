from __future__ import annotations

import copy
import uuid
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from app_icon import apply_window_icon
from target_detection import detect_target


def extract_targets_from_mime_data(mime_data: QtCore.QMimeData) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()

    for url in mime_data.urls():
        target = url.toLocalFile() if url.isLocalFile() else url.toString()
        add_unique_target(target, targets, seen)

    if not targets and mime_data.hasText():
        text = mime_data.text().strip()
        if text.lower().startswith(("http://", "https://")):
            add_unique_target(text, targets, seen)

    return targets


def extract_local_paths_from_mime_data(mime_data: QtCore.QMimeData) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for url in mime_data.urls():
        if url.isLocalFile():
            add_unique_target(url.toLocalFile(), paths, seen)
    return paths


def add_unique_target(target: str, targets: list[str], seen: set[str]) -> None:
    cleaned = target.strip()
    if not cleaned:
        return
    key = cleaned.casefold()
    if key in seen:
        return
    seen.add(key)
    targets.append(cleaned)


class DroppedItemsDialog(QtWidgets.QDialog):
    def __init__(
        self,
        paths: list[str],
        destinations: list[dict],
        preselected_path: list[int] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.destinations = destinations
        self.setWindowTitle("Add Dropped Items")
        apply_window_icon(self)
        self.resize(860, 420)

        layout = QtWidgets.QVBoxLayout(self)
        destination_row = QtWidgets.QHBoxLayout()
        destination_row.addWidget(QtWidgets.QLabel("Destination"))
        self.destination_combo = QtWidgets.QComboBox()
        for destination in destinations:
            self.destination_combo.addItem(str(destination.get("label") or "Menu"), copy.deepcopy(destination))
        self.destination_combo.setEnabled(bool(destinations))
        if preselected_path is not None:
            index = self.find_destination_index_for_path(self.destination_combo, preselected_path)
            if index >= 0:
                self.destination_combo.setCurrentIndex(index)
        destination_row.addWidget(self.destination_combo, 1)
        layout.addLayout(destination_row)

        self.apply_destination_to_all_check = QtWidgets.QCheckBox("Apply this destination to all rows")
        self.apply_destination_to_all_check.setEnabled(bool(destinations))
        layout.addWidget(self.apply_destination_to_all_check)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Display name", "Target", "Detected type", "Add as", "Destination menu", "Enabled"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        for path in paths:
            self.add_path(path)

        buttons = QtWidgets.QHBoxLayout()
        self.remove_button = QtWidgets.QPushButton("Remove Selected")
        self.add_all_button = QtWidgets.QPushButton("Add All")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.remove_button.clicked.connect(self.remove_selected)
        self.add_all_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.remove_button)
        buttons.addStretch()
        buttons.addWidget(self.add_all_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

    def add_path(self, path: str) -> None:
        detected = detect_target(path)
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [detected["name"], detected["target"], detected["target_type"], "", "", "true"]
        for column, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem("" if column in {3, 4, 5} else value)
            if column == 1:
                item.setData(QtCore.Qt.ItemDataRole.UserRole, str(detected.get("arguments", "")))
                item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, str(detected.get("working_directory", "")))
            if column == 5:
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.CheckState.Checked)
            self.table.setItem(row, column, item)

        add_as_combo = QtWidgets.QComboBox()
        if self.destinations:
            add_as_combo.addItem("Add to Existing Menu", "existing_menu")
        add_as_combo.addItem("Add as Top-Level Launcher", "top_level")
        if self.can_add_as_folder_menu(detected):
            add_as_combo.addItem("Add as Folder Menu", "top_level_folder_menu")
        add_as_combo.currentIndexChanged.connect(lambda _index, widget=add_as_combo: self.update_destination_combo_state(self.row_for_widget(widget)))
        self.table.setCellWidget(row, 3, add_as_combo)

        destination_combo = QtWidgets.QComboBox()
        self.populate_destination_combo(destination_combo)
        destination_combo.currentIndexChanged.connect(lambda _index, widget=destination_combo: self.apply_destination_to_all(self.row_for_widget(widget)))
        self.table.setCellWidget(row, 4, destination_combo)
        self.update_destination_combo_state(row)

    def can_add_as_folder_menu(self, detected: dict) -> bool:
        target_type = str(detected.get("target_type") or "").strip()
        if target_type != "Folder":
            return False
        target = str(detected.get("target") or "").strip()
        return bool(target) and Path(target).is_dir()

    def row_for_widget(self, widget: QtWidgets.QWidget) -> int:
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 3) is widget or self.table.cellWidget(row, 4) is widget:
                return row
        return -1

    def populate_destination_combo(self, combo: QtWidgets.QComboBox) -> None:
        for destination in self.destinations:
            combo.addItem(str(destination.get("label") or "Menu"), copy.deepcopy(destination))
        main_destination = self.destination_combo.currentData()
        if isinstance(main_destination, dict):
            index = self.find_destination_index_for_path(combo, main_destination.get("path"))
            if index >= 0:
                combo.setCurrentIndex(index)

    def find_destination_index_for_path(self, combo: QtWidgets.QComboBox, path: object) -> int:
        if not isinstance(path, list):
            return -1
        for index in range(combo.count()):
            data = combo.itemData(index)
            if isinstance(data, dict) and data.get("path") == path:
                return index
        return -1

    def add_mode_for_row(self, row: int) -> str:
        widget = self.table.cellWidget(row, 3)
        if isinstance(widget, QtWidgets.QComboBox):
            return str(widget.currentData() or "")
        return ""

    def destination_combo_for_row(self, row: int) -> QtWidgets.QComboBox | None:
        widget = self.table.cellWidget(row, 4)
        return widget if isinstance(widget, QtWidgets.QComboBox) else None

    def update_destination_combo_state(self, row: int) -> None:
        if row < 0:
            return
        combo = self.destination_combo_for_row(row)
        if combo is None:
            return
        use_existing_menu = self.add_mode_for_row(row) == "existing_menu"
        combo.setEnabled(use_existing_menu and bool(self.destinations))
        if not use_existing_menu:
            combo.setCurrentIndex(-1)
            return
        if combo.currentIndex() < 0 and combo.count():
            main_destination = self.destination_combo.currentData()
            if isinstance(main_destination, dict):
                index = self.find_destination_index_for_path(combo, main_destination.get("path"))
                if index >= 0:
                    combo.setCurrentIndex(index)
            if combo.currentIndex() < 0:
                combo.setCurrentIndex(0)

    def apply_destination_to_all(self, source_row: int) -> None:
        if source_row < 0:
            return
        if not self.apply_destination_to_all_check.isChecked():
            return
        source_combo = self.destination_combo_for_row(source_row)
        if source_combo is None or self.add_mode_for_row(source_row) != "existing_menu":
            return
        source_data = source_combo.currentData()
        if not isinstance(source_data, dict):
            return
        for row in range(self.table.rowCount()):
            if row == source_row or self.add_mode_for_row(row) != "existing_menu":
                continue
            combo = self.destination_combo_for_row(row)
            if combo is None:
                continue
            index = self.find_destination_index_for_path(combo, source_data.get("path"))
            if index >= 0:
                previous = combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(previous)

    def remove_selected(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def accept(self) -> None:
        for row in range(self.table.rowCount()):
            if self.add_mode_for_row(row) != "existing_menu":
                continue
            combo = self.destination_combo_for_row(row)
            destination = combo.currentData() if combo is not None else None
            if not isinstance(destination, dict) or not isinstance(destination.get("path"), list):
                QtWidgets.QMessageBox.warning(
                    self,
                    "Invalid Destination",
                    "Choose a destination menu for every item added to an existing menu.",
                )
                return
        super().accept()

    def result_items(self) -> list[dict]:
        results: list[dict] = []
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text().strip() or "Launcher"
            target_item = self.table.item(row, 1)
            target = target_item.text().strip()
            arguments = str(target_item.data(QtCore.Qt.ItemDataRole.UserRole) or "")
            working_directory = str(target_item.data(QtCore.Qt.ItemDataRole.UserRole + 1) or "")
            target_type = self.table.item(row, 2).text().strip() or "Auto Detect"
            enabled_item = self.table.item(row, 5)
            enabled = enabled_item.checkState() == QtCore.Qt.CheckState.Checked
            add_mode = self.add_mode_for_row(row)
            top_level = add_mode in {"top_level", "top_level_folder_menu"}
            if add_mode == "top_level_folder_menu":
                item = {
                    "name": name or Path(target).name or "Folder",
                    "type": "folder_menu",
                    "id": str(uuid.uuid4()),
                    "folder_path": target,
                    "include_files": True,
                    "include_folders": True,
                    "show_open_folder_action": True,
                    "enabled": enabled,
                }
            else:
                item_type = "top_launcher" if top_level else "launcher"
                item = {
                    "name": name or Path(target).name or "Launcher",
                    "type": item_type,
                    "target": target,
                    "target_type": target_type,
                    "arguments": arguments,
                    "working_directory": working_directory,
                    "python_mode": "Automatic",
                    "enabled": enabled,
                    "accept_dropped_files": False,
                }
            if top_level:
                item["icon_path"] = ""
                item["icon_only"] = False
                destination_path = None
                destination_id = ""
            else:
                item["icon"] = ""
                destination_combo = self.destination_combo_for_row(row)
                destination = destination_combo.currentData() if destination_combo is not None else None
                destination_path = copy.deepcopy(destination.get("path")) if isinstance(destination, dict) else None
                destination_id = str(destination.get("id") or "") if isinstance(destination, dict) else ""
            results.append(
                {
                    "item": item,
                    "add_mode": add_mode if top_level else "existing_menu",
                    "destination_path": destination_path,
                    "destination_id": destination_id,
                }
            )
        return results
