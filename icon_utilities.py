from __future__ import annotations

import os
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from PyQt6 import QtCore, QtGui, QtWidgets

from config_manager import (
    app_base_path,
    safe_icon_id,
    user_profile_staging_icons_relative_dir,
    user_profile_icons_dir,
    user_profile_item_icon_relative_path,
    user_profile_logo_relative_path,
)


ICON_FORMATS = {".png", ".svg", ".ico", ".jpg", ".jpeg", ".webp", ".exe"}
IMPORT_ICON_FORMATS = ICON_FORMATS
MANAGED_ICON_DIR = Path("icons")
MANAGED_LOGO_STEM = "LOGO"
MANAGED_LOGO_SUFFIXES = {".png", ".gif"}
MAX_IMPORTED_ICON_SIZE = 256
MAX_WEB_ICON_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class AssetContext:
    user_profile_id: str
    monitor_profile_id: str | None = None
    staging_session_id: str | None = None


def asset_context_path(context: AssetContext, filename: str) -> tuple[Path, str]:
    if context.staging_session_id:
        relative = user_profile_staging_icons_relative_dir(
            context.staging_session_id,
            context.user_profile_id,
            context.monitor_profile_id,
        ) / filename
        return app_base_path() / relative, str(relative).replace("\\", "/")
    destination = user_profile_icons_dir(context.user_profile_id, context.monitor_profile_id) / filename
    relative = destination.relative_to(app_base_path())
    return destination, str(relative).replace("\\", "/")


def asset_context_logo_path(context: AssetContext, suffix: str) -> tuple[Path, str]:
    if context.staging_session_id:
        normalized_suffix = suffix.lower()
        if normalized_suffix not in MANAGED_LOGO_SUFFIXES:
            normalized_suffix = ".png"
        relative_path = str(
            user_profile_staging_icons_relative_dir(
                context.staging_session_id,
                context.user_profile_id,
                context.monitor_profile_id,
            )
            / f"{MANAGED_LOGO_STEM}{normalized_suffix}"
        ).replace("\\", "/")
        return app_base_path() / relative_path, relative_path
    relative_path = user_profile_logo_relative_path(context.user_profile_id, suffix, context.monitor_profile_id)
    return app_base_path() / relative_path, relative_path


def asset_context_item_icon_path(context: AssetContext, item_id: str, fallback_name: str = "icon") -> tuple[Path, str]:
    if context.staging_session_id:
        safe_name = safe_icon_id(item_id) or fallback_name
        relative_path = str(
            user_profile_staging_icons_relative_dir(
                context.staging_session_id,
                context.user_profile_id,
                context.monitor_profile_id,
            )
            / f"{safe_name}.png"
        ).replace("\\", "/")
        return app_base_path() / relative_path, relative_path
    relative_path = user_profile_item_icon_relative_path(
        context.user_profile_id,
        item_id,
        context.monitor_profile_id,
        fallback_name,
    )
    return app_base_path() / relative_path, relative_path


def context_from_profile_id(profile_id: str | None, asset_context: AssetContext | None = None) -> AssetContext | None:
    return asset_context


class IconPreviewLabel(QtWidgets.QLabel):
    iconDropped = QtCore.pyqtSignal(object)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("Drop image here", parent)
        self.setAcceptDrops(True)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(96, 72)
        self.setStyleSheet("QLabel { color: #888888; }")

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if self.accepts_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        mime = event.mimeData()
        if self.accepts_mime(mime):
            self.iconDropped.emit(mime)
            event.acceptProposedAction()
        else:
            event.ignore()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.matches(QtGui.QKeySequence.StandardKey.Paste):
            clipboard = QtWidgets.QApplication.clipboard()
            if clipboard is not None:
                mime = clipboard.mimeData()
                if self.accepts_mime(mime):
                    self.iconDropped.emit(mime)
                    event.accept()
                    return
        super().keyPressEvent(event)

    def accepts_mime(self, mime: QtCore.QMimeData) -> bool:
        if mime.hasImage():
            return True
        for url in mime.urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(tuple(IMPORT_ICON_FORMATS)):
                return True
            if url.scheme().lower() in {"http", "https"}:
                return True
        text = mime.text().strip()
        return text.lower().startswith(("http://", "https://"))


def resolve_icon_path(icon_path: str) -> str:
    if not icon_path:
        return ""
    expanded = os.path.expandvars(os.path.expanduser(icon_path))
    path = Path(expanded)
    if path.is_absolute():
        return str(path)
    return str(app_base_path() / path)


def custom_icon(icon_path: str) -> QtGui.QIcon:
    resolved = resolve_icon_path(icon_path)
    if not resolved:
        return QtGui.QIcon()
    normalized = icon_path.replace("\\", "/")
    if normalized.startswith(f"{MANAGED_ICON_DIR}/") and not is_inside_managed_icon_dir(icon_path):
        return QtGui.QIcon()
    path = Path(resolved)
    if not path.exists() or path.suffix.lower() not in ICON_FORMATS:
        return QtGui.QIcon()
    if path.suffix.lower() == ".exe":
        return QtWidgets.QFileIconProvider().icon(QtCore.QFileInfo(str(path)))
    if is_inside_managed_icon_dir(icon_path) and path.suffix.lower() == ".png":
        pixmap = pixmap_from_image_file(path)
        return QtGui.QIcon(pixmap) if not pixmap.isNull() else QtGui.QIcon()
    return QtGui.QIcon(resolved)


def managed_icon_dir() -> Path:
    return app_base_path() / MANAGED_ICON_DIR


def managed_icon_relative_path(icon_id: str, fallback_name: str) -> str:
    safe_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in icon_id)
    return str(MANAGED_ICON_DIR / f"{safe_id or fallback_name}.png").replace("\\", "/")


def managed_menu_icon_relative_path(menu_id: str) -> str:
    return managed_icon_relative_path(menu_id, "menu")


def managed_menu_icon_path(menu_id: str) -> Path:
    return app_base_path() / managed_menu_icon_relative_path(menu_id)


def managed_launcher_icon_relative_path(launcher_id: str) -> str:
    return managed_icon_relative_path(launcher_id, "launcher")


def managed_launcher_icon_path(launcher_id: str) -> Path:
    return app_base_path() / managed_launcher_icon_relative_path(launcher_id)


def managed_profile_icon_relative_path(profile_id: str, item_id: str, fallback_name: str = "icon") -> str:
    safe_profile_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in profile_id)
    safe_item_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in item_id)
    return str(MANAGED_ICON_DIR / "profiles" / safe_profile_id / f"{safe_item_id or fallback_name}.png").replace("\\", "/")


def managed_profile_icon_path(profile_id: str, item_id: str, fallback_name: str = "icon") -> Path:
    return app_base_path() / managed_profile_icon_relative_path(profile_id, item_id, fallback_name)


def managed_logo_relative_path(suffix: str = ".png") -> str:
    return str(MANAGED_ICON_DIR / f"{MANAGED_LOGO_STEM}{suffix.lower()}").replace("\\", "/")


def managed_logo_path(suffix: str = ".png") -> Path:
    return app_base_path() / managed_logo_relative_path(suffix)


def managed_profile_logo_relative_path(profile_id: str, suffix: str = ".png") -> str:
    safe_profile_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in profile_id)
    return str(MANAGED_ICON_DIR / "profiles" / safe_profile_id / f"{MANAGED_LOGO_STEM}{suffix.lower()}").replace("\\", "/")


def managed_profile_logo_path(profile_id: str, suffix: str = ".png") -> Path:
    return app_base_path() / managed_profile_logo_relative_path(profile_id, suffix)


def is_inside_managed_icon_dir(icon_path: str) -> bool:
    resolved_icon_path = resolve_icon_path(icon_path)
    if not resolved_icon_path:
        return False
    resolved = Path(resolved_icon_path)
    try:
        resolved.relative_to(managed_icon_dir().resolve())
        return True
    except (OSError, ValueError):
        return False


def is_managed_logo_path(icon_path: str) -> bool:
    resolved_icon_path = resolve_icon_path(icon_path)
    if not resolved_icon_path:
        return False
    try:
        resolved = Path(resolved_icon_path).resolve()
    except OSError:
        return False
    if not is_inside_managed_icon_dir(str(resolved)):
        return False
    return resolved.name.lower() in {f"{MANAGED_LOGO_STEM.lower()}{suffix}" for suffix in MANAGED_LOGO_SUFFIXES}


def prepare_icon_image(image: QtGui.QImage) -> QtGui.QImage:
    if image.isNull():
        return QtGui.QImage()
    converted = image.convertToFormat(QtGui.QImage.Format.Format_ARGB32)
    if converted.width() > MAX_IMPORTED_ICON_SIZE or converted.height() > MAX_IMPORTED_ICON_SIZE:
        converted = converted.scaled(
            MAX_IMPORTED_ICON_SIZE,
            MAX_IMPORTED_ICON_SIZE,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
    return converted


def image_from_file(path: str | Path) -> QtGui.QImage:
    reader = QtGui.QImageReader(str(path))
    reader.setAutoTransform(True)
    return reader.read()


def pixmap_from_image_file(path: str | Path) -> QtGui.QPixmap:
    image = image_from_file(path)
    if image.isNull():
        return QtGui.QPixmap()
    return QtGui.QPixmap.fromImage(image)


def icon_image_from_file(source_path: str) -> QtGui.QImage:
    path = Path(source_path)
    if not path.exists() or path.suffix.lower() not in IMPORT_ICON_FORMATS:
        return QtGui.QImage()
    if path.suffix.lower() == ".exe":
        icon = custom_icon(str(path))
        if icon.isNull():
            return QtGui.QImage()
        return icon.pixmap(MAX_IMPORTED_ICON_SIZE, MAX_IMPORTED_ICON_SIZE).toImage()
    image = image_from_file(path)
    if not image.isNull():
        return image
    icon = custom_icon(str(path))
    if icon.isNull():
        return QtGui.QImage()
    return icon.pixmap(MAX_IMPORTED_ICON_SIZE, MAX_IMPORTED_ICON_SIZE).toImage()


def save_managed_icon(image: QtGui.QImage, destination: Path, relative_path: str) -> str:
    prepared = prepare_icon_image(image)
    if prepared.isNull():
        raise ValueError("That file could not be imported as an icon.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.stem}.",
            suffix=".png",
            dir=destination.parent,
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
        if not prepared.save(temp_path, "PNG"):
            raise OSError("The imported icon could not be saved.")
        if image_from_file(temp_path).isNull():
            raise ValueError("That file could not be imported as an icon.")
        os.replace(temp_path, destination)
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass
    QtGui.QPixmapCache.clear()
    return relative_path


def save_managed_menu_icon(image: QtGui.QImage, menu_id: str) -> str:
    return save_managed_icon(image, managed_menu_icon_path(menu_id), managed_menu_icon_relative_path(menu_id))


def save_managed_launcher_icon(image: QtGui.QImage, launcher_id: str) -> str:
    return save_managed_icon(
        image,
        managed_launcher_icon_path(launcher_id),
        managed_launcher_icon_relative_path(launcher_id),
    )


def save_managed_profile_icon(image: QtGui.QImage, profile_id: str, item_id: str) -> str:
    return save_managed_icon(
        image,
        managed_profile_icon_path(profile_id, item_id),
        managed_profile_icon_relative_path(profile_id, item_id),
    )


def save_asset_context_icon(image: QtGui.QImage, context: AssetContext, item_id: str, fallback_name: str = "icon") -> str:
    destination, relative_path = asset_context_item_icon_path(context, item_id, fallback_name)
    return save_managed_icon(image, destination, relative_path)


def save_managed_logo(image: QtGui.QImage) -> str:
    cleanup_managed_logo_variants(managed_logo_path())
    return save_managed_icon(image, managed_logo_path(), managed_logo_relative_path())


def save_managed_profile_logo(image: QtGui.QImage, profile_id: str) -> str:
    cleanup_managed_logo_variants(managed_profile_logo_path(profile_id))
    return save_managed_icon(image, managed_profile_logo_path(profile_id), managed_profile_logo_relative_path(profile_id))


def save_asset_context_logo(image: QtGui.QImage, context: AssetContext) -> str:
    destination, relative_path = asset_context_logo_path(context, ".png")
    cleanup_managed_logo_variants(destination)
    return save_managed_icon(image, destination, relative_path)


def cleanup_managed_logo_variants(destination: Path) -> None:
    for suffix in MANAGED_LOGO_SUFFIXES:
        candidate = destination.with_suffix(suffix)
        if candidate == destination:
            continue
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


def validate_gif_file(path: str | Path) -> None:
    movie = QtGui.QMovie(str(path))
    if not movie.isValid():
        reader = QtGui.QImageReader(str(path))
        if not reader.canRead():
            raise ValueError("That GIF could not be imported as a logo.")


def save_managed_logo_gif(source_path: str, profile_id: str | None = None, asset_context: AssetContext | None = None) -> str:
    source = Path(source_path)
    if not source.exists() or source.suffix.lower() != ".gif":
        raise ValueError("That GIF could not be imported as a logo.")
    validate_gif_file(source)
    if asset_context is not None:
        destination, relative_path = asset_context_logo_path(asset_context, ".gif")
    else:
        raise ValueError("A user profile asset context is required.")
    cleanup_managed_logo_variants(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.stem}.",
            suffix=destination.suffix,
            dir=destination.parent,
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
        shutil.copy2(source, temp_path)
        validate_gif_file(temp_path)
        os.replace(temp_path, destination)
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass
    QtGui.QPixmapCache.clear()
    return relative_path


def import_menu_icon_file(source_path: str, menu_id: str, profile_id: str | None = None, asset_context: AssetContext | None = None) -> str:
    if asset_context is not None:
        return save_asset_context_icon(icon_image_from_file(source_path), asset_context, menu_id, "menu")
    raise ValueError("A user profile asset context is required.")


def import_menu_icon_image(image: QtGui.QImage, menu_id: str, profile_id: str | None = None, asset_context: AssetContext | None = None) -> str:
    if asset_context is not None:
        return save_asset_context_icon(image, asset_context, menu_id, "menu")
    raise ValueError("A user profile asset context is required.")


def image_from_web_url(url: str) -> QtGui.QImage:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS image URLs can be dropped here.")
    request = urllib.request.Request(url, headers={"User-Agent": "ToolBar2"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_WEB_ICON_BYTES:
                raise ValueError("That web image is larger than 10 MB.")
            data = bytearray()
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > MAX_WEB_ICON_BYTES:
                    raise ValueError("That web image is larger than 10 MB.")
    except urllib.error.URLError as exc:
        raise ValueError("That web image could not be downloaded.") from exc
    image = QtGui.QImage()
    if not image.loadFromData(bytes(data)):
        raise ValueError("That web URL did not provide a supported image.")
    return image


def import_menu_icon_url(url: str, menu_id: str, profile_id: str | None = None, asset_context: AssetContext | None = None) -> str:
    if asset_context is not None:
        return save_asset_context_icon(image_from_web_url(url), asset_context, menu_id, "menu")
    raise ValueError("A user profile asset context is required.")


def import_launcher_icon_file(source_path: str, launcher_id: str, profile_id: str | None = None, asset_context: AssetContext | None = None) -> str:
    if asset_context is not None:
        return save_asset_context_icon(icon_image_from_file(source_path), asset_context, launcher_id, "launcher")
    raise ValueError("A user profile asset context is required.")


def import_launcher_icon_image(image: QtGui.QImage, launcher_id: str, profile_id: str | None = None, asset_context: AssetContext | None = None) -> str:
    if asset_context is not None:
        return save_asset_context_icon(image, asset_context, launcher_id, "launcher")
    raise ValueError("A user profile asset context is required.")


def import_launcher_icon_url(url: str, launcher_id: str, profile_id: str | None = None, asset_context: AssetContext | None = None) -> str:
    if asset_context is not None:
        return save_asset_context_icon(image_from_web_url(url), asset_context, launcher_id, "launcher")
    raise ValueError("A user profile asset context is required.")


def import_logo_file(source_path: str, profile_id: str | None = None, asset_context: AssetContext | None = None) -> str:
    if Path(source_path).suffix.lower() == ".gif":
        return save_managed_logo_gif(source_path, profile_id, asset_context)
    if asset_context is not None:
        return save_asset_context_logo(icon_image_from_file(source_path), asset_context)
    raise ValueError("A user profile asset context is required.")


def import_logo_image(image: QtGui.QImage, profile_id: str | None = None, asset_context: AssetContext | None = None) -> str:
    if asset_context is not None:
        return save_asset_context_logo(image, asset_context)
    raise ValueError("A user profile asset context is required.")


def import_logo_url(url: str, profile_id: str | None = None, asset_context: AssetContext | None = None) -> str:
    if asset_context is not None:
        return save_asset_context_logo(image_from_web_url(url), asset_context)
    raise ValueError("A user profile asset context is required.")


def import_icon_from_mime_data(
    mime: QtCore.QMimeData,
    import_file,
    import_image,
    import_url,
) -> bool:
    if mime.hasImage():
        image_data = mime.imageData()
        if isinstance(image_data, QtGui.QImage):
            import_image(image_data)
            return True
        if isinstance(image_data, QtGui.QPixmap):
            import_image(image_data.toImage())
            return True
    for url in mime.urls():
        if url.isLocalFile():
            import_file(url.toLocalFile())
            return True
        if url.scheme().lower() in {"http", "https"}:
            import_url(url.toString())
            return True
    text = mime.text().strip()
    if text.lower().startswith(("http://", "https://")):
        import_url(text)
        return True
    return False


def delete_managed_menu_icon_if_unused(deleted_menu: dict, menus_or_config: list[dict] | dict) -> None:
    deleted_references: set[Path] = set()
    collect_icon_references_from_menu(deleted_menu, deleted_references)
    for icon_path in deleted_references:
        delete_managed_icon_if_unused(str(icon_path), menus_or_config)


def delete_managed_icon_if_unused(icon_path: str, menus: list[dict], logo_config: dict | None = None) -> None:
    if not icon_path:
        return
    try:
        target = Path(icon_path).resolve() if Path(icon_path).is_absolute() else Path(resolve_icon_path(icon_path)).resolve()
    except OSError:
        return
    if is_managed_logo_path(str(target)):
        return
    if not is_inside_managed_icon_dir(str(target)):
        return
    if is_managed_icon_referenced(str(target), menus, logo_config):
        return
    try:
        target.unlink()
    except OSError:
        pass


def is_managed_icon_referenced(icon_path: str, menus_or_config: list[dict] | dict, logo_config: dict | None = None) -> bool:
    try:
        target = Path(icon_path).resolve() if Path(icon_path).is_absolute() else Path(resolve_icon_path(icon_path)).resolve()
    except OSError:
        return True
    referenced_paths: set[Path] = set()
    if isinstance(menus_or_config, dict):
        collect_icon_references_from_config(menus_or_config, referenced_paths)
    else:
        if logo_config is not None:
            collect_icon_references_from_logo(logo_config, referenced_paths)
        for menu in menus_or_config:
            collect_icon_references_from_menu(menu, referenced_paths)
    for other_path in referenced_paths:
        try:
            if other_path and Path(other_path).resolve() == target:
                return True
        except OSError:
            continue
    return False


def collect_icon_references_from_config(config: dict, references: set[Path]) -> None:
    collect_icon_references_from_logo(config.get("logo", {}), references)
    for menu in config.get("menus", []):
        if isinstance(menu, dict):
            collect_icon_references_from_menu(menu, references)
    profiles = config.get("toolbar_profiles", {})
    if isinstance(profiles, dict):
        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            collect_icon_references_from_logo(profile.get("logo", {}), references)
            for menu in profile.get("menus", []):
                if isinstance(menu, dict):
                    collect_icon_references_from_menu(menu, references)


def collect_icon_references_from_menu(menu: dict, references: set[Path]) -> None:
    add_reference(str(menu.get("icon_path") or ""), references)
    add_reference(str(menu.get("icon") or ""), references)
    if menu.get("type") == "top_launcher":
        add_reference(str(menu.get("icon_path") or ""), references)
    for item in menu.get("items", []):
        collect_icon_references_from_item(item, references)


def collect_icon_references_from_item(item: dict, references: set[Path]) -> None:
    add_reference(str(item.get("icon") or ""), references)
    add_reference(str(item.get("icon_path") or ""), references)
    if item.get("type") in {"submenu", "folder_menu"}:
        for child in item.get("items", []):
            collect_icon_references_from_item(child, references)


def collect_icon_references_from_logo(logo_config: dict, references: set[Path]) -> None:
    add_reference(str(logo_config.get("image") or ""), references)
    launcher = logo_config.get("left_click_launcher")
    if isinstance(launcher, dict):
        collect_icon_references_from_item(launcher, references)
    for item in logo_config.get("menu_items", []):
        collect_icon_references_from_item(item, references)


def add_reference(icon_path: str, references: set[Path]) -> None:
    if not icon_path or is_managed_logo_path(icon_path):
        return
    if not is_inside_managed_icon_dir(icon_path):
        return
    try:
        references.add(Path(resolve_icon_path(icon_path)).resolve())
    except OSError:
        pass


def folder_icon(widget: QtWidgets.QWidget | None = None) -> QtGui.QIcon:
    style_source = widget or QtWidgets.QApplication.instance()
    style = style_source.style() if style_source is not None else QtWidgets.QApplication.style()
    return style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirIcon)


def menu_button_icon(icon_path: str) -> QtGui.QIcon:
    return custom_icon(icon_path)


def folder_menu_icon(item: dict, widget: QtWidgets.QWidget | None = None) -> QtGui.QIcon:
    icon = custom_icon(str(item.get("icon_path") or ""))
    if not icon.isNull():
        return icon
    return folder_icon(widget)


def icon_for_item(item: dict, widget: QtWidgets.QWidget | None = None) -> QtGui.QIcon:
    if item.get("type") == "folder_menu":
        return folder_menu_icon(item, widget)
    icon = custom_icon(str(item.get("icon") or ""))
    if not icon.isNull():
        return icon

    style = (widget or QtWidgets.QApplication.instance()).style()
    provider = QtWidgets.QFileIconProvider()
    target = str(item.get("target") or "")
    target_type = str(item.get("target_type") or "Auto Detect")
    if item.get("type") in {"submenu", "menu"} or target_type == "Folder":
        return folder_icon(widget)
    if target_type == "Website" or target.lower().startswith(("http://", "https://")):
        return style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DriveNetIcon)
    resolved_target = os.path.expandvars(os.path.expanduser(target))

    if target and Path(resolved_target).exists():
        file_icon = provider.icon(QtCore.QFileInfo(resolved_target))
        if not file_icon.isNull():
            return file_icon

    if target_type == "Program":
        return style.standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon
        )
    return style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon)
