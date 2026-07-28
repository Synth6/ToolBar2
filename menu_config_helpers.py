from __future__ import annotations

import copy
import uuid

from config_manager import validate_button_style, validate_item, validate_menu


def top_launcher_to_launcher_item(launcher_config: dict) -> dict:
    launcher = copy.deepcopy(launcher_config)
    launcher["type"] = "launcher"
    launcher["icon"] = str(launcher_config.get("icon_path") or launcher_config.get("icon") or "")
    for field in ("icon_path", "icon_only", "button_style", "icon_managed", "items"):
        launcher.pop(field, None)
    return validate_item(launcher)


def top_launcher_to_editor_item(
    launcher_config: dict,
    button_fallbacks: dict[str, str] | None = None,
) -> dict:
    launcher = copy.deepcopy(launcher_config)
    launcher["type"] = "launcher"
    launcher["icon"] = str(launcher_config.get("icon_path") or launcher_config.get("icon") or "")
    launcher.pop("items", None)
    if "button_style" in launcher or button_fallbacks is not None:
        fallbacks = button_fallbacks or {
            "background": "#3b3b3b",
            "hover": "#505050",
            "text": "#ffffff",
            "border": "#606060",
        }
        launcher["button_style"] = validate_button_style(
            launcher.get("button_style"),
            fallbacks,
        )
    launcher.pop("icon_path", None)
    return validate_item(launcher)


def launcher_item_to_top_launcher(
    launcher: dict,
    existing_top_launcher: dict | None = None,
    button_fallbacks: dict[str, str] | None = None,
) -> dict:
    existing = existing_top_launcher or {}
    top_launcher = {
        **copy.deepcopy(existing),
        **copy.deepcopy(launcher),
        "id": launcher.get("id") or existing.get("id", ""),
        "name": launcher.get("name", "Launcher"),
        "type": "top_launcher",
        "target": launcher.get("target", ""),
        "target_type": launcher.get("target_type", "Auto Detect"),
        "arguments": launcher.get("arguments", ""),
        "working_directory": launcher.get("working_directory", ""),
        "python_mode": launcher.get("python_mode", "Automatic"),
        "enabled": bool(launcher.get("enabled", True)),
        "accept_dropped_files": bool(launcher.get("accept_dropped_files", False)),
        "folder_drop_action": launcher.get("folder_drop_action", existing.get("folder_drop_action", "move")),
        "icon_path": launcher.get("icon", existing.get("icon_path", "")),
        "icon_only": bool(launcher.get("icon_only", existing.get("icon_only", False))),
        "button_style": copy.deepcopy(launcher.get("button_style", existing.get("button_style", {}))),
        "items": [],
    }
    top_launcher.pop("icon", None)
    return validate_menu(top_launcher, top_level=True, button_fallbacks=button_fallbacks)


def list_menu_destinations(config: dict) -> list[dict]:
    destinations: list[dict] = []
    for index, menu in enumerate(config.get("menus", [])):
        collect_menu_destinations(menu, [index], menu.get("name", "Menu"), destinations)
    return destinations


def collect_menu_destinations(
    item: dict,
    path: list[int],
    label: str,
    destinations: list[dict],
) -> None:
    if item.get("type") not in {"menu", "submenu"} or not bool(item.get("enabled", True)):
        return
    destinations.append(
        {
            "label": label,
            "path": path.copy(),
            "id": str(item.get("id") or ""),
        }
    )
    for index, child in enumerate(item.get("items", [])):
        if child.get("type") == "submenu":
            collect_menu_destinations(
                child,
                [*path, index],
                f"{label} > {child.get('name', 'Submenu')}",
                destinations,
            )


def item_at_config_path(config: dict, path: list[int]) -> dict | None:
    if not path:
        return None
    try:
        item = config["menus"][path[0]]
        for index in path[1:]:
            item = item["items"][index]
        return item
    except (IndexError, KeyError, TypeError):
        return None


def config_path_for_item_id(config: dict, item_id: str) -> list[int] | None:
    if not item_id:
        return None
    for index, menu in enumerate(config.get("menus", [])):
        if menu.get("id") == item_id:
            return [index]
        path = config_path_for_item_id_in_items(menu.get("items", []), item_id, [index])
        if path is not None:
            return path
    return None


def config_path_for_item_id_in_items(items: list[dict], item_id: str, parent_path: list[int]) -> list[int] | None:
    for index, item in enumerate(items):
        path = [*parent_path, index]
        if item.get("id") == item_id:
            return path
        if item.get("type") == "submenu":
            found = config_path_for_item_id_in_items(item.get("items", []), item_id, path)
            if found is not None:
                return found
    return None


def valid_menu_destination_at_path(config: dict, destination_path: list[int], destination_id: str = "") -> bool:
    destination = item_at_config_path(config, destination_path)
    if destination is None:
        return False
    if destination.get("type") not in {"menu", "submenu"} or not bool(destination.get("enabled", True)):
        return False
    if destination_id and str(destination.get("id") or "") != destination_id:
        return False
    return True


def insert_launcher_items(config: dict, destination_path: list[int], items: list[dict]) -> bool:
    if destination_path == [-1]:
        config.setdefault("menus", []).extend(
            launcher_item_to_top_launcher(item) if item.get("type") == "launcher" else item
            for item in items
        )
        return True
    destination = item_at_config_path(config, destination_path)
    if destination is None or destination.get("type") not in {"menu", "submenu"}:
        return False
    destination.setdefault("items", []).extend(
        top_launcher_to_launcher_item(item) if item.get("type") == "top_launcher" else validate_item(item)
        for item in items
    )
    return True


def find_menu_index_by_id(config: dict, menu_id: str) -> int:
    for index, menu in enumerate(config.get("menus", [])):
        if menu.get("id") == menu_id:
            return index
    return -1


def find_menu_by_id(config: dict, menu_id: str) -> dict | None:
    index = find_menu_index_by_id(config, menu_id)
    if index < 0:
        return None
    return config["menus"][index]


def move_menu_by_id(config: dict, menu_id: str, offset: int) -> bool:
    menus = config.get("menus", [])
    index = find_menu_index_by_id(config, menu_id)
    new_index = index + offset
    if index < 0 or not 0 <= new_index < len(menus):
        return False
    menus[index], menus[new_index] = menus[new_index], menus[index]
    return True


def delete_menu_by_id(config: dict, menu_id: str) -> bool:
    index = find_menu_index_by_id(config, menu_id)
    if index < 0:
        return False
    config.get("menus", []).pop(index)
    return True


def duplicate_menu_by_id(config: dict, menu_id: str) -> dict | None:
    index = find_menu_index_by_id(config, menu_id)
    if index < 0:
        return None
    duplicate = copy.deepcopy(config["menus"][index])
    assign_new_ids_recursive(duplicate)
    duplicate["name"] = f"{duplicate.get('name', 'Menu')} Copy"
    config["menus"].insert(index + 1, duplicate)
    return duplicate


def count_nested_descendants(item: dict) -> int:
    total = 0
    for child in item.get("items", []):
        total += 1
        if child.get("type") == "submenu":
            total += count_nested_descendants(child)
    return total


def find_item_location(config: dict, item_id: str) -> dict | None:
    menus = config.get("menus", [])
    for index, menu in enumerate(menus):
        if menu.get("id") == item_id:
            return {"item": menu, "parent": None, "items": menus, "index": index, "top_menu": menu}
        found = find_item_location_in_children(menu, menu.get("items", []), item_id, menu)
        if found is not None:
            return found
    return None


def find_item_location_in_children(parent: dict, items: list[dict], item_id: str, top_menu: dict) -> dict | None:
    for index, item in enumerate(items):
        if item.get("id") == item_id:
            return {"item": item, "parent": parent, "items": items, "index": index, "top_menu": top_menu}
        if item.get("type") == "submenu":
            found = find_item_location_in_children(item, item.get("items", []), item_id, top_menu)
            if found is not None:
                return found
    return None


def find_any_item_by_id(config: dict, item_id: str) -> dict | None:
    location = find_item_location(config, item_id)
    if location is not None:
        return location["item"]
    return find_logo_item_by_id(config, item_id)


def find_logo_item_by_id(config: dict, item_id: str) -> dict | None:
    items = config.get("logo", {}).get("menu_items", [])
    return find_item_in_nested_list(items, item_id)


def find_item_in_nested_list(items: list[dict], item_id: str) -> dict | None:
    for item in items:
        if item.get("id") == item_id:
            return item
        if item.get("type") == "submenu":
            found = find_item_in_nested_list(item.get("items", []), item_id)
            if found is not None:
                return found
    return None


def find_parent_container_by_id(config: dict, item_id: str) -> dict | None:
    location = find_item_location(config, item_id)
    return location["parent"] if location else None


def find_item_index_by_id(config: dict, item_id: str) -> int:
    location = find_item_location(config, item_id)
    return int(location["index"]) if location else -1


def find_top_menu_containing_item(config: dict, item_id: str) -> dict | None:
    location = find_item_location(config, item_id)
    return location["top_menu"] if location else None


def replace_item_by_id(config: dict, item_id: str, replacement: dict) -> bool:
    location = find_item_location(config, item_id)
    if location is None:
        return False
    replacement = copy.deepcopy(replacement)
    replacement["id"] = item_id
    location["items"][location["index"]] = replacement
    return True


def delete_item_by_id(config: dict, item_id: str) -> bool:
    location = find_item_location(config, item_id)
    if location is None or location["parent"] is None:
        return False
    location["items"].pop(location["index"])
    return True


def move_item_by_id(config: dict, item_id: str, offset: int) -> bool:
    location = find_item_location(config, item_id)
    if location is None:
        return False
    items = location["items"]
    index = location["index"]
    new_index = index + offset
    if not 0 <= new_index < len(items):
        return False
    items[index], items[new_index] = items[new_index], items[index]
    return True


def duplicate_item_by_id(config: dict, item_id: str) -> dict | None:
    location = find_item_location(config, item_id)
    if location is None or location["parent"] is None:
        return None
    duplicate = copy.deepcopy(location["item"])
    assign_new_ids_recursive(duplicate)
    if "name" in duplicate:
        duplicate["name"] = f"{duplicate['name']} Copy"
    location["items"].insert(location["index"] + 1, duplicate)
    return duplicate


def assign_new_ids_recursive(item: dict) -> None:
    item["id"] = str(uuid.uuid4())
    for child in item.get("items", []):
        assign_new_ids_recursive(child)


def add_launcher_to_container_by_id(config: dict, container_id: str, launcher: dict) -> bool:
    item = top_launcher_to_launcher_item(launcher) if launcher.get("type") == "top_launcher" else validate_item(launcher)
    return add_item_to_container_by_id(config, container_id, item)


def add_submenu_to_container_by_id(config: dict, container_id: str, name: str) -> bool:
    return add_item_to_container_by_id(config, container_id, validate_item({"type": "submenu", "name": name, "items": []}))


def add_heading_to_container_by_id(config: dict, container_id: str, name: str) -> bool:
    return add_item_to_container_by_id(config, container_id, validate_item({"type": "heading", "name": name}))


def add_separator_to_container_by_id(config: dict, container_id: str) -> bool:
    return add_item_to_container_by_id(config, container_id, validate_item({"type": "separator"}))


def add_item_to_container_by_id(config: dict, container_id: str, item: dict) -> bool:
    location = find_item_location(config, container_id)
    container = location["item"] if location is not None else None
    if container is None or container.get("type") not in {"menu", "submenu"}:
        return False
    container.setdefault("items", []).append(item)
    return True


def toggle_item_enabled_by_id(config: dict, item_id: str) -> bool:
    location = find_item_location(config, item_id)
    item = location["item"] if location is not None else None
    if item is None or item.get("type") not in {"menu", "submenu", "launcher"}:
        return False
    item["enabled"] = not bool(item.get("enabled", True))
    return True
