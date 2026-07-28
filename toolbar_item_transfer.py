from __future__ import annotations

import copy
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config_manager import (
    app_base_path,
    resolve_profile_owned_asset_path,
    validate_item,
    validate_menu,
)
from icon_utilities import AssetContext, asset_context_item_icon_path, asset_context_logo_path
from menu_config_helpers import assign_new_ids_recursive, launcher_item_to_top_launcher, top_launcher_to_launcher_item


@dataclass
class ToolbarRef:
    profile_id: str
    profile_name: str
    toolbar_key: str
    toolbar_label: str
    monitor_profile_id: str | None = None


@dataclass
class TransferDestination:
    toolbar: ToolbarRef
    container_path: list[int] | None
    position: str
    sibling_path: list[int] | None = None


def item_at_path(toolbar_config: dict, path: list[int]) -> dict | None:
    if not path:
        return None
    try:
        item = toolbar_config["menus"][path[0]]
        for index in path[1:]:
            item = item["items"][index]
        return item
    except (IndexError, KeyError, TypeError):
        return None


def parent_list_for_path(toolbar_config: dict, path: list[int]) -> tuple[list[dict], int] | None:
    if not path:
        return None
    if len(path) == 1:
        return toolbar_config.setdefault("menus", []), path[0]
    parent = item_at_path(toolbar_config, path[:-1])
    if parent is None or parent.get("type") not in {"menu", "submenu"}:
        return None
    return parent.setdefault("items", []), path[-1]


def remove_item_at_path(toolbar_config: dict, path: list[int]) -> dict | None:
    target = parent_list_for_path(toolbar_config, path)
    if target is None:
        return None
    items, index = target
    if not 0 <= index < len(items):
        return None
    return items.pop(index)


def insert_item(toolbar_config: dict, item: dict, destination: TransferDestination) -> None:
    item = copy.deepcopy(item)
    top_level = destination.container_path is None
    if top_level:
        if item.get("type") == "launcher":
            item = launcher_item_to_top_launcher(item)
        elif item.get("type") == "submenu":
            item["type"] = "menu"
        item = validate_menu(item, top_level=True)
        siblings = toolbar_config.setdefault("menus", [])
    else:
        container = item_at_path(toolbar_config, destination.container_path)
        if container is None or container.get("type") not in {"menu", "submenu"}:
            raise ValueError("Destination menu no longer exists.")
        if item.get("type") == "top_launcher":
            item = top_launcher_to_launcher_item(item)
        elif item.get("type") == "menu":
            item["type"] = "submenu"
        item = validate_item(item)
        siblings = container.setdefault("items", [])

    index = insertion_index(toolbar_config, siblings, destination)
    siblings.insert(index, item)


def insertion_index(toolbar_config: dict, siblings: list[dict], destination: TransferDestination) -> int:
    if destination.position == "beginning":
        return 0
    if destination.position in {"before", "after"} and destination.sibling_path is not None:
        target = parent_list_for_path(toolbar_config, destination.sibling_path)
        if target is not None and target[0] is siblings:
            offset = 0 if destination.position == "before" else 1
            return max(0, min(len(siblings), target[1] + offset))
    return len(siblings)


def clone_item_for_destination(item: dict, context: AssetContext) -> dict:
    clone = copy.deepcopy(item)
    assign_new_ids_recursive(clone)
    copy_referenced_assets(clone, context)
    return clone


def copy_referenced_assets(item: dict, context: AssetContext) -> None:
    for field in ("icon", "icon_path", "image"):
        copy_asset_field(item, field, context)
    for child in item.get("items", []):
        if isinstance(child, dict):
            copy_referenced_assets(child, context)


def copy_asset_field(item: dict, field: str, context: AssetContext) -> None:
    value = str(item.get(field) or "")
    # Skip built-in bundled logos, including the legacy Logo2 asset path kept for compatibility.
    if not value or value in {"img/ToolBar2.png", "img/Logo2.png"}:
        return
    source = resolve_asset_path(value)
    if source is None or not source.exists() or not source.is_file():
        return
    suffix = source.suffix.lower() or ".png"
    if field == "image":
        destination, relative = asset_context_logo_path(context, suffix)
    else:
        item_id = str(item.get("id") or item.get("name") or field)
        destination, relative = asset_context_item_icon_path(context, item_id, field)
        if destination.suffix.lower() != suffix:
            destination = destination.with_suffix(suffix)
            relative = str(destination.relative_to(app_base_path())).replace("\\", "/")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    item[field] = relative


def resolve_asset_path(value: str) -> Path | None:
    normalized = value.replace("\\", "/")
    try:
        if normalized.startswith("user_profiles/"):
            return resolve_profile_owned_asset_path(normalized)
    except ValueError:
        return None
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    if path.is_absolute():
        return path
    return app_base_path() / normalized


def destination_containers(toolbar_config: dict) -> list[tuple[str, list[int]]]:
    containers: list[tuple[str, list[int]]] = []
    for index, menu in enumerate(toolbar_config.get("menus", [])):
        if menu.get("type") in {"menu", "submenu"}:
            collect_container(menu, [index], str(menu.get("name") or "Menu"), containers)
    return containers


def collect_container(item: dict, path: list[int], label: str, containers: list[tuple[str, list[int]]]) -> None:
    containers.append((label, path.copy()))
    for index, child in enumerate(item.get("items", [])):
        if isinstance(child, dict) and child.get("type") == "submenu":
            collect_container(child, [*path, index], f"{label} > {child.get('name', 'Submenu')}", containers)


def sibling_positions(toolbar_config: dict, container_path: list[int] | None) -> list[tuple[str, str, list[int] | None]]:
    positions: list[tuple[str, str, list[int] | None]] = [
        ("Add to end", "end", None),
        ("Add to beginning", "beginning", None),
    ]
    siblings = toolbar_config.get("menus", []) if container_path is None else (item_at_path(toolbar_config, container_path) or {}).get("items", [])
    base = [] if container_path is None else container_path
    if isinstance(siblings, list):
        for index, item in enumerate(siblings):
            name = str(item.get("name") or "Item") if isinstance(item, dict) else "Item"
            path = [*base, index]
            positions.append((f"Insert before {name}", "before", path))
            positions.append((f"Insert after {name}", "after", path))
    return positions
