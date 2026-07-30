from __future__ import annotations

import copy
from typing import Callable

from PyQt6 import QtCore, QtGui, QtWidgets

from config_manager import validate_item
from drop_handler import DroppedItemsDialog, extract_targets_from_mime_data
from icon_utilities import icon_for_item
from launcher_editor import LauncherEditorDialog
from icon_utilities import AssetContext
from menu_config_helpers import assign_new_ids_recursive


class NestedItemTree(QtWidgets.QTreeWidget):
    def __init__(self, editor: "NestedItemEditorWidget") -> None:
        super().__init__(editor)
        self.editor = editor
        self.setHeaderHidden(True)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.source() is self:
            super().dragEnterEvent(event)
            return
        if extract_targets_from_mime_data(event.mimeData()):
            event.setDropAction(QtCore.Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.source() is self:
            super().dragMoveEvent(event)
            return
        if extract_targets_from_mime_data(event.mimeData()):
            event.setDropAction(QtCore.Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        if event.source() is not self:
            self.editor.handle_external_drop(event)
            return
        before = copy.deepcopy(self.editor.items)
        super().dropEvent(event)
        if self.editor.tree_is_valid():
            self.editor.sync_items_from_tree()
            event.accept()
            return
        self.editor.items = before
        self.editor.populate_tree()
        event.ignore()
        QtWidgets.QMessageBox.warning(self, "Invalid Move", "That item cannot be moved to that location.")


class NestedItemEditorWidget(QtWidgets.QWidget):
    configurationChanged = QtCore.pyqtSignal()

    def __init__(
        self,
        items: list[dict],
        parent: QtWidgets.QWidget | None = None,
        profile_id: str | None = None,
        add_button_in_layout: bool = True,
        asset_context: AssetContext | None = None,
        transfer_callback: Callable[[str, list[int], dict], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.items = [validate_item(item) for item in items if isinstance(item, dict)]
        self.profile_id = profile_id
        self.asset_context = asset_context
        self.transfer_callback = transfer_callback
        self.loading_items = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.tree = NestedItemTree(self)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.currentItemChanged.connect(self.update_buttons)
        self.tree.itemDoubleClicked.connect(lambda item, column: self.edit_selected())
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        layout.addWidget(self.tree, 1)

        self.add_item_button = QtWidgets.QPushButton("Add Item...")
        self.add_item_menu = QtWidgets.QMenu(self.add_item_button)
        self.add_item_menu.addAction("Launcher", self.add_launcher)
        self.add_item_menu.addAction("Submenu", self.add_submenu)
        self.add_item_menu.addAction("Heading", self.add_heading)
        self.add_item_menu.addAction("Separator", self.add_separator)
        self.add_item_button.setMenu(self.add_item_menu)
        if add_button_in_layout:
            layout.addWidget(self.add_item_button, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        self.add_shortcut(QtCore.Qt.Key.Key_F2, self.rename_selected)
        self.add_shortcut(QtCore.Qt.Key.Key_Delete, self.delete_selected)
        self.add_shortcut(QtGui.QKeySequence("Ctrl+D"), self.duplicate_selected)
        self.populate_tree()

    def button(self, text: str, callback) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.clicked.connect(callback)
        return button

    def add_shortcut(self, key, callback) -> None:
        shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self.tree)
        shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(callback)

    def populate_tree(self) -> None:
        self.loading_items = True
        self.tree.clear()
        try:
            for item in self.items:
                self.add_tree_item(None, item)
            self.update_buttons()
        finally:
            self.loading_items = False

    def add_tree_item(self, parent: QtWidgets.QTreeWidgetItem | None, data: dict) -> QtWidgets.QTreeWidgetItem:
        tree_item = QtWidgets.QTreeWidgetItem([self.item_label(data)])
        tree_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, copy.deepcopy(data))
        tree_item.setIcon(0, icon_for_item(data, self))
        tree_item.setFlags(tree_item.flags() | QtCore.Qt.ItemFlag.ItemIsDragEnabled | QtCore.Qt.ItemFlag.ItemIsDropEnabled)
        if data.get("type") != "submenu":
            tree_item.setFlags(tree_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsDropEnabled)
        if parent is None:
            self.tree.addTopLevelItem(tree_item)
        else:
            parent.addChild(tree_item)
        for child in data.get("items", []):
            self.add_tree_item(tree_item, child)
        tree_item.setExpanded(True)
        return tree_item

    def item_label(self, data: dict) -> str:
        if data.get("type") == "separator":
            return "----------"
        return data.get("name", "Item")

    def selected_item(self) -> QtWidgets.QTreeWidgetItem | None:
        return self.tree.currentItem()

    def item_data(self, item: QtWidgets.QTreeWidgetItem) -> dict:
        return item.data(0, QtCore.Qt.ItemDataRole.UserRole)

    def selected_container(self) -> QtWidgets.QTreeWidgetItem | None:
        item = self.selected_item()
        if item is None:
            return None
        if self.item_data(item).get("type") == "submenu":
            return item
        return item.parent()

    def update_buttons(self) -> None:
        self.add_item_button.setEnabled(True)

    def show_tree_context_menu(self, position: QtCore.QPoint) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        menu = QtWidgets.QMenu(self)

        if self.can_edit(item):
            menu.addAction("Edit", self.edit_selected)
        if self.can_rename(item):
            menu.addAction("Rename", self.rename_selected)

        if not menu.isEmpty():
            menu.addSeparator()
        menu.addAction("Add Launcher", self.add_launcher)
        menu.addAction("Add Submenu", self.add_submenu)
        menu.addAction("Add Heading", self.add_heading)
        menu.addAction("Add Separator", self.add_separator)

        if self.can_duplicate(item):
            menu.addSeparator()
            menu.addAction("Duplicate", self.duplicate_selected)
            if self.transfer_callback is not None:
                menu.addAction("Copy To...", lambda: self.transfer_selected("copy"))
                menu.addAction("Move To...", lambda: self.transfer_selected("move"))

        move_actions = [
            ("Move Up", self.can_move_up(item), lambda: self.move_selected(-1)),
            ("Move Down", self.can_move_down(item), lambda: self.move_selected(1)),
            ("Move Left", self.can_move_left(item), self.move_left),
            ("Move Right", self.can_move_right(item), self.move_right),
        ]
        valid_moves = [action for action in move_actions if action[1]]
        if valid_moves:
            menu.addSeparator()
            for text, _enabled, callback in valid_moves:
                menu.addAction(text, callback)

        if self.can_delete(item):
            menu.addSeparator()
            menu.addAction("Delete", self.delete_selected)

        menu.exec(self.tree.viewport().mapToGlobal(position))

    def can_edit(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        return item is not None and self.item_data(item).get("type") == "launcher"

    def can_rename(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        return item is not None and self.item_data(item).get("type") in {"launcher", "submenu", "heading"}

    def can_duplicate(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        return item is not None

    def can_delete(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        return item is not None

    def sibling_index(self, item: QtWidgets.QTreeWidgetItem | None) -> int:
        if item is None:
            return -1
        parent = item.parent()
        return self.tree.indexOfTopLevelItem(item) if parent is None else parent.indexOfChild(item)

    def sibling_count(self, item: QtWidgets.QTreeWidgetItem | None) -> int:
        if item is None:
            return 0
        parent = item.parent()
        return self.tree.topLevelItemCount() if parent is None else parent.childCount()

    def can_move_up(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        return self.sibling_index(item) > 0

    def can_move_down(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        index = self.sibling_index(item)
        return item is not None and 0 <= index < self.sibling_count(item) - 1

    def can_move_left(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        return item is not None and item.parent() is not None

    def can_move_right(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        index = self.sibling_index(item)
        if item is None or index <= 0:
            return False
        parent = item.parent()
        target = self.tree.topLevelItem(index - 1) if parent is None else parent.child(index - 1)
        return self.item_data(target).get("type") == "submenu"

    def add_to_container(self, data: dict, container: QtWidgets.QTreeWidgetItem | None = None) -> None:
        if container is None:
            self.items.append(data)
            child = self.add_tree_item(None, data)
        else:
            container_data = self.item_data(container)
            container_data.setdefault("items", []).append(data)
            child = self.add_tree_item(container, data)
            container.setExpanded(True)
        self.tree.setCurrentItem(child)
        self.sync_items_from_tree()

    def add_launcher(self) -> None:
        dialog = LauncherEditorDialog(
            {"type": "launcher", "name": "New Launcher"},
            self,
            profile_id=self.profile_id,
            asset_context=self.asset_context,
        )
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.add_to_container(dialog.result_item(), self.selected_container())

    def add_submenu(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "Add Submenu", "Submenu name:")
        if ok:
            self.add_to_container(validate_item({"type": "submenu", "name": name.strip() or "Submenu", "items": []}), self.selected_container())

    def add_separator(self) -> None:
        self.add_to_container({"type": "separator"}, self.selected_container())

    def add_heading(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "Add Heading", "Heading text:")
        if ok:
            self.add_to_container(validate_item({"type": "heading", "name": name.strip() or "Heading"}), self.selected_container())

    def edit_selected(self) -> None:
        item = self.selected_item()
        if item is None or self.item_data(item).get("type") != "launcher":
            return
        dialog = LauncherEditorDialog(self.item_data(item), self, profile_id=self.profile_id, asset_context=self.asset_context)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            updated = dialog.result_item()
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, updated)
            item.setText(0, self.item_label(updated))
            item.setIcon(0, icon_for_item(updated, self))
            self.sync_items_from_tree()

    def rename_selected(self) -> None:
        item = self.selected_item()
        if item is None or self.item_data(item).get("type") == "separator":
            return
        data = self.item_data(item)
        name, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=data.get("name", ""))
        if ok:
            data["name"] = name.strip() or self.item_label(data)
            item.setText(0, self.item_label(data))
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, data)
            self.sync_items_from_tree()

    def duplicate_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        data = copy.deepcopy(self.item_data(item))
        assign_new_ids_recursive(data)
        if "name" in data:
            data["name"] = f"{data['name']} Copy"
        parent = item.parent()
        clone = self.add_tree_item(parent, data)
        if parent is None:
            old = self.tree.indexOfTopLevelItem(clone)
            self.tree.insertTopLevelItem(self.tree.indexOfTopLevelItem(item) + 1, self.tree.takeTopLevelItem(old))
        else:
            old = parent.indexOfChild(clone)
            parent.insertChild(parent.indexOfChild(item) + 1, parent.takeChild(old))
        self.tree.setCurrentItem(clone)
        self.sync_items_from_tree()

    def transfer_selected(self, mode: str) -> None:
        item = self.selected_item()
        if item is None or self.transfer_callback is None:
            return
        self.sync_items_from_tree()
        self.transfer_callback(
            mode,
            self.config_path_for_item(item),
            copy.deepcopy(self.item_data(item)),
        )

    def delete_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        parent = item.parent()
        if parent is None:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        else:
            parent.takeChild(parent.indexOfChild(item))
        self.sync_items_from_tree()

    def move_selected(self, offset: int) -> None:
        item = self.selected_item()
        if item is None:
            return
        parent = item.parent()
        count = self.tree.topLevelItemCount() if parent is None else parent.childCount()
        index = self.tree.indexOfTopLevelItem(item) if parent is None else parent.indexOfChild(item)
        new_index = index + offset
        if not 0 <= new_index < count:
            return
        moved = self.tree.takeTopLevelItem(index) if parent is None else parent.takeChild(index)
        if parent is None:
            self.tree.insertTopLevelItem(new_index, moved)
        else:
            parent.insertChild(new_index, moved)
        self.tree.setCurrentItem(moved)
        self.sync_items_from_tree()

    def move_right(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        parent = item.parent()
        index = self.tree.indexOfTopLevelItem(item) if parent is None else parent.indexOfChild(item)
        if index <= 0:
            return
        target = self.tree.topLevelItem(index - 1) if parent is None else parent.child(index - 1)
        if self.item_data(target).get("type") != "submenu":
            return
        moved = self.tree.takeTopLevelItem(index) if parent is None else parent.takeChild(index)
        target.addChild(moved)
        target.setExpanded(True)
        self.tree.setCurrentItem(moved)
        self.sync_items_from_tree()

    def move_left(self) -> None:
        item = self.selected_item()
        if item is None or item.parent() is None:
            return
        parent = item.parent()
        grandparent = parent.parent()
        moved = parent.takeChild(parent.indexOfChild(item))
        if grandparent is None:
            self.tree.insertTopLevelItem(self.tree.indexOfTopLevelItem(parent) + 1, moved)
        else:
            grandparent.insertChild(grandparent.indexOfChild(parent) + 1, moved)
        self.tree.setCurrentItem(moved)
        self.sync_items_from_tree()

    def tree_is_valid(self) -> bool:
        for index in range(self.tree.topLevelItemCount()):
            if not self.children_are_valid(self.tree.topLevelItem(index)):
                return False
        return True

    def children_are_valid(self, parent: QtWidgets.QTreeWidgetItem) -> bool:
        if self.item_data(parent).get("type") != "submenu" and parent.childCount():
            return False
        for index in range(parent.childCount()):
            if not self.children_are_valid(parent.child(index)):
                return False
        return True

    def destination_paths(self) -> list[dict]:
        destinations = [
            {
                "label": "Logo Menu",
                "path": [],
                "id": "logo_menu",
            }
        ]

        for index in range(self.tree.topLevelItemCount()):
            self.collect_destinations(
                self.tree.topLevelItem(index),
                [index],
                destinations,
            )

        return destinations

    def collect_destinations(
        self,
        item: QtWidgets.QTreeWidgetItem,
        path: list[int],
        destinations: list[dict],
    ) -> None:
        data = self.item_data(item)

        if data.get("type") != "submenu":
            return

        label = "Logo Menu > " + " > ".join(self.names_for_path(path))

        destinations.append(
            {
                "label": label,
                "path": path.copy(),
                "id": str(data.get("id") or ""),
            }
        )

        for index in range(item.childCount()):
            self.collect_destinations(
                item.child(index),
                [*path, index],
                destinations,
            )

    def names_for_path(self, path: list[int]) -> list[str]:
        names = []
        item = self.tree.topLevelItem(path[0])
        names.append(self.item_data(item).get("name", "Submenu"))
        for index in path[1:]:
            item = item.child(index)
            names.append(self.item_data(item).get("name", "Submenu"))
        return names

    def item_at_path(self, path: list[int]) -> QtWidgets.QTreeWidgetItem | None:
        if not path:
            return None
        item = self.tree.topLevelItem(path[0])
        for index in path[1:]:
            if item is None:
                return None
            item = item.child(index)
        return item

    def handle_external_drop(self, event: QtGui.QDropEvent) -> None:
        targets = extract_targets_from_mime_data(event.mimeData())
        if not targets:
            event.ignore()
            return

        item = self.tree.itemAt(event.position().toPoint())
        destination_path: list[int] | None = None

        if item is not None:
            destination = (
                item
                if self.item_data(item).get("type") == "submenu"
                else item.parent()
            )
            destination_path = (
                self.config_path_for_item(destination)
                if destination is not None
                else []
            )

        dialog = DroppedItemsDialog(
            targets,
            self.destination_paths(),
            destination_path,
            self,
        )

        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            event.ignore()
            return

        results = dialog.result_items()
        last_destination_path: list[int] = []

        for result in results:
            dropped_item = result.get("item")
            if not isinstance(dropped_item, dict):
                continue

            item_destination = result.get("destination_path")
            if not isinstance(item_destination, list):
                item_destination = []

            # Logo Menu items must always be nested launchers,
            # never toolbar top-level launchers.
            if dropped_item.get("type") == "top_launcher":
                dropped_item["type"] = "launcher"
                dropped_item.pop("icon_path", None)
                dropped_item.pop("icon_only", None)
                dropped_item.setdefault("icon", "")

            self.insert_item_at_path(
                item_destination,
                validate_item(dropped_item),
            )
            last_destination_path = item_destination

        self.populate_tree()
        self.select_last_inserted_item(last_destination_path)
        self.notify_changed()

        event.setDropAction(QtCore.Qt.DropAction.CopyAction)
        event.accept()

    def config_path_for_item(self, item: QtWidgets.QTreeWidgetItem | None) -> list[int]:
        if item is None:
            return []
        path = []
        current = item
        while current.parent() is not None:
            parent = current.parent()
            path.insert(0, parent.indexOfChild(current))
            current = parent
        path.insert(0, self.tree.indexOfTopLevelItem(current))
        return path

    def insert_item_at_path(self, path: list[int], data: dict) -> None:
        self.sync_items_from_tree()
        if not path:
            self.items.append(data)
            return
        target_data = self.data_at_path(path)
        if target_data is None or target_data.get("type") != "submenu":
            self.items.append(data)
            return
        target_data.setdefault("items", []).append(data)

    def select_last_inserted_item(self, path: list[int]) -> None:
        if not path:
            if self.tree.topLevelItemCount():
                self.tree.setCurrentItem(self.tree.topLevelItem(self.tree.topLevelItemCount() - 1))
            return
        parent = self.item_at_path(path)
        if parent is not None and parent.childCount():
            parent.setExpanded(True)
            self.tree.setCurrentItem(parent.child(parent.childCount() - 1))

    def data_at_path(self, path: list[int]) -> dict | None:
        if not path:
            return None
        try:
            item = self.items[path[0]]
            for index in path[1:]:
                item = item["items"][index]
            return item
        except (IndexError, KeyError, TypeError):
            return None

    def sync_items_from_tree(self) -> None:
        self.items = [self.item_to_data(self.tree.topLevelItem(index)) for index in range(self.tree.topLevelItemCount())]
        self.notify_changed()

    def notify_changed(self) -> None:
        if not self.loading_items:
            self.configurationChanged.emit()

    def item_to_data(self, item: QtWidgets.QTreeWidgetItem) -> dict:
        data = copy.deepcopy(self.item_data(item))
        if data.get("type") == "submenu":
            data["items"] = [self.item_to_data(item.child(index)) for index in range(item.childCount())]
        return data

    def current_items(self) -> list[dict]:
        was_loading = self.loading_items
        self.loading_items = True
        try:
            self.sync_items_from_tree()
            return [validate_item(item) for item in self.items]
        finally:
            self.loading_items = was_loading

    def load_items(self, items: list[dict], profile_id: str | None = None, asset_context: AssetContext | None = None) -> None:
        self.loading_items = True
        self.items = [validate_item(item) for item in items if isinstance(item, dict)]
        if profile_id is not None:
            self.profile_id = profile_id
        if asset_context is not None:
            self.asset_context = asset_context
        self.populate_tree()
        self.loading_items = False
