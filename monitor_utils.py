from __future__ import annotations

from PyQt6 import QtCore, QtGui


def monitor_id(screen: QtGui.QScreen | None) -> str:
    if screen is None:
        return ""

    name = str(screen.name() or "").strip()
    if name:
        return f"name:{name}"

    hardware_parts = []
    for attribute in ("manufacturer", "model", "serialNumber"):
        value = getattr(screen, attribute, None)
        if callable(value):
            text = str(value() or "").strip()
            if text:
                hardware_parts.append(text)
    if hardware_parts:
        return "hardware:" + "|".join(hardware_parts)

    geometry = screen.geometry()
    return (
        "geometry:"
        f"{geometry.x()},{geometry.y()},"
        f"{geometry.width()}x{geometry.height()}"
    )


def connected_monitor_map() -> dict[str, QtGui.QScreen]:
    monitors: dict[str, QtGui.QScreen] = {}
    for screen in QtGui.QGuiApplication.screens():
        screen_id = monitor_id(screen)
        if screen_id and screen_id not in monitors:
            monitors[screen_id] = screen
    return monitors


def connected_monitor_ids() -> list[str]:
    return connected_monitor_ids_in_screen_order()


def connected_monitor_ids_in_screen_order() -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for screen in QtGui.QGuiApplication.screens():
        screen_id = monitor_id(screen)
        if screen_id and screen_id not in seen:
            seen.add(screen_id)
            ids.append(screen_id)
    return ids


def primary_monitor_id() -> str:
    return monitor_id(QtGui.QGuiApplication.primaryScreen())


def monitor_display_name(screen: QtGui.QScreen, index: int) -> str:
    geometry = screen.geometry()
    name = str(screen.name() or monitor_id(screen) or "Unknown").strip()
    primary = " - Primary" if screen == QtGui.QGuiApplication.primaryScreen() else ""
    return f"Monitor {index + 1} - {geometry.width()} x {geometry.height()} - {name}{primary}"


def monitor_tray_display_name(screen: QtGui.QScreen, index: int) -> str:
    name_parts: list[str] = []
    for attribute in ("manufacturer", "model"):
        value = getattr(screen, attribute, None)
        if callable(value):
            text = str(value() or "").strip()
            if text and text not in name_parts:
                name_parts.append(text)
    name = " ".join(name_parts).strip() or str(screen.name() or monitor_id(screen) or "Unknown").strip()
    primary = " (Primary)" if screen == QtGui.QGuiApplication.primaryScreen() else ""
    return f"Monitor {index + 1} - {name}{primary}"


def monitor_metadata(screen: QtGui.QScreen, index: int | None = None) -> dict:
    geometry = screen.geometry()
    metadata = {
        "display_name": monitor_display_name(screen, index if index is not None else 0),
        "manufacturer": "",
        "model": "",
        "serial_number": "",
        "last_geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
    }
    for key, attribute in (
        ("manufacturer", "manufacturer"),
        ("model", "model"),
        ("serial_number", "serialNumber"),
    ):
        value = getattr(screen, attribute, None)
        if callable(value):
            metadata[key] = str(value() or "")
    return metadata


def screen_for_monitor_id(selected_monitor_id: str) -> QtGui.QScreen | None:
    for screen in QtGui.QGuiApplication.screens():
        if monitor_id(screen) == selected_monitor_id:
            return screen
    return None


def index_for_monitor_id(selected_monitor_id: str) -> int | None:
    for index, screen in enumerate(QtGui.QGuiApplication.screens()):
        if monitor_id(screen) == selected_monitor_id:
            return index
    return None
