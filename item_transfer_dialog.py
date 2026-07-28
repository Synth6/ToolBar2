from __future__ import annotations

from typing import Callable

from PyQt6 import QtCore, QtWidgets

from app_icon import apply_window_icon
from toolbar_item_transfer import ToolbarRef, TransferDestination


class ItemTransferDialog(QtWidgets.QDialog):
    def __init__(
        self,
        mode: str,
        source_profile: str,
        source_toolbar: str,
        source_item: str,
        source_toolbar_key: tuple[str, str],
        toolbar_provider: Callable[[str], list[ToolbarRef]],
        container_provider: Callable[[ToolbarRef], list[tuple[str, list[int]]]],
        position_provider: Callable[[ToolbarRef, list[int] | None], list[tuple[str, str, list[int] | None]]],
        profiles: list[tuple[str, str]],
        top_level: bool,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mode = mode
        self.source_toolbar_key = source_toolbar_key
        self.toolbar_provider = toolbar_provider
        self.container_provider = container_provider
        self.position_provider = position_provider
        self.top_level = top_level
        self.toolbar_refs: list[ToolbarRef] = []

        self.setWindowTitle("Copy To..." if mode == "copy" else "Move To...")
        apply_window_icon(self)
        self.resize(760, 520)

        layout = QtWidgets.QVBoxLayout(self)
        source_group = QtWidgets.QGroupBox("Source")
        source_layout = QtWidgets.QFormLayout(source_group)
        source_layout.addRow("Profile", QtWidgets.QLabel(source_profile))
        source_layout.addRow("Toolbar", QtWidgets.QLabel(source_toolbar))
        source_layout.addRow("Item", QtWidgets.QLabel(source_item))
        layout.addWidget(source_group)

        destination_group = QtWidgets.QGroupBox("Destination")
        destination_layout = QtWidgets.QFormLayout(destination_group)
        self.profile_combo = QtWidgets.QComboBox()
        for name, profile_id in profiles:
            self.profile_combo.addItem(name, profile_id)
        self.profile_combo.currentIndexChanged.connect(self.refresh_toolbars)
        destination_layout.addRow("Destination Profile", self.profile_combo)

        self.toolbar_list = QtWidgets.QListWidget()
        self.toolbar_list.itemChanged.connect(lambda _item: self.refresh_location_controls())
        self.toolbar_list.currentItemChanged.connect(lambda *_args: self.refresh_location_controls())
        self.toolbar_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        destination_layout.addRow("Destination Toolbar", self.toolbar_list)

        self.container_combo = QtWidgets.QComboBox()
        self.container_combo.currentIndexChanged.connect(self.refresh_positions)
        if not top_level:
            destination_layout.addRow("Destination menu", self.container_combo)

        self.position_combo = QtWidgets.QComboBox()
        destination_layout.addRow("Position", self.position_combo)
        layout.addWidget(destination_group, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh_toolbars()

    def refresh_toolbars(self) -> None:
        profile_id = str(self.profile_combo.currentData() or "")
        self.toolbar_refs = self.toolbar_provider(profile_id)
        self.toolbar_list.clear()
        for ref in self.toolbar_refs:
            item = QtWidgets.QListWidgetItem(ref.toolbar_label)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, ref)
            selectable = (ref.profile_id, ref.toolbar_key) != self.source_toolbar_key
            if self.mode == "copy":
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.CheckState.Unchecked)
            item.setFlags(item.flags() if selectable else QtCore.Qt.ItemFlag.NoItemFlags)
            self.toolbar_list.addItem(item)
        if self.mode == "move":
            for index in range(self.toolbar_list.count()):
                item = self.toolbar_list.item(index)
                if item.flags() != QtCore.Qt.ItemFlag.NoItemFlags:
                    self.toolbar_list.setCurrentRow(index)
                    break
        self.refresh_location_controls()

    def selected_toolbar_refs(self) -> list[ToolbarRef]:
        refs: list[ToolbarRef] = []
        if self.mode == "move":
            item = self.toolbar_list.currentItem()
            ref = item.data(QtCore.Qt.ItemDataRole.UserRole) if item is not None else None
            return [ref] if isinstance(ref, ToolbarRef) else []
        for index in range(self.toolbar_list.count()):
            item = self.toolbar_list.item(index)
            ref = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if isinstance(ref, ToolbarRef) and item.checkState() == QtCore.Qt.CheckState.Checked:
                refs.append(ref)
        return refs

    def active_toolbar_ref(self) -> ToolbarRef | None:
        refs = self.selected_toolbar_refs()
        if refs:
            return refs[0]
        item = self.toolbar_list.currentItem()
        ref = item.data(QtCore.Qt.ItemDataRole.UserRole) if item is not None else None
        return ref if isinstance(ref, ToolbarRef) else None

    def refresh_location_controls(self) -> None:
        ref = self.active_toolbar_ref()
        self.container_combo.clear()
        if ref is not None and not self.top_level:
            for label, path in self.container_provider(ref):
                self.container_combo.addItem(label, path)
        self.refresh_positions()

    def refresh_positions(self) -> None:
        ref = self.active_toolbar_ref()
        container_path = None if self.top_level else self.container_combo.currentData()
        self.position_combo.clear()
        if ref is None:
            return
        for label, position, sibling_path in self.position_provider(ref, container_path):
            self.position_combo.addItem(label, (position, sibling_path))

    def accept(self) -> None:
        if not self.selected_toolbar_refs():
            QtWidgets.QMessageBox.warning(self, self.windowTitle(), "Choose a destination toolbar.")
            return
        if not self.top_level and self.active_toolbar_ref() is not None and self.container_combo.currentData() is None:
            QtWidgets.QMessageBox.warning(self, self.windowTitle(), "Choose a destination menu.")
            return
        super().accept()

    def destinations(self) -> list[TransferDestination]:
        container_path = None if self.top_level else self.container_combo.currentData()
        position_data = self.position_combo.currentData()
        position, sibling_path = position_data if isinstance(position_data, tuple) else ("end", None)
        return [
            TransferDestination(ref, container_path, position, sibling_path)
            for ref in self.selected_toolbar_refs()
        ]
