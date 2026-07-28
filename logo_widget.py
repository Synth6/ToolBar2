from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from config_manager import DEFAULT_LOGO_IMAGE, app_base_path, resource_path
from icon_utilities import is_inside_managed_icon_dir, pixmap_from_image_file


SUPPORTED_LOGO_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico", ".gif"}


class LogoWidget(QtWidgets.QLabel):
    leftClicked = QtCore.pyqtSignal()
    rightClicked = QtCore.pyqtSignal(QtCore.QPoint)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft)
        self.opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.movie_player: QtGui.QMovie | None = None

    def apply_logo_config(self, logo_config: dict) -> None:
        self.stop_movie()
        try:
            self.setMovie(None)
        except TypeError:
            pass
        self.setPixmap(QtGui.QPixmap())
        self.clear()
        QtGui.QPixmapCache.clear()
        self.setVisible(bool(logo_config.get("visible", True)))
        self.setToolTip(str(logo_config.get("tooltip") or ""))
        self.opacity_effect.setOpacity(float(logo_config.get("opacity", 1.0)))

        height = int(logo_config.get("height", 48))
        maximum_width = int(logo_config.get("maximum_width", 240))
        self.setFixedHeight(height)
        self.setMaximumWidth(maximum_width)

        image_path = str(logo_config.get("image") or DEFAULT_LOGO_IMAGE)
        path = resolve_logo_path(image_path)
        if path and self.apply_logo_source(path, logo_config):
            pass
        else:
            fallback = resolve_logo_path(DEFAULT_LOGO_IMAGE)
            if fallback:
                self.apply_logo_source(fallback, logo_config)

        has_action = logo_config.get("left_click_action") != "none" or bool(logo_config.get("menu_items"))
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor if has_action else QtCore.Qt.CursorShape.ArrowCursor))

    def stop_movie(self) -> None:
        if self.movie_player is None:
            return
        self.movie_player.stop()
        self.movie_player.deleteLater()
        self.movie_player = None

    def apply_logo_source(self, path: str, logo_config: dict) -> bool:
        if Path(path).suffix.lower() == ".gif":
            return self.apply_gif_logo(path, logo_config)
        return self.apply_static_logo(path, logo_config)

    def apply_gif_logo(self, path: str, logo_config: dict) -> bool:
        movie = QtGui.QMovie(path)
        if not movie.isValid():
            return False
        movie.setCacheMode(QtGui.QMovie.CacheMode.CacheAll)
        movie.jumpToFrame(0)
        movie.setScaledSize(self.scaled_logo_size(movie.currentImage().size(), logo_config))
        movie.setParent(self)
        self.movie_player = movie
        self.setMovie(movie)
        if self.isVisible():
            movie.start()
        return True

    def apply_static_logo(self, path: str, logo_config: dict) -> bool:
        normalized = Path(path).as_posix()
        if is_inside_managed_icon_dir(path) or "/user_profiles/" in normalized or normalized.startswith("user_profiles/"):
            pixmap = pixmap_from_image_file(path)
        else:
            icon = QtGui.QIcon(path)
            pixmap = icon.pixmap(QtCore.QSize(self.maximumWidth(), self.height()))
            if pixmap.isNull():
                pixmap = pixmap_from_image_file(path)
        if pixmap.isNull():
            return False
        pixmap = pixmap.scaled(
            self.scaled_logo_size(pixmap.size(), logo_config),
            QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pixmap)
        return True

    def scaled_logo_size(self, source_size: QtCore.QSize, logo_config: dict) -> QtCore.QSize:
        maximum_width = max(1, int(logo_config.get("maximum_width", 240)))
        height = max(1, int(logo_config.get("height", 48)))
        if bool(logo_config.get("preserve_aspect_ratio", True)):
            base_size = source_size if source_size.isValid() else QtCore.QSize(maximum_width, height)
            return base_size.scaled(
                maximum_width,
                height,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            )
        return QtCore.QSize(maximum_width, height)

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        if self.movie_player is not None:
            self.movie_player.stop()
        super().hideEvent(event)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if self.movie_player is not None:
            self.movie_player.start()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.leftClicked.emit()
            event.accept()
            return
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            self.rightClicked.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)


def resolve_logo_path(path_text: str) -> str:
    path = Path(path_text)
    if path.is_absolute():
        if path.suffix.lower() in SUPPORTED_LOGO_SUFFIXES and path.exists():
            return str(path)
        return ""

    app_relative = app_base_path() / path
    if app_relative.suffix.lower() in SUPPORTED_LOGO_SUFFIXES and app_relative.exists():
        return str(app_relative)

    bundled = Path(resource_path(path_text))
    if bundled.suffix.lower() in SUPPORTED_LOGO_SUFFIXES and bundled.exists():
        return str(bundled)
    return ""
