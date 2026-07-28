from __future__ import annotations

import copy
from typing import Callable
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from app_icon import apply_window_icon
from config_manager import DEFAULT_LOGO_IMAGE, validate_logo
from icon_utilities import (
    AssetContext,
    import_icon_from_mime_data,
    import_logo_file,
    import_logo_image,
    import_logo_url,
    pixmap_from_image_file,
)
from launcher_editor import LauncherEditorDialog
from logo_widget import resolve_logo_path
from nested_item_editor import NestedItemEditorWidget


LOGO_IMPORT_FORMATS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico"}
LOGO_IMPORT_FORMATS.add(".gif")

LEFT_CLICK_ACTIONS = [
    ("Do nothing", "none"),
    ("Open logo menu", "open_menu"),
    ("Open first enabled item", "open_first_item"),
    ("Custom launcher", "custom_launcher"),
]


class LogoPreviewWidget(QtWidgets.QLabel):
    logoDropped = QtCore.pyqtSignal(object)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("Drop a logo image here\nor paste an image or web image URL", parent)
        self.source_pixmap = QtGui.QPixmap()
        self.movie_player: QtGui.QMovie | None = None
        self.hint_text = ""
        self.logo_config: dict | None = None
        self.setAcceptDrops(True)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setMinimumHeight(118)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.setWordWrap(True)
        self.set_drag_active(False)

    def set_drag_active(self, active: bool) -> None:
        border = "#6aa9ff" if active else "#777777"
        background = "rgba(106, 169, 255, 0.08)" if active else "rgba(255, 255, 255, 0.03)"
        self.setStyleSheet(
            f"""
            QLabel {{
                background-color: {background};
                border: 1px dashed {border};
                border-radius: 6px;
                color: #999999;
                padding: 12px;
            }}
            """
        )

    def set_preview_pixmap(self, pixmap: QtGui.QPixmap, hint_text: str, logo_config: dict | None = None) -> None:
        self.stop_movie()
        self.source_pixmap = pixmap
        self.hint_text = hint_text
        self.logo_config = logo_config
        self.render_preview()

    def set_preview_movie(self, path: str, hint_text: str, logo_config: dict | None = None) -> bool:
        self.clear_preview()
        movie = QtGui.QMovie(path)
        if not movie.isValid():
            return False
        movie.setCacheMode(QtGui.QMovie.CacheMode.CacheAll)
        movie.frameChanged.connect(self.render_preview)
        self.movie_player = movie
        self.hint_text = hint_text
        self.logo_config = logo_config
        movie.start()
        self.render_preview()
        return True

    def clear_preview(self) -> None:
        self.stop_movie()
        self.source_pixmap = QtGui.QPixmap()
        self.logo_config = None
        self.clear()

    def set_empty_message(self, message: str) -> None:
        self.stop_movie()
        self.source_pixmap = QtGui.QPixmap()
        self.logo_config = None
        self.clear()
        self.setText(message)

    def stop_movie(self) -> None:
        if self.movie_player is None:
            return
        self.movie_player.stop()
        self.movie_player.deleteLater()
        self.movie_player = None

    def render_preview(self) -> None:
        source_pixmap = self.current_source_pixmap()
        if source_pixmap.isNull():
            return
        size = self.contentsRect().size()
        if size.width() <= 0 or size.height() <= 0:
            return
        canvas = QtGui.QPixmap(size)
        canvas.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(canvas)
        try:
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
            text_height = 24 if self.hint_text else 0
            image_size = QtCore.QSize(max(1, size.width() - 24), max(1, size.height() - text_height - 24))
            logo = self.logo_config or {}
            logical_size = QtCore.QSize(
                max(1, int(logo.get("maximum_width", source_pixmap.width()))),
                max(1, int(logo.get("height", source_pixmap.height()))),
            )
            preserve = bool(logo.get("preserve_aspect_ratio", True))
            if preserve:
                display_size = source_pixmap.size().scaled(
                    logical_size,
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                )
            else:
                display_size = logical_size
            display_size.scale(image_size, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            scaled = source_pixmap.scaled(
                display_size,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio if preserve else QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            x = (size.width() - scaled.width()) // 2
            y = max(0, (size.height() - text_height - scaled.height()) // 2)
            painter.setOpacity(float(logo.get("opacity", 1.0)))
            painter.drawPixmap(x, y, scaled)
            painter.setOpacity(1.0)
            if self.hint_text:
                painter.setPen(QtGui.QColor("#999999"))
                painter.drawText(
                    QtCore.QRect(0, size.height() - text_height, size.width(), text_height),
                    QtCore.Qt.AlignmentFlag.AlignCenter,
                    self.hint_text,
                )
        finally:
            painter.end()
        self.setText("")
        self.setPixmap(canvas)

    def current_source_pixmap(self) -> QtGui.QPixmap:
        if self.movie_player is not None:
            return self.movie_player.currentPixmap()
        return self.source_pixmap

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if self.accepts_mime(event.mimeData()):
            self.set_drag_active(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if self.accepts_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent) -> None:
        self.set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        self.set_drag_active(False)
        if self.accepts_mime(event.mimeData()):
            self.logoDropped.emit(event.mimeData())
            event.acceptProposedAction()
        else:
            event.ignore()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.matches(QtGui.QKeySequence.StandardKey.Paste):
            clipboard = QtWidgets.QApplication.clipboard()
            if clipboard is not None and self.accepts_mime(clipboard.mimeData()):
                self.logoDropped.emit(clipboard.mimeData())
                event.accept()
                return
        super().keyPressEvent(event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.render_preview()

    def accepts_mime(self, mime: QtCore.QMimeData) -> bool:
        if mime.hasImage():
            return True
        for url in mime.urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.is_file() and path.suffix.lower() in LOGO_IMPORT_FORMATS:
                    return True
            elif url.scheme().lower() in {"http", "https"}:
                return True
        return mime.text().strip().lower().startswith(("http://", "https://"))


class LogoEditorWidget(QtWidgets.QWidget):
    configurationChanged = QtCore.pyqtSignal()

    def __init__(
        self,
        logo_config: dict,
        fallback_height: int,
        parent: QtWidgets.QWidget | None = None,
        profile_id: str | None = None,
        asset_context: AssetContext | None = None,
        transfer_callback: Callable[[str, list[int], dict], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.logo_config = validate_logo(copy.deepcopy(logo_config), fallback_height)
        self.custom_launcher = copy.deepcopy(self.logo_config.get("left_click_launcher"))
        self.profile_id = profile_id
        self.asset_context = asset_context
        self.transfer_callback = transfer_callback
        self.fallback_height = fallback_height
        self.loading_logo = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.build_appearance_tab()
        self.build_menu_tab()
        self.populate()

    def build_appearance_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)
        layout.addLayout(form)

        self.visible_check = QtWidgets.QCheckBox("Show logo")
        self.image_edit = QtWidgets.QLineEdit()
        image_row = QtWidgets.QHBoxLayout()
        image_row.addWidget(self.image_edit)
        browse_button = QtWidgets.QPushButton("Browse")
        browse_button.clicked.connect(self.browse_logo)
        default_button = QtWidgets.QPushButton("Restore Default Logo")
        default_button.clicked.connect(self.restore_default_logo)
        image_row.addWidget(browse_button)
        image_row.addWidget(default_button)

        self.height_spin = QtWidgets.QSpinBox()
        self.height_spin.setRange(16, 200)
        self.maximum_width_spin = QtWidgets.QSpinBox()
        self.maximum_width_spin.setRange(32, 600)
        self.opacity_spin = QtWidgets.QDoubleSpinBox()
        self.opacity_spin.setRange(0.10, 1.00)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setDecimals(2)
        self.preserve_check = QtWidgets.QCheckBox("Preserve aspect ratio")
        toggle_row = QtWidgets.QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(12)
        toggle_row.addWidget(self.visible_check)
        toggle_row.addWidget(self.preserve_check)
        toggle_row.addStretch()
        self.tooltip_edit = QtWidgets.QLineEdit()
        self.left_click_combo = QtWidgets.QComboBox()
        for label, value in LEFT_CLICK_ACTIONS:
            self.left_click_combo.addItem(label, value)
        self.edit_action_button = QtWidgets.QPushButton("Edit Action")
        self.edit_action_button.clicked.connect(self.edit_custom_launcher)

        form.addRow("", toggle_row)
        form.addRow("Logo image path", image_row)
        form.addRow("Logo height", self.height_spin)
        form.addRow("Maximum width", self.maximum_width_spin)
        form.addRow("Logo opacity", self.opacity_spin)
        form.addRow("Tooltip", self.tooltip_edit)
        form.addRow("Left-click action", self.left_click_combo)
        form.addRow("Custom left-click launcher", self.edit_action_button)

        self.preview = LogoPreviewWidget()
        self.preview.logoDropped.connect(self.import_dropped_logo)
        layout.addWidget(QtWidgets.QLabel("Preview"))
        layout.addWidget(self.preview, 1)
        self.tabs.addTab(tab, "Appearance")

        for widget in (
            self.visible_check,
            self.image_edit,
            self.height_spin,
            self.maximum_width_spin,
            self.opacity_spin,
            self.preserve_check,
            self.tooltip_edit,
            self.left_click_combo,
        ):
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.textChanged.connect(self.update_preview)
            elif isinstance(widget, QtWidgets.QComboBox):
                widget.currentIndexChanged.connect(self.update_preview)
                widget.currentIndexChanged.connect(self.update_action_state)
            else:
                widget.valueChanged.connect(self.update_preview) if hasattr(widget, "valueChanged") else widget.toggled.connect(self.update_preview)

    def build_menu_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(QtWidgets.QLabel("Drag files, folders, apps, scripts, HTML pages, or website shortcuts here to add them."))
        self.menu_editor = NestedItemEditorWidget(
            self.logo_config.get("menu_items", []),
            tab,
            profile_id=self.profile_id,
            add_button_in_layout=False,
            asset_context=self.asset_context,
            transfer_callback=self.transfer_callback,
        )
        self.menu_editor.configurationChanged.connect(self.on_menu_configuration_changed)
        layout.addWidget(self.menu_editor, 1)
        self.tabs.addTab(tab, "Logo Menu")

    def populate(self) -> None:
        self.loading_logo = True
        try:
            self.visible_check.setChecked(bool(self.logo_config["visible"]))
            self.image_edit.setText(str(self.logo_config["image"]))
            self.height_spin.setValue(int(self.logo_config["height"]))
            self.maximum_width_spin.setValue(int(self.logo_config["maximum_width"]))
            self.opacity_spin.setValue(float(self.logo_config["opacity"]))
            self.preserve_check.setChecked(bool(self.logo_config["preserve_aspect_ratio"]))
            self.tooltip_edit.setText(str(self.logo_config["tooltip"]))
            index = self.left_click_combo.findData(self.logo_config["left_click_action"])
            self.left_click_combo.setCurrentIndex(max(0, index))
            self.update_action_state()
            self.update_preview()
        finally:
            self.loading_logo = False

    def set_logo_config(self, logo_config: dict, fallback_height: int | None = None) -> None:
        self.loading_logo = True
        if fallback_height is not None:
            self.fallback_height = fallback_height
        self.logo_config = validate_logo(copy.deepcopy(logo_config), self.fallback_height)
        self.custom_launcher = copy.deepcopy(self.logo_config.get("left_click_launcher"))
        self.menu_editor.load_items(self.logo_config.get("menu_items", []), self.profile_id, self.asset_context)
        try:
            self.populate()
        finally:
            self.loading_logo = False

    def browse_logo(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose Logo",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.svg *.ico *.gif)",
        )
        if path:
            self.import_logo_file(path)

    def restore_default_logo(self) -> None:
        self.image_edit.setText(DEFAULT_LOGO_IMAGE)
        self.preview.clear_preview()
        QtGui.QPixmapCache.clear()
        self.update_preview()

    def set_imported_logo(self, managed_path: str) -> None:
        self.preview.clear_preview()
        QtGui.QPixmapCache.clear()
        self.image_edit.setText(managed_path)
        self.update_preview()

    def import_logo_file(self, path: str) -> None:
        try:
            managed_path = import_logo_file(path, self.profile_id, self.asset_context)
        except (OSError, ValueError) as exc:
            self.show_logo_error(str(exc))
            return
        self.set_imported_logo(managed_path)

    def import_logo_image(self, image: QtGui.QImage) -> None:
        try:
            managed_path = import_logo_image(image, self.profile_id, self.asset_context)
        except (OSError, ValueError) as exc:
            self.show_logo_error(str(exc))
            return
        self.set_imported_logo(managed_path)

    def import_logo_url(self, url: str) -> None:
        try:
            managed_path = import_logo_url(url, self.profile_id, self.asset_context)
        except (OSError, ValueError) as exc:
            self.show_logo_error(str(exc))
            return
        self.set_imported_logo(managed_path)

    def import_dropped_logo(self, mime: QtCore.QMimeData) -> None:
        if not import_icon_from_mime_data(mime, self.import_logo_file, self.import_logo_image, self.import_logo_url):
            self.show_logo_error("Drop a supported image file or web image URL.")

    def show_logo_error(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Logo Import Failed", message or "That logo could not be imported.")

    def edit_custom_launcher(self) -> None:
        dialog = LauncherEditorDialog(
            self.custom_launcher or {"type": "launcher", "name": "Logo Action"},
            self,
            profile_id=self.profile_id,
            asset_context=self.asset_context,
        )
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.custom_launcher = dialog.result_item()
            self.notify_changed()

    def update_action_state(self) -> None:
        self.edit_action_button.setEnabled(self.left_click_combo.currentData() == "custom_launcher")

    def on_menu_configuration_changed(self) -> None:
        self.update_preview()

    def logo_from_controls(self) -> dict:
        return validate_logo(
            {
                **self.logo_config,
                "visible": self.visible_check.isChecked(),
                "image": self.image_edit.text().strip() or DEFAULT_LOGO_IMAGE,
                "height": self.height_spin.value(),
                "maximum_width": self.maximum_width_spin.value(),
                "opacity": self.opacity_spin.value(),
                "preserve_aspect_ratio": self.preserve_check.isChecked(),
                "tooltip": self.tooltip_edit.text().strip(),
                "left_click_action": self.left_click_combo.currentData(),
                "left_click_launcher": self.custom_launcher,
                "menu_items": self.menu_editor.current_items(),
            },
            self.height_spin.value(),
        )

    def update_preview(self, *_args: object) -> None:
        logo = self.logo_from_controls()
        path = resolve_logo_path(logo.get("image", DEFAULT_LOGO_IMAGE))
        if self.update_preview_from_path(path, logo):
            self.notify_changed()
            return
        fallback_path = resolve_logo_path(DEFAULT_LOGO_IMAGE)
        if self.update_preview_from_path(fallback_path, logo):
            self.notify_changed()
            return
        self.preview.set_empty_message("Drop a logo image here\nor paste an image or web image URL")
        self.notify_changed()

    def notify_changed(self) -> None:
        if not self.loading_logo:
            self.configurationChanged.emit()

    def update_preview_from_path(self, path: str, logo: dict) -> bool:
        if Path(path).suffix.lower() == ".gif":
            if self.preview.set_preview_movie(path, "Drop or paste another image to replace it", logo):
                return True
        pixmap = pixmap_from_image_file(path)
        if pixmap.isNull():
            icon = QtGui.QIcon(path)
            if not icon.isNull():
                pixmap = icon.pixmap(QtCore.QSize(512, 512))
        if pixmap.isNull():
            return False
        self.preview.set_preview_pixmap(pixmap, "Drop or paste another image to replace it", logo)
        return True

    def result_logo(self) -> dict:
        return self.logo_from_controls()


class LogoEditorDialog(QtWidgets.QDialog):
    def __init__(
        self,
        logo_config: dict,
        fallback_height: int,
        parent: QtWidgets.QWidget | None = None,
        profile_id: str | None = None,
        asset_context: AssetContext | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Logo Settings")
        apply_window_icon(self)
        self.resize(760, 560)
        layout = QtWidgets.QVBoxLayout(self)
        self.editor = LogoEditorWidget(
            logo_config,
            fallback_height,
            self,
            profile_id=profile_id,
            asset_context=asset_context,
        )
        layout.addWidget(self.editor, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_logo(self) -> dict:
        return self.editor.result_logo()
