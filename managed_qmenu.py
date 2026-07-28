from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets


class ManagedMenu(QtWidgets.QMenu):
    itemContextRequested = QtCore.pyqtSignal(str, str, QtCore.QPoint)
    dragMoved = QtCore.pyqtSignal(object, QtCore.QPoint, QtCore.QPoint, object)
    dragDropped = QtCore.pyqtSignal(object, QtCore.QPoint, QtCore.QPoint, object)
    dragLeft = QtCore.pyqtSignal(object)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            position = event.position().toPoint()
            self.emit_context_for_position(position, self.mapToGlobal(position))
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        self.emit_context_for_position(event.pos(), event.globalPos())
        event.accept()

    def emit_context_for_position(self, position: QtCore.QPoint, global_position: QtCore.QPoint) -> None:
        action = self.actionAt(position)
        if action is None:
            return
        data = action.data()
        if not isinstance(data, dict):
            return
        item_id = str(data.get("item_id") or "")
        item_type = str(data.get("item_type") or "")
        if item_id and item_type:
            self.itemContextRequested.emit(item_id, item_type, global_position)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        event.setDropAction(QtCore.Qt.DropAction.CopyAction)
        event.accept()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        position = event.position().toPoint()
        self.setActiveAction(self.actionAt(position))
        self.dragMoved.emit(self, position, self.mapToGlobal(position), event.mimeData())
        event.setDropAction(QtCore.Qt.DropAction.CopyAction)
        event.accept()

    def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent) -> None:
        self.setActiveAction(None)
        self.dragLeft.emit(self)
        event.accept()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        position = event.position().toPoint()
        self.dragDropped.emit(self, position, self.mapToGlobal(position), event.mimeData())
        event.setDropAction(QtCore.Qt.DropAction.CopyAction)
        event.accept()
