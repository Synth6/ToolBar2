from __future__ import annotations

import copy
from typing import Callable

from PyQt6 import QtCore, QtGui, QtWidgets

from config_manager import isolate_profile_item_assets, isolate_profile_menu_assets, validate_config, validate_item, validate_menu
from drop_handler import DroppedItemsDialog, extract_targets_from_mime_data
from folder_menu_properties_dialog import FolderMenuPropertiesDialog
from icon_utilities import AssetContext, icon_for_item
from launcher_editor import LauncherEditorDialog
from menu_properties_dialog import MenuPropertiesDialog
from menu_config_helpers import (
    assign_new_ids_recursive,
    insert_launcher_items,
    launcher_item_to_top_launcher,
    list_menu_destinations,
    top_launcher_to_editor_item,
    top_launcher_to_launcher_item,
    valid_menu_destination_at_path,
)


WEB_SEARCH_TREE_TYPE = "web_search_bar"


class MenuTreeWidget(QtWidgets.QTreeWidget):
    def __init__(self, editor: "MenuEditorWidget") -> None:
        super().__init__()
        self.editor = editor
        self.setHeaderHidden(True)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)

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
            destination_item = self.editor.destination_item_for_position(event.position().toPoint())
            if destination_item is not None:
                self.setCurrentItem(destination_item)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        if event.source() is not self:
            self.editor.handle_external_drop(event)
            return

        before = copy.deepcopy(self.editor.config["menus"])
        before_appearance = copy.deepcopy(self.editor.config.get("appearance", {}))
        super().dropEvent(event)
        if self.editor.tree_is_valid():
            self.editor.sync_config_from_tree()
            event.accept()
            return
        self.editor.config["menus"] = before
        self.editor.config["appearance"] = before_appearance
        self.editor.populate_tree()
        event.ignore()
        QtWidgets.QMessageBox.warning(self, "Invalid Move", "That item cannot be moved to that location.")


class MenuEditorWidget(QtWidgets.QWidget):
    configurationChanged = QtCore.pyqtSignal()

    def __init__(
        self,
        config: dict,
        parent: QtWidgets.QWidget | None = None,
        profile_id: str | None = None,
        asset_context: AssetContext | None = None,
        transfer_callback: Callable[[str, list[int], dict], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.profile_id = profile_id
        self.asset_context = asset_context
        self.transfer_callback = transfer_callback
        self.loading_config = False

        layout = QtWidgets.QVBoxLayout(self)
        self.instructions_label = QtWidgets.QLabel(
            "Drag files, folders, apps, scripts, HTML pages, or website shortcuts here to add them."
        )
        self.instructions_label.setWordWrap(True)
        layout.addWidget(self.instructions_label)
        self.empty_menu_label = QtWidgets.QLabel("Create a top-level menu before dropping shortcuts here.")
        self.empty_menu_label.setWordWrap(True)
        self.empty_menu_label.setStyleSheet("color: #8a5a00;")
        layout.addWidget(self.empty_menu_label)
        self.tree = MenuTreeWidget(self)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.currentItemChanged.connect(self.update_buttons)
        self.tree.itemDoubleClicked.connect(self.handle_double_click)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        layout.addWidget(self.tree, 1)

        grid = QtWidgets.QGridLayout()
        self.add_menu_button = self.button("Add Top-Level Menu", self.add_top_level_menu)
        self.add_item_button = QtWidgets.QPushButton("Add Item...")
        self.add_item_menu = QtWidgets.QMenu(self.add_item_button)
        self.add_item_menu.addAction("Submenu", self.add_submenu)
        self.add_item_menu.addAction("Launcher", self.add_launcher)
        self.add_item_menu.addAction("Heading", self.add_heading)
        self.add_item_menu.addAction("Separator", self.add_separator)
        self.add_item_button.setMenu(self.add_item_menu)

        buttons = [self.add_menu_button, self.add_item_button]
        for index, button in enumerate(buttons):
            grid.addWidget(button, index // 3, index % 3)
        layout.addLayout(grid)
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

    def button_style_fallbacks(self) -> dict[str, str]:
        appearance = self.config.get("appearance", {})
        return {
            "background": appearance.get("button_background", "#3b3b3b"),
            "hover": appearance.get("button_hover", "#505050"),
            "text": appearance.get("button_text", "#ffffff"),
            "border": appearance.get("border_color", "#606060"),
        }

    def refresh_config(self, config: dict, profile_id: str | None = None, asset_context: AssetContext | None = None) -> None:
        self.loading_config = True
        self.config = config
        self.profile_id = profile_id
        if asset_context is not None:
            self.asset_context = asset_context
        self.populate_tree()
        self.loading_config = False

    def populate_tree(self) -> None:
        self.loading_config = True
        expanded = self.expanded_paths()
        self.tree.clear()
        try:
            menus = self.config.get("menus", [])
            search_inserted = False
            search_enabled = self.web_search_enabled()
            search_position = self.web_search_tree_position() if search_enabled else -1
            for index, menu in enumerate(menus):
                if search_enabled and not search_inserted and index == search_position:
                    self.add_web_search_tree_item()
                    search_inserted = True
                self.add_tree_item(None, menu)
            if search_enabled and not search_inserted:
                self.add_web_search_tree_item()
            self.restore_expanded_paths(expanded)
            if self.tree.topLevelItemCount() and self.tree.currentItem() is None:
                self.tree.setCurrentItem(self.tree.topLevelItem(0))
            self.empty_menu_label.setVisible(self.tree.topLevelItemCount() == 0)
            self.update_buttons()
        finally:
            self.loading_config = False

    def web_search_enabled(self) -> bool:
        return bool(self.config.get("appearance", {}).get("show_web_search_bar", False))

    def web_search_tree_position(self) -> int:
        menus_count = len(self.config.get("menus", []))
        try:
            raw_position = int(self.config.get("appearance", {}).get("web_search_position", -1))
        except (TypeError, ValueError):
            raw_position = -1
        if raw_position < 0:
            return menus_count
        return max(0, min(raw_position, menus_count))

    def add_web_search_tree_item(self) -> QtWidgets.QTreeWidgetItem:
        data = {"type": WEB_SEARCH_TREE_TYPE, "name": "Web Search Bar"}
        item = QtWidgets.QTreeWidgetItem(["Web Search Bar"])
        item.setData(0, QtCore.Qt.ItemDataRole.UserRole, data)
        item.setIcon(0, self.web_search_icon())
        item.setFlags(
            (item.flags() | QtCore.Qt.ItemFlag.ItemIsDragEnabled)
            & ~QtCore.Qt.ItemFlag.ItemIsDropEnabled
        )
        self.tree.addTopLevelItem(item)
        return item

    def web_search_icon(self) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(16, 16)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor("#2563eb"), 2)
        painter.setPen(pen)
        painter.drawEllipse(3, 3, 7, 7)
        painter.drawLine(9, 9, 13, 13)
        painter.end()
        return QtGui.QIcon(pixmap)

    def add_tree_item(self, parent: QtWidgets.QTreeWidgetItem | None, data: dict) -> QtWidgets.QTreeWidgetItem:
        if parent is not None and data.get("type") == "top_launcher":
            data = top_launcher_to_launcher_item(data)
        item = QtWidgets.QTreeWidgetItem([self.item_label(data)])
        item.setData(0, QtCore.Qt.ItemDataRole.UserRole, copy.deepcopy(data))
        item.setIcon(0, self.icon_for_tree_item(data))
        font = item.font(0)
        font.setItalic(not bool(data.get("enabled", True)) and data.get("type") in {"menu", "submenu", "launcher", "top_launcher"})
        item.setFont(0, font)
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsDragEnabled | QtCore.Qt.ItemFlag.ItemIsDropEnabled)
        if data.get("type") not in {"menu", "submenu"}:
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsDropEnabled)
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        for child in data.get("items", []):
            self.add_tree_item(item, child)
        item.setExpanded(True)
        return item

    def icon_for_tree_item(self, data: dict) -> QtGui.QIcon:
        if data.get("type") == "menu" and data.get("button_style", {}).get("use_custom_colors"):
            pixmap = QtGui.QPixmap(14, 14)
            pixmap.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setPen(QtGui.QColor(data["button_style"].get("border", "#606060")))
            painter.setBrush(QtGui.QColor(data["button_style"].get("background", "#3b3b3b")))
            painter.drawRect(1, 1, 12, 12)
            painter.end()
            return QtGui.QIcon(pixmap)
        if data.get("type") == "top_launcher":
            return icon_for_item(
                {
                    **data,
                    "type": "launcher",
                    "icon": data.get("icon_path", ""),
                },
                self,
            )
        return icon_for_item(data, self)

    def item_label(self, data: dict) -> str:
        item_type = data.get("type")
        if item_type == "separator":
            return "----------"
        if item_type == "heading":
            return data.get("name", "Heading")
        return data.get("name", "Item")

    def selected_item(self) -> QtWidgets.QTreeWidgetItem | None:
        return self.tree.currentItem()

    def selected_data(self) -> dict | None:
        item = self.selected_item()
        if item is None:
            return None
        data = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def selected_container(self) -> QtWidgets.QTreeWidgetItem | None:
        item = self.selected_item()
        if item is None:
            return None
        data = self.item_data(item)
        if data.get("type") in {"menu", "submenu"}:
            return item
        return item.parent()

    def destination_item_for_position(self, position: QtCore.QPoint) -> QtWidgets.QTreeWidgetItem | None:
        item = self.tree.itemAt(position)
        if item is None:
            return None
        data = self.item_data(item)
        if data.get("type") in {"menu", "submenu"}:
            return item
        return item.parent()

    def config_path_for_item(self, item: QtWidgets.QTreeWidgetItem) -> list[int]:
        path: list[int] = []
        current = item
        while current.parent() is not None:
            parent = current.parent()
            path.insert(0, parent.indexOfChild(current))
            current = parent
        path.insert(0, self.tree.indexOfTopLevelItem(current))
        return path

    def handle_external_drop(self, event: QtGui.QDropEvent) -> None:
        targets = extract_targets_from_mime_data(event.mimeData())
        if not targets:
            event.ignore()
            return

        destinations = list_menu_destinations(self.config)
        destination_item = self.destination_item_for_position(event.position().toPoint())
        preselected_path = self.config_path_for_item(destination_item) if destination_item is not None else None
        dialog = DroppedItemsDialog(targets, destinations, preselected_path, self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            event.ignore()
            return

        results = dialog.result_items()
        inserted_path = self.add_dropped_results(results)
        if inserted_path is not False:
            self.populate_tree()
            if isinstance(inserted_path, list):
                destination = self.item_at_path(tuple(inserted_path))
                if destination is not None:
                    destination.setExpanded(True)
                    self.tree.setCurrentItem(destination)
            self.notify_changed()
            event.setDropAction(QtCore.Qt.DropAction.CopyAction)
            event.accept()
            return

        QtWidgets.QMessageBox.warning(self, "Invalid Destination", "Choose a menu or submenu destination.")
        event.ignore()

    def add_dropped_results(self, results: list[dict]) -> list[int] | None | bool:
        next_config = copy.deepcopy(self.config)
        first_destination_path: list[int] | None = None
        for result in results:
            item = copy.deepcopy(result.get("item") or {})
            add_mode = str(result.get("add_mode") or "")
            if add_mode in {"top_level", "top_level_folder_menu"}:
                if item.get("type") == "launcher":
                    item = launcher_item_to_top_launcher(item)
                next_config.setdefault("menus", []).append(item)
                continue
            destination_path = copy.deepcopy(result.get("destination_path"))
            destination_id = str(result.get("destination_id") or "")
            if not isinstance(destination_path, list):
                return False
            if not valid_menu_destination_at_path(next_config, destination_path, destination_id):
                return False
            if not insert_launcher_items(next_config, destination_path, [item]):
                return False
            if first_destination_path is None:
                first_destination_path = destination_path
        self.config = next_config
        return first_destination_path

    def item_data(self, item: QtWidgets.QTreeWidgetItem) -> dict:
        return item.data(0, QtCore.Qt.ItemDataRole.UserRole)

    def update_buttons(self) -> None:
        data = self.selected_data()
        is_container = bool(data and data.get("type") in {"menu", "submenu"})
        self.add_item_button.setEnabled(is_container)

    def show_tree_context_menu(self, position: QtCore.QPoint) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            return
        self.tree.setCurrentItem(item)

        menu = QtWidgets.QMenu(self)
        data = self.item_data(item)
        item_type = data.get("type")
        if item_type == WEB_SEARCH_TREE_TYPE:
            menu.addAction("Edit Search Bar...", self.edit_web_search_bar)
            move_left = menu.addAction("Move Left", lambda: self.move_selected(-1))
            move_left.setEnabled(self.can_move_up(item))
            move_right = menu.addAction("Move Right", lambda: self.move_selected(1))
            move_right.setEnabled(self.can_move_down(item))
            move_up = menu.addAction("Move Up", lambda: self.move_selected(-1))
            move_up.setEnabled(self.can_move_up(item))
            move_down = menu.addAction("Move Down", lambda: self.move_selected(1))
            move_down.setEnabled(self.can_move_down(item))
            menu.addSeparator()
            menu.addAction("Hide Search Bar", self.hide_web_search_bar)
            menu.exec(self.tree.viewport().mapToGlobal(position))
            return
        is_container = item_type in {"menu", "submenu"}

        if self.can_edit(item):
            menu.addAction("Edit", self.edit_selected)
        if self.can_rename(item):
            menu.addAction("Rename", self.rename_selected)
        if is_container:
            if not menu.isEmpty():
                menu.addSeparator()
            menu.addAction("Add Submenu", self.add_submenu)
            menu.addAction("Add Launcher", self.add_launcher)
            menu.addAction("Add Heading", self.add_heading)
            menu.addAction("Add Separator", self.add_separator)
        if self.can_duplicate(item):
            if not menu.isEmpty():
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
            if not menu.isEmpty():
                menu.addSeparator()
            for text, _enabled, callback in valid_moves:
                menu.addAction(text, callback)

        if self.can_delete(item):
            if not menu.isEmpty():
                menu.addSeparator()
            menu.addAction("Delete", self.delete_selected)

        if not menu.isEmpty():
            menu.exec(self.tree.viewport().mapToGlobal(position))

    def can_edit(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        if item is None:
            return False
        item_type = self.item_data(item).get("type")
        return item_type in {"launcher", "top_launcher", "folder_menu"} or (item.parent() is None and item_type == "menu")

    def can_rename(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        if item is None:
            return False
        return self.item_data(item).get("type") in {"menu", "submenu", "heading", "launcher", "top_launcher"}

    def can_duplicate(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        return item is not None and self.item_data(item).get("type") != WEB_SEARCH_TREE_TYPE

    def can_delete(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        return item is not None and self.item_data(item).get("type") != WEB_SEARCH_TREE_TYPE

    def can_move_up(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        return self.sibling_index(item) > 0

    def can_move_down(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        index = self.sibling_index(item)
        if item is None or index < 0:
            return False
        parent = item.parent()
        siblings_count = self.tree.topLevelItemCount() if parent is None else parent.childCount()
        return index < siblings_count - 1

    def can_move_left(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        if item is None or item.parent() is None:
            return False
        parent = item.parent()
        return parent.parent() is not None or self.item_data(item).get("type") in {"submenu", "launcher", "top_launcher"}

    def can_move_right(self, item: QtWidgets.QTreeWidgetItem | None) -> bool:
        index = self.sibling_index(item)
        if item is None or index <= 0:
            return False
        parent = item.parent()
        target = self.tree.topLevelItem(index - 1) if parent is None else parent.child(index - 1)
        if self.item_data(item).get("type") == WEB_SEARCH_TREE_TYPE:
            return False
        return self.item_data(target).get("type") in {"menu", "submenu"}

    def sibling_index(self, item: QtWidgets.QTreeWidgetItem | None) -> int:
        if item is None:
            return -1
        parent = item.parent()
        return self.tree.indexOfTopLevelItem(item) if parent is None else parent.indexOfChild(item)

    def add_top_level_menu(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "Add Top-Level Menu", "Menu name:")
        if not ok:
            return
        data = validate_menu({"name": name.strip() or "Menu", "type": "menu", "items": []}, top_level=True)
        self.config.setdefault("menus", []).append(data)
        self.populate_tree()
        self.tree.setCurrentItem(self.tree.topLevelItem(self.tree.topLevelItemCount() - 1))
        self.notify_changed()

    def add_submenu(self) -> None:
        container = self.selected_container()
        if container is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Add Submenu", "Submenu name:")
        if not ok:
            return
        self.add_child_data(container, validate_item({"name": name.strip() or "Submenu", "type": "submenu", "items": []}))

    def add_launcher(self) -> None:
        container = self.selected_container()
        if container is None:
            return
        dialog = LauncherEditorDialog({"type": "launcher", "name": "New Launcher"}, self, profile_id=self.profile_id, asset_context=self.asset_context)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.add_child_data(container, dialog.result_item())

    def add_separator(self) -> None:
        container = self.selected_container()
        if container is not None:
            self.add_child_data(container, {"type": "separator"})

    def add_heading(self) -> None:
        container = self.selected_container()
        if container is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Add Heading", "Heading text:")
        if ok:
            self.add_child_data(container, validate_item({"name": name.strip() or "Heading", "type": "heading"}))

    def add_child_data(self, container: QtWidgets.QTreeWidgetItem, data: dict) -> None:
        container_data = self.item_data(container)
        container_data.setdefault("items", []).append(data)
        child = self.add_tree_item(container, data)
        container.setExpanded(True)
        self.tree.setCurrentItem(child)
        self.sync_config_from_tree()

    def edit_web_search_bar(self) -> None:
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
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        appearance["web_search_width"] = width_spin.value()
        appearance["web_search_placeholder"] = placeholder_edit.text().strip() or "Search the web..."
        appearance["web_search_engine"] = str(engine_combo.currentData() or "Google")
        appearance["web_search_custom_url"] = custom_url_edit.text().strip()
        self.populate_tree()
        self.sync_config_from_tree()

    def hide_web_search_bar(self) -> None:
        self.config.setdefault("appearance", {})["show_web_search_bar"] = False
        self.populate_tree()
        self.sync_config_from_tree()

    def edit_selected(self) -> None:
        item = self.selected_item()
        data = self.selected_data()
        if item is None or not data:
            return
        if data.get("type") == "menu" and item.parent() is None:
            dialog = MenuPropertiesDialog(data, self.config["appearance"], self, profile_id=self.profile_id, asset_context=self.asset_context)
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                updated = dialog.result_menu()
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, updated)
                item.setText(0, self.item_label(updated))
                item.setIcon(0, self.icon_for_tree_item(updated))
                font = item.font(0)
                font.setItalic(not bool(updated.get("enabled", True)))
                item.setFont(0, font)
                self.sync_config_from_tree()
            return
        if data.get("type") == "folder_menu":
            dialog = FolderMenuPropertiesDialog(
                data,
                self,
                profile_id=self.profile_id,
                asset_context=self.asset_context,
                top_level=item.parent() is None,
                button_fallbacks=self.button_style_fallbacks(),
            )
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                updated = dialog.result_menu()
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, updated)
                item.setText(0, self.item_label(updated))
                item.setIcon(0, self.icon_for_tree_item(updated))
                font = item.font(0)
                font.setItalic(not bool(updated.get("enabled", True)))
                item.setFont(0, font)
                self.sync_config_from_tree()
            return
        if data.get("type") == "top_launcher" and item.parent() is None:
            dialog = LauncherEditorDialog(
                self.top_launcher_as_editor_item(data),
                self,
                global_appearance=self.config["appearance"],
                top_level=True,
                profile_id=self.profile_id,
                asset_context=self.asset_context,
            )
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                updated = self.launcher_item_as_top_launcher(data, dialog.result_item())
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, updated)
                item.setText(0, self.item_label(updated))
                item.setIcon(0, self.icon_for_tree_item(updated))
                font = item.font(0)
                font.setItalic(not bool(updated.get("enabled", True)))
                item.setFont(0, font)
                self.sync_config_from_tree()
            return
        if data.get("type") != "launcher":
            return
        dialog = LauncherEditorDialog(data, self, profile_id=self.profile_id, asset_context=self.asset_context)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            updated = dialog.result_item()
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, updated)
            item.setText(0, self.item_label(updated))
            item.setIcon(0, icon_for_item(updated, self))
            self.sync_config_from_tree()

    def handle_double_click(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        data_type = self.item_data(item).get("type")
        if data_type == WEB_SEARCH_TREE_TYPE:
            self.tree.setCurrentItem(item)
            self.edit_web_search_bar()
            return
        if data_type in {"launcher", "top_launcher", "folder_menu"} or (item.parent() is None and data_type == "menu"):
            self.tree.setCurrentItem(item)
            self.edit_selected()

    def top_launcher_as_launcher_item(self, launcher_config: dict) -> dict:
        return top_launcher_to_launcher_item(launcher_config)

    def top_launcher_as_editor_item(self, launcher_config: dict) -> dict:
        return top_launcher_to_editor_item(
            launcher_config,
            self.button_style_fallbacks(),
        )

    def launcher_item_as_top_launcher(self, launcher_config: dict, updated_item: dict) -> dict:
        return launcher_item_to_top_launcher(
            updated_item,
            launcher_config,
            self.button_style_fallbacks(),
        )

    def rename_selected(self) -> None:
        item = self.selected_item()
        data = self.selected_data()
        if item is None or not data or data.get("type") == "separator":
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=data.get("name", ""))
        if ok:
            data["name"] = name.strip() or self.item_label(data)
            item.setText(0, self.item_label(data))
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, data)
            self.sync_config_from_tree()

    def duplicate_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        data = copy.deepcopy(self.item_data(item))
        assign_new_ids_recursive(data)
        if "name" in data:
            data["name"] = f"{data['name']} Copy"
        if self.profile_id:
            if item.parent() is None:
                isolate_profile_menu_assets(data, self.profile_id)
            else:
                isolate_profile_item_assets(data, self.profile_id)
        parent = item.parent()
        clone = self.add_tree_item(parent, data)
        if parent is None:
            self.tree.insertTopLevelItem(self.tree.indexOfTopLevelItem(item) + 1, self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(clone)))
        else:
            parent.insertChild(parent.indexOfChild(item) + 1, parent.takeChild(parent.indexOfChild(clone)))
        self.tree.setCurrentItem(clone)
        self.sync_config_from_tree()

    def transfer_selected(self, mode: str) -> None:
        item = self.selected_item()
        if item is None or self.transfer_callback is None:
            return
        self.sync_config_from_tree()
        self.transfer_callback(
            mode,
            self.config_path_for_item(item),
            copy.deepcopy(self.item_data(item)),
        )

    def delete_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        data = self.item_data(item)
        if data.get("type") in {"menu", "submenu"} and item.childCount():
            response = QtWidgets.QMessageBox.question(
                self,
                "Delete Menu",
                "Delete this menu and all items inside it?",
            )
            if response != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        parent = item.parent()
        if parent is None:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        else:
            parent.takeChild(parent.indexOfChild(item))
        self.sync_config_from_tree()

    def move_selected(self, direction: int) -> None:
        item = self.selected_item()
        if item is None:
            return
        parent = item.parent()
        siblings_count = self.tree.topLevelItemCount() if parent is None else parent.childCount()
        index = self.tree.indexOfTopLevelItem(item) if parent is None else parent.indexOfChild(item)
        new_index = index + direction
        if not 0 <= new_index < siblings_count:
            return
        moved = self.tree.takeTopLevelItem(index) if parent is None else parent.takeChild(index)
        if parent is None:
            self.tree.insertTopLevelItem(new_index, moved)
        else:
            parent.insertChild(new_index, moved)
        self.tree.setCurrentItem(moved)
        self.sync_config_from_tree()

    def move_right(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        parent = item.parent()
        index = self.tree.indexOfTopLevelItem(item) if parent is None else parent.indexOfChild(item)
        if index <= 0:
            return
        target = self.tree.topLevelItem(index - 1) if parent is None else parent.child(index - 1)
        if self.item_data(target).get("type") not in {"menu", "submenu"}:
            return
        moved = self.tree.takeTopLevelItem(index) if parent is None else parent.takeChild(index)
        if parent is None and self.item_data(moved).get("type") == "top_launcher":
            moved_data = top_launcher_to_launcher_item(self.item_data(moved))
            moved.setData(0, QtCore.Qt.ItemDataRole.UserRole, moved_data)
            moved.setIcon(0, self.icon_for_tree_item(moved_data))
        target.addChild(moved)
        target.setExpanded(True)
        self.tree.setCurrentItem(moved)
        self.sync_config_from_tree()

    def move_left(self) -> None:
        item = self.selected_item()
        if item is None or item.parent() is None:
            return
        parent = item.parent()
        grandparent = parent.parent()
        index = parent.indexOfChild(item)
        moved = parent.takeChild(index)
        if grandparent is None:
            moved_type = self.item_data(moved).get("type")
            if moved_type == "submenu":
                moved_data = self.item_data(moved)
                moved_data["type"] = "menu"
                moved.setData(0, QtCore.Qt.ItemDataRole.UserRole, moved_data)
            elif moved_type == "launcher":
                moved_data = launcher_item_to_top_launcher(
                    self.item_data(moved),
                    button_fallbacks=self.button_style_fallbacks(),
                )
                moved.setData(0, QtCore.Qt.ItemDataRole.UserRole, moved_data)
                moved.setIcon(0, self.icon_for_tree_item(moved_data))
            elif moved_type == "top_launcher":
                moved_data = launcher_item_to_top_launcher(
                    top_launcher_to_launcher_item(self.item_data(moved)),
                    self.item_data(moved),
                    self.button_style_fallbacks(),
                )
                moved.setData(0, QtCore.Qt.ItemDataRole.UserRole, moved_data)
                moved.setIcon(0, self.icon_for_tree_item(moved_data))
            else:
                parent.insertChild(index, moved)
                return
            self.tree.insertTopLevelItem(self.tree.indexOfTopLevelItem(parent) + 1, moved)
        else:
            grandparent.insertChild(grandparent.indexOfChild(parent) + 1, moved)
        self.tree.setCurrentItem(moved)
        self.sync_config_from_tree()

    def tree_is_valid(self) -> bool:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            item_type = self.item_data(item).get("type")
            if item_type == WEB_SEARCH_TREE_TYPE:
                if item.childCount():
                    return False
                continue
            if item_type not in {"menu", "folder_menu", "top_launcher", "launcher"}:
                return False
            if item_type in {"top_launcher", "launcher"} and item.childCount():
                return False
            if not self.children_are_valid(item):
                return False
        return True

    def children_are_valid(self, parent: QtWidgets.QTreeWidgetItem) -> bool:
        parent_type = self.item_data(parent).get("type")
        if parent_type not in {"menu", "submenu"} and parent.childCount():
            return False
        for index in range(parent.childCount()):
            child = parent.child(index)
            child_type = self.item_data(child).get("type")
            if child_type in {"menu", WEB_SEARCH_TREE_TYPE}:
                return False
            if not self.children_are_valid(child):
                return False
        return True

    def sync_config_from_tree(self) -> None:
        menus = []
        search_position = -1
        seen_menu_slots = 0
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            item_type = self.item_data(item).get("type")
            if item_type == WEB_SEARCH_TREE_TYPE:
                search_position = seen_menu_slots
                continue
            menus.append(self.item_to_data(item, top_level=True))
            seen_menu_slots += 1
        self.config["menus"] = menus
        if self.web_search_enabled():
            self.config.setdefault("appearance", {})["web_search_position"] = (
                -1 if search_position < 0 or search_position >= len(menus) else search_position
            )
        self.notify_changed()

    def notify_changed(self) -> None:
        if not self.loading_config:
            self.configurationChanged.emit()

    def item_to_data(self, item: QtWidgets.QTreeWidgetItem, top_level: bool = False) -> dict:
        data = copy.deepcopy(self.item_data(item))
        item_type = data.get("type")
        if top_level:
            if item_type == "launcher":
                data = launcher_item_to_top_launcher(data, button_fallbacks=self.button_style_fallbacks())
            elif item_type not in {"menu", "folder_menu", "top_launcher"}:
                data["type"] = "menu"
        elif item_type == "menu":
            data["type"] = "submenu"
        elif item_type == "top_launcher":
            data = top_launcher_to_launcher_item(data)
        if data.get("type") in {"menu", "submenu"}:
            data["items"] = [self.item_to_data(item.child(index)) for index in range(item.childCount())]
        elif data.get("type") == "top_launcher":
            data["items"] = []
        return data

    def expanded_paths(self) -> set[tuple[int, ...]]:
        paths: set[tuple[int, ...]] = set()
        for index in range(self.tree.topLevelItemCount()):
            self.collect_expanded(self.tree.topLevelItem(index), (index,), paths)
        return paths

    def collect_expanded(self, item: QtWidgets.QTreeWidgetItem, path: tuple[int, ...], paths: set[tuple[int, ...]]) -> None:
        if item.isExpanded():
            paths.add(path)
        for index in range(item.childCount()):
            self.collect_expanded(item.child(index), (*path, index), paths)

    def restore_expanded_paths(self, paths: set[tuple[int, ...]]) -> None:
        for path in paths:
            item = self.item_at_path(path)
            if item is not None:
                item.setExpanded(True)

    def item_at_path(self, path: tuple[int, ...]) -> QtWidgets.QTreeWidgetItem | None:
        if not path:
            return None
        item = self.tree.topLevelItem(path[0])
        for index in path[1:]:
            if item is None:
                return None
            item = item.child(index)
        return item

    def current_config(self) -> dict:
        was_loading = self.loading_config
        self.loading_config = True
        try:
            self.sync_config_from_tree()
            return validate_config(self.config)
        finally:
            self.loading_config = was_loading
