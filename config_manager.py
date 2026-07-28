from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

ITEM_TYPES = {"menu", "submenu", "folder_menu", "launcher", "separator", "heading"}
LAUNCH_TARGET_TYPES = {
    "Auto Detect",
    "Program",
    "Command Script",
    "PowerShell Script",
    "Python Script",
    "File",
    "Folder",
    "Website",
}
PYTHON_MODES = {"Automatic", "Console Python", "Windowed Python"}
LOGO_LEFT_CLICK_ACTIONS = {"none", "open_menu", "open_first_item", "custom_launcher"}
FOLDER_DROP_ACTIONS = {"move", "copy", "ask"}
CONFIG_VERSION = 3
MONITORING_MODES = {"single", "selected_shared", "all_shared", "per_monitor"}
DEFAULT_LOGO_IMAGE = "img/ToolBar2.png"
MANAGED_ICON_DIR = "icons"
MANAGED_LOGO_IMAGE = "icons/LOGO.png"
USER_PROFILES_DIR = "user_profiles"
OLD_MANAGED_ICON_PREFIXES = ("icons/menu_icons/", "icons/launcher_icons/")

DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": CONFIG_VERSION,
    "active_user_profile_id": "",
    "user_profile_name": "Default",
    "user_profile_description": "",
    "monitoring": {
        "mode": "single",
        "selected_monitor_ids": [],
        "known_monitors": {},
    },
    "toolbar_profiles": {},
    "unmapped_monitor_profiles": [],
    "saved_toolbar_profiles": [],
    "application": {
        "start_with_windows": False,
    },
    "appearance": {
        "toolbar_background": "#202020",
        "button_background": "#3b3b3b",
        "button_hover": "#505050",
        "button_text": "#ffffff",
        "menu_background": "#2c2c2c",
        "menu_text": "#ffffff",
        "border_color": "#606060",
        "opacity": 0.95,
        "toolbar_height": 40,
        "button_height": 36,
        "corner_radius": 6,
        "horizontal_padding": 8,
        "vertical_padding": 4,
        "menu_button_spacing": 10,
        "menu_alignment": "center",
        "auto_toolbar_width": False,
        "toolbar_width": 1000,
        "horizontal_alignment": "center",
        "horizontal_offset": 0,
        "show_settings_button": True,
        "show_exit_button": False,
        "show_web_search_bar": False,
        "web_search_width": 180,
        "web_search_placeholder": "Search the web...",
        "web_search_engine": "Google",
        "web_search_custom_url": "",
        "web_search_position": -1,
    },
    "behavior": {
        "screen_index": 0,
        "screen_name": "",
        "screen_geometry": [],
        "trigger_height": 5,
        "hide_delay_ms": 750,
        "animation_duration_ms": 200,
        "open_menus_on_hover": True,
        "menu_hover_delay_ms": 200,
        "confirm_before_exit": False,
    },
    "logo": {
        "visible": True,
        "image": DEFAULT_LOGO_IMAGE,
        "height": 48,
        "maximum_width": 640,
        "opacity": 1.0,
        "preserve_aspect_ratio": True,
        "tooltip": "ToolBar2 by Ron",
        "left_click_action": "none",
        "left_click_launcher": None,
        "menu_items": [],
    },
    "menus": [
        {
            "id": "",
            "name": "Tools",
            "type": "menu",
            "items": [],
        }
    ],
}


def app_base_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(relative_path: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", app_base_path()))
    return str(base / relative_path)


def config_file_path() -> Path:
    return app_base_path() / "toolbar_config.json"


def backup_file_path() -> Path:
    return app_base_path() / "toolbar_config.backup.json"


def user_profiles_dir() -> Path:
    return app_base_path() / USER_PROFILES_DIR


def user_profile_staging_dir(session_id: str) -> Path:
    return user_profiles_dir() / ".staging" / safe_profile_id(session_id)


def user_profile_staging_icons_relative_dir(
    session_id: str,
    profile_id: str,
    monitor_profile_id: str | None = None,
) -> Path:
    safe_session_id = safe_profile_id(session_id)
    safe_user_id = safe_profile_id(profile_id)
    if not safe_session_id or not safe_user_id:
        raise ValueError("Valid staging session and user profile IDs are required.")
    base = Path(USER_PROFILES_DIR) / ".staging" / safe_session_id / safe_user_id
    if monitor_profile_id:
        safe_monitor_id = safe_profile_id(monitor_profile_id)
        if not safe_monitor_id:
            raise ValueError("A valid monitor profile ID is required.")
        return base / "monitor_profiles" / safe_monitor_id / "icons"
    return base / "shared" / "icons"


def delete_staging_session(session_id: str) -> None:
    safe_session_id = safe_profile_id(session_id)
    if not safe_session_id:
        return
    try:
        shutil.rmtree(user_profile_staging_dir(safe_session_id))
    except FileNotFoundError:
        return
    except OSError:
        logger.debug("failed to delete staging session %s", safe_session_id, exc_info=True)


def user_profile_dir(profile_id: str) -> Path:
    return user_profiles_dir() / safe_profile_id(profile_id)


def user_profile_json_path(profile_id: str) -> Path:
    return user_profile_dir(profile_id) / "profile.json"


def user_profile_shared_icons_relative_dir(profile_id: str) -> Path:
    safe_user_id = safe_profile_id(profile_id)
    if not safe_user_id:
        raise ValueError("A valid user profile ID is required.")
    return Path(USER_PROFILES_DIR) / safe_user_id / "shared" / "icons"


def user_profile_monitor_icons_relative_dir(profile_id: str, monitor_profile_id: str) -> Path:
    safe_user_id = safe_profile_id(profile_id)
    safe_monitor_id = safe_profile_id(monitor_profile_id)
    if not safe_user_id or not safe_monitor_id:
        raise ValueError("Valid user and monitor profile IDs are required.")
    return Path(USER_PROFILES_DIR) / safe_user_id / "monitor_profiles" / safe_monitor_id / "icons"


def user_profile_icons_relative_dir(profile_id: str, monitor_profile_id: str | None = None) -> Path:
    if monitor_profile_id:
        return user_profile_monitor_icons_relative_dir(profile_id, monitor_profile_id)
    return user_profile_shared_icons_relative_dir(profile_id)


def user_profile_icons_dir(profile_id: str, monitor_profile_id: str | None = None) -> Path:
    return app_base_path() / user_profile_icons_relative_dir(profile_id, monitor_profile_id)


def user_profile_logo_relative_path(profile_id: str, suffix: str, monitor_profile_id: str | None = None) -> str:
    normalized_suffix = suffix.lower()
    if normalized_suffix not in {".png", ".gif"}:
        normalized_suffix = ".png"
    return str(user_profile_icons_relative_dir(profile_id, monitor_profile_id) / f"LOGO{normalized_suffix}").replace("\\", "/")


def user_profile_item_icon_relative_path(
    profile_id: str,
    item_id: str,
    monitor_profile_id: str | None = None,
    fallback_name: str = "icon",
) -> str:
    safe_id = safe_icon_id(item_id) or fallback_name
    return str(user_profile_icons_relative_dir(profile_id, monitor_profile_id) / f"{safe_id}.png").replace("\\", "/")


def resolve_profile_owned_asset_path(path_text: str) -> Path:
    normalized = str(path_text or "").replace("\\", "/")
    if not normalized.startswith(f"{USER_PROFILES_DIR}/"):
        raise ValueError("Path is not a user profile asset path.")
    resolved = (app_base_path() / normalized).resolve()
    root = user_profiles_dir().resolve()
    try:
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("User profile asset path escapes user_profiles.") from exc
    return resolved


def managed_icons_dir() -> Path:
    return app_base_path() / MANAGED_ICON_DIR


def default_config() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_CONFIG)


def clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


def clamp_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


def normalize_hex_color(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    text = value.strip()
    if len(text) != 7 or not text.startswith("#"):
        return fallback
    try:
        int(text[1:], 16)
    except ValueError:
        return fallback
    return text.lower()


def validate_config(
    config: Any,
    screen_count: int | None = None,
    connected_monitor_ids: list[str] | None = None,
) -> dict[str, Any]:
    defaults = default_config()
    source = config if isinstance(config, dict) else {}
    defaults["config_version"] = CONFIG_VERSION
    defaults["active_user_profile_id"] = safe_profile_id(str(source.get("active_user_profile_id") or ""))
    defaults["user_profile_name"] = str(source.get("user_profile_name") or defaults["user_profile_name"])
    defaults["user_profile_description"] = str(source.get("user_profile_description") or "")

    application = source.get("application", {})
    if not isinstance(application, dict):
        application = {}
    defaults["application"] = preserve_future_fields(application)
    defaults["application"]["start_with_windows"] = bool(
        application.get(
            "start_with_windows",
            DEFAULT_CONFIG["application"]["start_with_windows"],
        )
    )

    appearance = source.get("appearance", {})
    if not isinstance(appearance, dict):
        appearance = {}

    for key in (
        "toolbar_background",
        "button_background",
        "button_hover",
        "button_text",
        "menu_background",
        "menu_text",
        "border_color",
    ):
        defaults["appearance"][key] = normalize_hex_color(
            appearance.get(key),
            defaults["appearance"][key],
        )

    defaults["appearance"]["opacity"] = clamp_float(
        appearance.get("opacity"),
        0.00,
        1.00,
        defaults["appearance"]["opacity"],
    )
    defaults["appearance"]["toolbar_height"] = clamp_int(
        appearance.get("toolbar_height"),
        16,
        240,
        defaults["appearance"]["toolbar_height"],
    )
    defaults["appearance"]["button_height"] = clamp_int(
        appearance.get("button_height"),
        12,
        96,
        defaults["appearance"]["button_height"],
    )
    defaults["appearance"]["corner_radius"] = clamp_int(
        appearance.get("corner_radius"),
        0,
        24,
        defaults["appearance"]["corner_radius"],
    )
    defaults["appearance"]["horizontal_padding"] = clamp_int(
        appearance.get("horizontal_padding"),
        0,
        100,
        defaults["appearance"]["horizontal_padding"],
    )
    defaults["appearance"]["vertical_padding"] = clamp_int(
        appearance.get("vertical_padding"),
        0,
        60,
        defaults["appearance"]["vertical_padding"],
    )
    defaults["appearance"]["menu_button_spacing"] = clamp_int(
        appearance.get("menu_button_spacing"),
        0,
        50,
        defaults["appearance"]["menu_button_spacing"],
    )
    defaults["appearance"]["menu_alignment"] = normalize_choice(
        str(appearance.get("menu_alignment") or "center"),
        {"left", "center", "right"},
        "center",
    )
    defaults["appearance"]["auto_toolbar_width"] = bool(
        appearance.get(
            "auto_toolbar_width",
            defaults["appearance"]["auto_toolbar_width"],
        )
    )
    defaults["appearance"]["toolbar_width"] = clamp_int(
        appearance.get("toolbar_width"),
        300,
        3000,
        defaults["appearance"]["toolbar_width"],
    )
    defaults["appearance"]["horizontal_alignment"] = normalize_choice(
        str(appearance.get("horizontal_alignment") or "center"),
        {"left", "center", "right"},
        "center",
    )
    defaults["appearance"]["horizontal_offset"] = clamp_int(
        appearance.get("horizontal_offset"),
        -3000,
        3000,
        defaults["appearance"]["horizontal_offset"],
    )
    defaults["appearance"]["show_settings_button"] = bool(
        appearance.get(
            "show_settings_button",
            defaults["appearance"]["show_settings_button"],
        )
    )
    defaults["appearance"]["show_exit_button"] = bool(
        appearance.get(
            "show_exit_button",
            defaults["appearance"]["show_exit_button"],
        )
    )
    # Legacy customer-search keys still migrate forward so older saved configs load cleanly.
    defaults["appearance"]["show_web_search_bar"] = bool(
        appearance.get(
            "show_web_search_bar",
            appearance.get(
                "show_customer_search_bar",
                defaults["appearance"]["show_web_search_bar"],
            ),
        )
    )
    defaults["appearance"]["web_search_width"] = clamp_int(
        appearance.get("web_search_width", appearance.get("customer_search_width")),
        100,
        500,
        defaults["appearance"]["web_search_width"],
    )
    defaults["appearance"]["web_search_placeholder"] = str(
        appearance.get(
            "web_search_placeholder",
            appearance.get(
                "customer_search_placeholder",
                defaults["appearance"]["web_search_placeholder"],
            ),
        )
        or defaults["appearance"]["web_search_placeholder"]
    )
    defaults["appearance"]["web_search_engine"] = normalize_choice(
        str(appearance.get("web_search_engine") or "Google"),
        {"Google", "Bing", "DuckDuckGo", "Yahoo", "Custom"},
        defaults["appearance"]["web_search_engine"],
    )
    defaults["appearance"]["web_search_custom_url"] = str(
        appearance.get(
            "web_search_custom_url",
            defaults["appearance"]["web_search_custom_url"],
        )
        or ""
    )
    defaults["appearance"]["web_search_position"] = clamp_int(
        appearance.get("web_search_position", appearance.get("customer_search_position")),
        -1,
        999,
        defaults["appearance"]["web_search_position"],
    )

    defaults["logo"] = validate_logo(
        source.get("logo"),
        fallback_height=DEFAULT_CONFIG["logo"]["height"],
    )

    behavior = source.get("behavior", {})
    if not isinstance(behavior, dict):
        behavior = {}

    max_screen_index = max(0, screen_count - 1) if screen_count is not None else 32
    screen_index = clamp_int(
        behavior.get("screen_index"),
        0,
        max_screen_index,
        defaults["behavior"]["screen_index"],
    )
    defaults["behavior"]["screen_index"] = screen_index
    defaults["behavior"]["screen_name"] = str(behavior.get("screen_name") or "")
    screen_geometry = behavior.get("screen_geometry", [])
    if not isinstance(screen_geometry, list):
        screen_geometry = []
    defaults["behavior"]["screen_geometry"] = [
        clamp_int(item, -100000, 100000, 0)
        for item in screen_geometry[:4]
    ]
    defaults["behavior"]["trigger_height"] = clamp_int(
        behavior.get("trigger_height"),
        1,
        30,
        defaults["behavior"]["trigger_height"],
    )
    defaults["behavior"]["hide_delay_ms"] = clamp_int(
        behavior.get("hide_delay_ms"),
        100,
        5000,
        defaults["behavior"]["hide_delay_ms"],
    )
    defaults["behavior"]["animation_duration_ms"] = clamp_int(
        behavior.get("animation_duration_ms"),
        0,
        2000,
        defaults["behavior"]["animation_duration_ms"],
    )
    defaults["behavior"]["open_menus_on_hover"] = bool(
        behavior.get(
            "open_menus_on_hover",
            defaults["behavior"]["open_menus_on_hover"],
        )
    )
    defaults["behavior"]["menu_hover_delay_ms"] = clamp_int(
        behavior.get("menu_hover_delay_ms"),
        0,
        1000,
        defaults["behavior"]["menu_hover_delay_ms"],
    )
    defaults["behavior"]["confirm_before_exit"] = bool(
        behavior.get(
            "confirm_before_exit",
            defaults["behavior"]["confirm_before_exit"],
        )
    )

    defaults["monitoring"] = validate_monitoring(
        source.get("monitoring"),
        connected_monitor_ids,
        defaults["behavior"]["screen_index"],
    )
    defaults["behavior"]["screen_index"] = synchronized_screen_index(
        defaults["monitoring"]["selected_monitor_ids"],
        defaults["behavior"]["screen_index"],
        screen_count,
        connected_monitor_ids,
    )

    menus = source.get("menus")
    if isinstance(menus, list):
        button_fallbacks = {
            "background": defaults["appearance"]["button_background"],
            "hover": defaults["appearance"]["button_hover"],
            "text": defaults["appearance"]["button_text"],
            "border": defaults["appearance"]["border_color"],
        }
        validated_menus = [
            validate_menu(menu, top_level=True, button_fallbacks=button_fallbacks)
            for menu in menus
            if isinstance(menu, dict)
        ]
        defaults["menus"] = validated_menus
    if defaults["appearance"]["web_search_position"] != -1:
        defaults["appearance"]["web_search_position"] = max(
            0,
            min(
                defaults["appearance"]["web_search_position"],
                len(defaults["menus"]),
            ),
        )

    defaults["toolbar_profiles"] = validate_toolbar_profiles(defaults, source.get("toolbar_profiles"))
    defaults["unmapped_monitor_profiles"] = validate_unmapped_monitor_profiles(
        defaults,
        source.get("unmapped_monitor_profiles"),
    )
    defaults["saved_toolbar_profiles"] = validate_saved_toolbar_profiles(defaults, source.get("saved_toolbar_profiles"))
    return defaults


TOOLBAR_PROFILE_BEHAVIOR_KEYS = {
    "trigger_height",
    "hide_delay_ms",
    "animation_duration_ms",
    "open_menus_on_hover",
    "menu_hover_delay_ms",
}


def saved_toolbar_profile_from_toolbar(
    toolbar_config: dict[str, Any],
    name: str,
    description: str = "",
    profile_id: str | None = None,
) -> dict[str, Any]:
    validated = validate_config(
        {
            "appearance": toolbar_config.get("appearance", {}),
            "behavior": toolbar_config.get("behavior", {}),
            "logo": toolbar_config.get("logo", {}),
            "menus": toolbar_config.get("menus", []),
            "toolbar_profiles": {},
            "saved_toolbar_profiles": [],
        }
    )
    return validate_saved_toolbar_profile(
        {
            "profile_id": profile_id or new_profile_id(),
            "name": name,
            "description": description,
            "appearance": validated["appearance"],
            "behavior": {
                key: validated["behavior"][key]
                for key in TOOLBAR_PROFILE_BEHAVIOR_KEYS
            },
            "logo": validated["logo"],
            "menus": validated["menus"],
        }
    )


def validate_saved_toolbar_profiles(config: dict[str, Any], value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    profiles: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    used_names: set[str] = set()
    for raw_profile in value:
        if not isinstance(raw_profile, dict):
            continue
        profile = validate_saved_toolbar_profile(raw_profile, used_ids, used_names)
        used_ids.add(profile["profile_id"])
        used_names.add(profile["name"].casefold())
        profiles.append(profile)
    return profiles


def validate_saved_toolbar_profile(
    value: dict[str, Any],
    used_ids: set[str] | None = None,
    used_names: set[str] | None = None,
) -> dict[str, Any]:
    defaults = default_config()
    used_profile_ids = used_ids or set()
    profile_id = safe_profile_id(str(value.get("profile_id") or ""))
    while not profile_id or profile_id in used_profile_ids:
        profile_id = new_profile_id()

    base_name = str(value.get("name") or "Saved Toolbar Profile").strip() or "Saved Toolbar Profile"
    name = unique_saved_profile_name(base_name, used_names or set())
    section_config = validate_config(
        {
            "appearance": value.get("appearance", defaults["appearance"]),
            "behavior": {
                **defaults["behavior"],
                **(value.get("behavior", {}) if isinstance(value.get("behavior"), dict) else {}),
            },
            "logo": value.get("logo", defaults["logo"]),
            "menus": value.get("menus", defaults["menus"]),
            "toolbar_profiles": {},
            "saved_toolbar_profiles": [],
        }
    )
    return {
        "profile_id": profile_id,
        "name": name,
        "description": str(value.get("description") or ""),
        "appearance": section_config["appearance"],
        "behavior": {
            key: section_config["behavior"][key]
            for key in TOOLBAR_PROFILE_BEHAVIOR_KEYS
        },
        "logo": section_config["logo"],
        "menus": section_config["menus"],
    }


def unique_saved_profile_name(name: str, used_names: set[str]) -> str:
    candidate = name.strip() or "Saved Toolbar Profile"
    if candidate.casefold() not in used_names:
        return candidate
    index = 2
    while f"{candidate} {index}".casefold() in used_names:
        index += 1
    return f"{candidate} {index}"


def validate_toolbar_profiles(config: dict[str, Any], value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    profiles: dict[str, dict[str, Any]] = {}
    used_profile_ids: set[str] = set()
    for monitor_key, raw_profile in value.items():
        monitor_id = str(monitor_key or "").strip()
        if not monitor_id or not isinstance(raw_profile, dict):
            continue
        profile = validate_toolbar_profile(config, raw_profile, used_profile_ids)
        used_profile_ids.add(profile["profile_id"])
        profiles[monitor_id] = profile
    return profiles


def validate_toolbar_profile(
    config: dict[str, Any],
    profile: dict[str, Any],
    used_profile_ids: set[str] | None = None,
) -> dict[str, Any]:
    validated = preserve_future_fields(profile)
    used = used_profile_ids or set()
    profile_id = safe_profile_id(str(profile.get("profile_id") or ""))
    while not profile_id or profile_id in used:
        profile_id = new_profile_id()
    section_config = validate_config(
        {
            "config_version": CONFIG_VERSION,
            "monitoring": config.get("monitoring", {}),
            "appearance": profile.get("appearance", config.get("appearance", {})),
            "behavior": profile.get("behavior", config.get("behavior", {})),
            "logo": profile.get("logo", config.get("logo", {})),
            "menus": profile.get("menus", config.get("menus", [])),
            "toolbar_profiles": {},
        }
    )
    validated["profile_id"] = profile_id
    validated["appearance"] = section_config["appearance"]
    validated["behavior"] = section_config["behavior"]
    validated["logo"] = section_config["logo"]
    validated["menus"] = section_config["menus"]
    return validated


def validate_unmapped_monitor_profiles(config: dict[str, Any], value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    profiles: list[dict[str, Any]] = []
    used_profile_ids: set[str] = {
        str(profile.get("profile_id") or "")
        for profile in config.get("toolbar_profiles", {}).values()
        if isinstance(profile, dict)
    }
    for item in value:
        if not isinstance(item, dict):
            continue
        toolbar = item.get("toolbar")
        if not isinstance(toolbar, dict):
            continue
        profile = validate_toolbar_profile(config, toolbar, used_profile_ids)
        used_profile_ids.add(profile["profile_id"])
        metadata = item.get("source_monitor_metadata", {})
        profiles.append(
            {
                "source_monitor_id": str(item.get("source_monitor_id") or ""),
                "source_monitor_metadata": copy.deepcopy(metadata) if isinstance(metadata, dict) else {},
                "toolbar": profile,
            }
        )
    return profiles


def new_profile_id() -> str:
    return f"profile_{uuid.uuid4().hex[:12]}"


def safe_profile_id(value: str) -> str:
    text = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
    return text[:80]


def ensure_monitor_profile(config: dict[str, Any], monitor_id: str) -> dict[str, Any]:
    monitor_key = str(monitor_id or "").strip()
    if not monitor_key:
        raise ValueError("A monitor ID is required.")
    profiles = config.setdefault("toolbar_profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
        config["toolbar_profiles"] = profiles
    existing = profiles.get(monitor_key)
    if isinstance(existing, dict):
        profile = validate_toolbar_profile(config, existing, profile_ids_used_by_others(config, monitor_key))
        profiles[monitor_key] = profile
        return profile
    return create_monitor_profile(config, monitor_key)


def create_monitor_profile(config: dict[str, Any], monitor_id: str) -> dict[str, Any]:
    profile_id = unique_profile_id(config)
    logger.debug("profile creation monitor_id=%s profile_id=%s", monitor_id, profile_id)
    profile = {
        "profile_id": profile_id,
        "appearance": copy.deepcopy(config.get("appearance", DEFAULT_CONFIG["appearance"])),
        "behavior": copy.deepcopy(config.get("behavior", DEFAULT_CONFIG["behavior"])),
        "logo": copy.deepcopy(config.get("logo", DEFAULT_CONFIG["logo"])),
        "menus": copy.deepcopy(config.get("menus", [])),
    }
    isolate_profile_assets(profile, profile_id)
    config.setdefault("toolbar_profiles", {})[monitor_id] = profile
    return profile


def profile_for_monitor(config: dict[str, Any], monitor_id: str) -> dict[str, Any] | None:
    profile = config.get("toolbar_profiles", {}).get(str(monitor_id or ""))
    return profile if isinstance(profile, dict) else None


def effective_config_for_monitor(config: dict[str, Any], monitor_id: str) -> dict[str, Any]:
    effective = copy.deepcopy(config)
    if str(config.get("monitoring", {}).get("mode") or "single") != "per_monitor":
        return effective
    profile = ensure_monitor_profile(effective, monitor_id)
    effective["appearance"] = copy.deepcopy(profile["appearance"])
    effective["behavior"] = copy.deepcopy(profile["behavior"])
    effective["logo"] = copy.deepcopy(profile["logo"])
    effective["menus"] = copy.deepcopy(profile["menus"])
    return effective


def update_monitor_profile(config: dict[str, Any], monitor_id: str, updated_config: dict[str, Any]) -> dict[str, Any]:
    profile = ensure_monitor_profile(config, monitor_id)
    profile.update(
        {
            "appearance": copy.deepcopy(updated_config.get("appearance", profile.get("appearance", {}))),
            "behavior": copy.deepcopy(updated_config.get("behavior", profile.get("behavior", {}))),
            "logo": copy.deepcopy(updated_config.get("logo", profile.get("logo", {}))),
            "menus": copy.deepcopy(updated_config.get("menus", profile.get("menus", []))),
        }
    )
    config.setdefault("toolbar_profiles", {})[monitor_id] = validate_toolbar_profile(
        config,
        profile,
        profile_ids_used_by_others(config, monitor_id),
    )
    return config["toolbar_profiles"][monitor_id]


def copy_monitor_profile(config: dict[str, Any], source_monitor_id: str, target_monitor_id: str) -> dict[str, Any]:
    source = ensure_monitor_profile(config, source_monitor_id)
    old_target = copy.deepcopy(config.get("toolbar_profiles", {}).get(target_monitor_id))
    profile_id = unique_profile_id(config)
    copied = copy.deepcopy(source)
    copied["profile_id"] = profile_id
    logger.debug("profile copy source=%s target=%s profile_id=%s", source_monitor_id, target_monitor_id, profile_id)
    try:
        isolate_profile_assets(copied, profile_id)
        config.setdefault("toolbar_profiles", {})[target_monitor_id] = validate_toolbar_profile(
            config,
            copied,
            profile_ids_used_by_others(config, target_monitor_id),
        )
        return config["toolbar_profiles"][target_monitor_id]
    except Exception:
        if old_target is None:
            config.setdefault("toolbar_profiles", {}).pop(target_monitor_id, None)
        else:
            config.setdefault("toolbar_profiles", {})[target_monitor_id] = old_target
        try:
            shutil.rmtree(profile_asset_directory_by_id(profile_id))
        except OSError:
            logger.debug("failed to clean incomplete profile asset copy", exc_info=True)
        raise


def reset_monitor_profile(config: dict[str, Any], monitor_id: str) -> dict[str, Any]:
    existing = profile_for_monitor(config, monitor_id)
    profile_id = safe_profile_id(str(existing.get("profile_id") or "")) if isinstance(existing, dict) else ""
    profile_id = profile_id or unique_profile_id(config)
    logger.debug("profile reset monitor_id=%s profile_id=%s", monitor_id, profile_id)
    profile = {
        "profile_id": profile_id,
        "appearance": copy.deepcopy(config.get("appearance", DEFAULT_CONFIG["appearance"])),
        "behavior": copy.deepcopy(config.get("behavior", DEFAULT_CONFIG["behavior"])),
        "logo": copy.deepcopy(config.get("logo", DEFAULT_CONFIG["logo"])),
        "menus": copy.deepcopy(config.get("menus", [])),
    }
    isolate_profile_assets(profile, profile_id)
    config.setdefault("toolbar_profiles", {})[monitor_id] = validate_toolbar_profile(
        config,
        profile,
        profile_ids_used_by_others(config, monitor_id),
    )
    return config["toolbar_profiles"][monitor_id]


def unique_profile_id(config: dict[str, Any]) -> str:
    used = {
        str(profile.get("profile_id") or "")
        for profile in config.get("toolbar_profiles", {}).values()
        if isinstance(profile, dict)
    }
    profile_id = new_profile_id()
    while profile_id in used:
        profile_id = new_profile_id()
    return profile_id


def profile_ids_used_by_others(config: dict[str, Any], monitor_id: str) -> set[str]:
    return {
        str(profile.get("profile_id") or "")
        for key, profile in config.get("toolbar_profiles", {}).items()
        if key != monitor_id and isinstance(profile, dict)
    }


def profile_asset_directory(config: dict[str, Any], monitor_id: str) -> Path:
    profile = ensure_monitor_profile(config, monitor_id)
    return profile_asset_directory_by_id(profile["profile_id"])


def profile_asset_directory_by_id(profile_id: str) -> Path:
    return app_base_path() / MANAGED_ICON_DIR / "profiles" / safe_profile_id(profile_id)


def profile_icon_relative_path(profile_id: str, item_id: str, fallback_name: str = "icon") -> str:
    safe_id = safe_icon_id(item_id) or fallback_name
    return str(Path(MANAGED_ICON_DIR) / "profiles" / safe_profile_id(profile_id) / f"{safe_id}.png").replace("\\", "/")


def profile_logo_relative_path(profile_id: str, suffix: str = ".png") -> str:
    return str(Path(MANAGED_ICON_DIR) / "profiles" / safe_profile_id(profile_id) / f"LOGO{suffix.lower()}").replace("\\", "/")


def isolate_profile_assets(profile: dict[str, Any], profile_id: str) -> None:
    logo = profile.get("logo")
    if isinstance(logo, dict):
        image_path = str(logo.get("image") or "")
        if image_path:
            logo["image"] = copy_managed_asset_to_profile(image_path, profile_id, "LOGO")
    for menu in profile.get("menus", []):
        if isinstance(menu, dict):
            isolate_profile_menu_assets(menu, profile_id)


def isolate_profile_menu_assets(menu: dict[str, Any], profile_id: str) -> None:
    if "icon_path" in menu:
        menu["icon_path"] = copy_managed_asset_to_profile(
            str(menu.get("icon_path") or ""),
            profile_id,
            str(menu.get("id") or "menu"),
        )
    if "icon" in menu:
        menu["icon"] = copy_managed_asset_to_profile(
            str(menu.get("icon") or ""),
            profile_id,
            str(menu.get("id") or "menu"),
        )
    for item in menu.get("items", []):
        if isinstance(item, dict):
            isolate_profile_item_assets(item, profile_id)


def isolate_profile_item_assets(item: dict[str, Any], profile_id: str) -> None:
    if "icon" in item:
        item["icon"] = copy_managed_asset_to_profile(
            str(item.get("icon") or ""),
            profile_id,
            str(item.get("id") or "item"),
        )
    if "icon_path" in item:
        item["icon_path"] = copy_managed_asset_to_profile(
            str(item.get("icon_path") or ""),
            profile_id,
            str(item.get("id") or "item"),
        )
    if item.get("type") == "submenu":
        for child in item.get("items", []):
            if isinstance(child, dict):
                isolate_profile_item_assets(child, profile_id)


def copy_managed_asset_to_profile(icon_path: str, profile_id: str, item_id: str) -> str:
    return icon_path


def validate_monitoring(
    value: Any,
    connected_monitor_ids: list[str] | None,
    legacy_screen_index: int,
) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    monitoring = preserve_future_fields(source)
    mode = normalize_choice(str(source.get("mode") or "single"), MONITORING_MODES, "single")
    selected_ids = unique_nonempty_strings(source.get("selected_monitor_ids"))
    if not selected_ids and connected_monitor_ids:
        if 0 <= legacy_screen_index < len(connected_monitor_ids):
            selected_ids = [connected_monitor_ids[legacy_screen_index]]
        else:
            selected_ids = [connected_monitor_ids[0]]
    monitoring["mode"] = mode
    monitoring["selected_monitor_ids"] = selected_ids
    return monitoring


def unique_nonempty_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def synchronized_screen_index(
    selected_monitor_ids: list[str],
    legacy_screen_index: int,
    screen_count: int | None,
    connected_monitor_ids: list[str] | None,
) -> int:
    if connected_monitor_ids:
        for selected_id in selected_monitor_ids:
            try:
                return connected_monitor_ids.index(selected_id)
            except ValueError:
                continue
    max_screen_index = max(0, screen_count - 1) if screen_count is not None else 32
    if 0 <= legacy_screen_index <= max_screen_index:
        return legacy_screen_index
    return 0


def validate_menu(
    menu: dict[str, Any],
    top_level: bool = False,
    button_fallbacks: dict[str, str] | None = None,
) -> dict[str, Any]:
    validated = preserve_future_fields(menu)
    items = menu.get("items", [])
    requested_type = str(menu.get("type") or "").lower()
    if top_level and requested_type == "top_launcher":
        item_type = "top_launcher"
    elif requested_type == "folder_menu":
        item_type = "folder_menu"
    else:
        item_type = "menu" if top_level else "submenu"
    validated.update(
        {
            "name": str(menu.get("name") or ("Menu" if top_level else "Submenu")),
            "type": item_type,
            "items": [validate_item(item) for item in items if isinstance(item, dict)],
            "icon": str(menu.get("icon") or ""),
            "enabled": bool(menu.get("enabled", True)),
            "id": str(menu.get("id") or "").strip() or str(uuid.uuid4()),
        }
    )
    if item_type == "folder_menu":
        validated["folder_path"] = str(menu.get("folder_path") or "")
        validated["include_files"] = bool(menu.get("include_files", True))
        validated["include_folders"] = bool(menu.get("include_folders", True))
        validated["show_open_folder_action"] = bool(menu.get("show_open_folder_action", True))
        validated["items"] = []
    elif item_type == "top_launcher":
        target_type = normalize_choice(str(menu.get("target_type") or "Auto Detect"), LAUNCH_TARGET_TYPES, "Auto Detect")
        validated["target"] = str(menu.get("target") or "")
        validated["target_type"] = target_type
        validated["arguments"] = str(menu.get("arguments") or "")
        validated["working_directory"] = str(menu.get("working_directory") or "")
        validated["python_mode"] = normalize_choice(str(menu.get("python_mode") or "Automatic"), PYTHON_MODES, "Automatic")
        validated["accept_dropped_files"] = bool(menu.get("accept_dropped_files", False))
        validated["folder_drop_action"] = normalize_choice(
            str(menu.get("folder_drop_action") or "move"),
            FOLDER_DROP_ACTIONS,
            "move",
        )
        validated["items"] = []
    if top_level:
        appearance = button_fallbacks or {
            "background": DEFAULT_CONFIG["appearance"]["button_background"],
            "hover": DEFAULT_CONFIG["appearance"]["button_hover"],
            "text": DEFAULT_CONFIG["appearance"]["button_text"],
            "border": DEFAULT_CONFIG["appearance"]["border_color"],
        }
        validated["icon_path"] = str(menu.get("icon_path") or "")
        validated["icon_managed"] = bool(menu.get("icon_managed", False))
        validated["icon_only"] = bool(menu.get("icon_only", False))
        validated["button_style"] = validate_button_style(
            menu.get("button_style"),
            appearance,
        )
        menu_id = str(menu.get("id") or "").strip()
        validated["id"] = menu_id or str(uuid.uuid4())
    else:
        validated.pop("button_style", None)
        if item_type == "folder_menu":
            validated["icon_path"] = str(menu.get("icon_path") or "")
            validated["icon_managed"] = bool(menu.get("icon_managed", False))
            validated["icon_only"] = bool(menu.get("icon_only", False))
        else:
            validated.pop("icon_path", None)
            validated.pop("icon_managed", None)
            validated.pop("icon_only", None)
        if item_type != "top_launcher":
            validated.pop("target", None)
            validated.pop("target_type", None)
            validated.pop("arguments", None)
            validated.pop("working_directory", None)
            validated.pop("python_mode", None)
            validated.pop("accept_dropped_files", None)
            validated.pop("folder_drop_action", None)
    return validated


def validate_logo(value: Any, fallback_height: int | None = None) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    defaults = copy.deepcopy(DEFAULT_CONFIG["logo"])
    effective_fallback = clamp_int(
        fallback_height,
        16,
        200,
        DEFAULT_CONFIG["logo"]["height"],
    )
    defaults["height"] = clamp_int(source.get("height"), 16, 200, effective_fallback)
    defaults["maximum_width"] = clamp_int(source.get("maximum_width"), 32, 600, defaults["maximum_width"])
    defaults["opacity"] = clamp_float(source.get("opacity"), 0.10, 1.00, defaults["opacity"])
    defaults["visible"] = bool(source.get("visible", defaults["visible"]))
    defaults["image"] = str(source.get("image") or defaults["image"])
    defaults["preserve_aspect_ratio"] = bool(source.get("preserve_aspect_ratio", defaults["preserve_aspect_ratio"]))
    defaults["tooltip"] = str(source.get("tooltip") or defaults["tooltip"])

    action = str(source.get("left_click_action") or defaults["left_click_action"]).strip().lower()
    defaults["left_click_action"] = action if action in LOGO_LEFT_CLICK_ACTIONS else "none"

    launcher = source.get("left_click_launcher")
    defaults["left_click_launcher"] = validate_item(launcher) if isinstance(launcher, dict) else None

    items = source.get("menu_items", [])
    defaults["menu_items"] = [validate_item(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    preserved = preserve_future_fields(source)
    preserved.update(defaults)
    return preserved


def migrate_managed_asset_paths(config: dict[str, Any]) -> bool:
    changed = False

    def migrate_path(path_text: Any, item_id: str | None = None, logo: bool = False) -> str:
        nonlocal changed
        text = str(path_text or "")
        normalized = text.replace("\\", "/")
        if logo:
            if normalized.startswith(OLD_MANAGED_ICON_PREFIXES):
                source = resolve_external_path(normalized)
                if source.exists():
                    move_managed_asset_file(source, app_base_path() / MANAGED_LOGO_IMAGE)
                    changed = True
                    return MANAGED_LOGO_IMAGE
            return text

        for prefix in OLD_MANAGED_ICON_PREFIXES:
            if normalized.startswith(prefix):
                source = app_base_path() / normalized
                destination_name = f"{safe_icon_id(item_id) or Path(normalized).name}"
                if not destination_name.lower().endswith(".png"):
                    destination_name = f"{destination_name}.png"
                destination = managed_icons_dir() / destination_name
                move_managed_asset_file(source, destination)
                changed = True
                return str(Path(MANAGED_ICON_DIR) / destination.name).replace("\\", "/")
        return text

    logo = config.get("logo")
    if isinstance(logo, dict):
        migrated = migrate_path(logo.get("image"), logo=True)
        if migrated != logo.get("image"):
            logo["image"] = migrated
        changed = migrate_item_collection(logo.get("menu_items", []), migrate_path) or changed
        launcher = logo.get("left_click_launcher")
        if isinstance(launcher, dict):
            changed = migrate_item_icon(launcher, migrate_path) or changed

    menus = config.get("menus", [])
    if isinstance(menus, list):
        for menu in menus:
            if isinstance(menu, dict):
                changed = migrate_menu_icon(menu, migrate_path) or changed

    remove_empty_old_icon_dirs()
    return changed


def migrate_menu_icon(menu: dict[str, Any], migrate_path) -> bool:
    changed = False
    if "icon_path" in menu:
        migrated = migrate_path(menu.get("icon_path"), str(menu.get("id") or ""))
        if migrated != menu.get("icon_path"):
            menu["icon_path"] = migrated
            changed = True
    changed = migrate_item_collection(menu.get("items", []), migrate_path) or changed
    return changed


def migrate_item_collection(items: Any, migrate_path) -> bool:
    changed = False
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                changed = migrate_item_icon(item, migrate_path) or changed
    return changed


def migrate_item_icon(item: dict[str, Any], migrate_path) -> bool:
    changed = False
    if "icon" in item:
        migrated = migrate_path(item.get("icon"), str(item.get("id") or ""))
        if migrated != item.get("icon"):
            item["icon"] = migrated
            changed = True
    if "icon_path" in item:
        migrated = migrate_path(item.get("icon_path"), str(item.get("id") or ""))
        if migrated != item.get("icon_path"):
            item["icon_path"] = migrated
            changed = True
    changed = migrate_item_collection(item.get("items", []), migrate_path) or changed
    return changed


def resolve_external_path(path_text: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(path_text)))
    return path if path.is_absolute() else app_base_path() / path


def move_managed_asset_file(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return
    try:
        source.replace(destination)
    except OSError:
        try:
            import shutil

            shutil.copy2(source, destination)
        except OSError:
            pass


def safe_icon_id(item_id: str | None) -> str:
    text = str(item_id or "").strip()
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in text)


def remove_empty_old_icon_dirs() -> None:
    for old_dir in (Path("icons") / "menu_icons", Path("icons") / "launcher_icons"):
        target = app_base_path() / old_dir
        try:
            target.rmdir()
        except OSError:
            pass


def validate_button_style(value: Any, fallbacks: dict[str, str]) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "use_custom_colors": bool(source.get("use_custom_colors", False)),
        "background": normalize_hex_color(source.get("background"), fallbacks["background"]),
        "hover": normalize_hex_color(source.get("hover"), fallbacks["hover"]),
        "text": normalize_hex_color(source.get("text"), fallbacks["text"]),
        "border": normalize_hex_color(source.get("border"), fallbacks["border"]),
    }


def validate_item(item: dict[str, Any]) -> dict[str, Any]:
    item_type = str(item.get("type") or "launcher").lower()
    if item_type == "menu":
        item_type = "submenu"
    if item_type not in ITEM_TYPES or item_type == "menu":
        item_type = "launcher"

    if item_type in {"submenu", "folder_menu"}:
        return validate_menu({**item, "type": item_type}, top_level=False)
    if item_type == "separator":
        validated = preserve_future_fields(item)
        validated["type"] = "separator"
        validated["id"] = str(item.get("id") or "").strip() or str(uuid.uuid4())
        return validated
    if item_type == "heading":
        validated = preserve_future_fields(item)
        validated.update(
            {
                "id": str(item.get("id") or "").strip() or str(uuid.uuid4()),
                "name": str(item.get("name") or "Heading"),
                "type": "heading",
                "icon": str(item.get("icon") or ""),
            }
        )
        return validated

    target_type = normalize_choice(str(item.get("target_type") or "Auto Detect"), LAUNCH_TARGET_TYPES, "Auto Detect")
    if target_type not in LAUNCH_TARGET_TYPES:
        target_type = "Auto Detect"
    python_mode = normalize_choice(str(item.get("python_mode") or "Automatic"), PYTHON_MODES, "Automatic")

    validated = preserve_future_fields(item)
    validated.update(
        {
            "id": str(item.get("id") or "").strip() or str(uuid.uuid4()),
            "name": str(item.get("name") or "Launcher"),
            "type": "launcher",
            "target": str(item.get("target") or ""),
            "target_type": target_type,
            "arguments": str(item.get("arguments") or ""),
            "working_directory": str(item.get("working_directory") or ""),
            "python_mode": python_mode,
            "icon": str(item.get("icon") or ""),
            "enabled": bool(item.get("enabled", True)),
            "accept_dropped_files": bool(item.get("accept_dropped_files", False)),
            "folder_drop_action": normalize_choice(
                str(item.get("folder_drop_action") or "move"),
                FOLDER_DROP_ACTIONS,
                "move",
            ),
        }
    )
    return validated


def preserve_future_fields(item: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(item)


def normalize_choice(value: str, choices: set[str], fallback: str) -> str:
    normalized = value.strip().lower().replace("_", " ").replace("-", " ")
    for choice in choices:
        if choice.lower().replace("_", " ").replace("-", " ") == normalized:
            return choice
    aliases = {
        "program": "Program",
        "powershell": "PowerShell Script",
        "powershell script": "PowerShell Script",
        "python": "Python Script",
        "python script": "Python Script",
        "command": "Command Script",
        "command script": "Command Script",
        "website": "Website",
        "folder": "Folder",
        "file": "File",
        "auto": "Auto Detect",
        "auto detect": "Auto Detect",
        "console python": "Console Python",
        "windowed python": "Windowed Python",
        "automatic": "Automatic",
    }
    return aliases.get(normalized, fallback)


def root_config_from_runtime(config: dict[str, Any]) -> dict[str, Any]:
    application = config.get("application", {})
    return {
        "config_version": CONFIG_VERSION,
        "active_user_profile_id": safe_profile_id(
            str(config.get("active_user_profile_id") or "")
        ),
        "application": preserve_future_fields(application) if isinstance(application, dict) else {},
        "monitoring": {
            "known_monitors": copy.deepcopy(
                config.get("monitoring", {}).get("known_monitors", {})
            )
        },
    }


def toolbar_sections_from_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "appearance": copy.deepcopy(config.get("appearance", DEFAULT_CONFIG["appearance"])),
        "behavior": copy.deepcopy(config.get("behavior", DEFAULT_CONFIG["behavior"])),
        "logo": copy.deepcopy(config.get("logo", DEFAULT_CONFIG["logo"])),
        "menus": copy.deepcopy(config.get("menus", DEFAULT_CONFIG["menus"])),
    }


def profile_json_from_runtime(config: dict[str, Any], localize_assets: bool = True) -> dict[str, Any]:
    profile_id = safe_profile_id(str(config.get("active_user_profile_id") or "")) or new_profile_id()
    profile_data = {
        "profile_id": profile_id,
        "name": str(config.get("user_profile_name") or "Default"),
        "description": str(config.get("user_profile_description") or ""),
        "monitoring": copy.deepcopy(config.get("monitoring", {})),
        "shared": toolbar_sections_from_config(config),
        "monitor_profiles": {},
    }
    for monitor_key, monitor_profile in config.get("toolbar_profiles", {}).items():
        if isinstance(monitor_profile, dict):
            profile_data["monitor_profiles"][str(monitor_key)] = copy.deepcopy(monitor_profile)
    profile_data["unmapped_monitor_profiles"] = copy.deepcopy(
        config.get("unmapped_monitor_profiles", [])
    )
    if localize_assets:
        localize_profile_asset_paths(profile_data)
    return profile_data


def runtime_config_from_profile_json(
    root_config: dict[str, Any],
    profile_data: dict[str, Any],
    screen_count: int | None = None,
    connected_monitor_ids: list[str] | None = None,
) -> dict[str, Any]:
    profile_data = copy.deepcopy(profile_data)
    expand_profile_asset_paths(profile_data)
    shared = profile_data.get("shared", {})
    if not isinstance(shared, dict):
        shared = {}
    merged = {
        **toolbar_sections_from_config(shared),
        "config_version": CONFIG_VERSION,
        "active_user_profile_id": safe_profile_id(str(profile_data.get("profile_id") or "")),
        "user_profile_name": str(profile_data.get("name") or "Default"),
        "user_profile_description": str(profile_data.get("description") or ""),
        "application": copy.deepcopy(root_config.get("application", DEFAULT_CONFIG["application"])),
        "monitoring": copy.deepcopy(profile_data.get("monitoring", DEFAULT_CONFIG["monitoring"])),
        "toolbar_profiles": copy.deepcopy(profile_data.get("monitor_profiles", {})),
        "unmapped_monitor_profiles": copy.deepcopy(profile_data.get("unmapped_monitor_profiles", [])),
        "saved_toolbar_profiles": [],
    }
    root_known = root_config.get("monitoring", {}).get("known_monitors", {})
    if isinstance(root_known, dict):
        merged.setdefault("monitoring", {}).setdefault("known_monitors", {})
        if isinstance(merged["monitoring"]["known_monitors"], dict):
            merged["monitoring"]["known_monitors"] = {
                **copy.deepcopy(root_known),
                **copy.deepcopy(merged["monitoring"]["known_monitors"]),
            }
    return validate_config(merged, screen_count, connected_monitor_ids)


def asset_field_values(item: dict[str, Any]) -> list[str]:
    return [field for field in ("icon", "icon_path", "image") if str(item.get(field) or "")]


def localize_profile_asset_paths(profile_data: dict[str, Any]) -> None:
    profile_id = safe_profile_id(str(profile_data.get("profile_id") or ""))
    if not profile_id:
        return
    shared = profile_data.get("shared")
    if isinstance(shared, dict):
        localize_toolbar_asset_paths(profile_id, shared, Path("shared") / "icons")
    monitor_profiles = profile_data.get("monitor_profiles", {})
    if isinstance(monitor_profiles, dict):
        for monitor_profile in monitor_profiles.values():
            if not isinstance(monitor_profile, dict):
                continue
            monitor_profile_id = safe_profile_id(str(monitor_profile.get("profile_id") or "monitor"))
            localize_toolbar_asset_paths(profile_id, monitor_profile, Path("monitor_profiles") / monitor_profile_id / "icons")
    unmapped_profiles = profile_data.get("unmapped_monitor_profiles", [])
    if isinstance(unmapped_profiles, list):
        for unmapped in unmapped_profiles:
            if not isinstance(unmapped, dict) or not isinstance(unmapped.get("toolbar"), dict):
                continue
            toolbar = unmapped["toolbar"]
            monitor_profile_id = safe_profile_id(str(toolbar.get("profile_id") or "monitor"))
            localize_toolbar_asset_paths(profile_id, toolbar, Path("monitor_profiles") / monitor_profile_id / "icons")


def expand_profile_asset_paths(profile_data: dict[str, Any]) -> None:
    profile_id = safe_profile_id(str(profile_data.get("profile_id") or ""))
    if not profile_id:
        return
    shared = profile_data.get("shared")
    if isinstance(shared, dict):
        expand_toolbar_asset_paths(profile_id, shared)
    monitor_profiles = profile_data.get("monitor_profiles", {})
    if isinstance(monitor_profiles, dict):
        for monitor_profile in monitor_profiles.values():
            if isinstance(monitor_profile, dict):
                expand_toolbar_asset_paths(profile_id, monitor_profile)
    unmapped_profiles = profile_data.get("unmapped_monitor_profiles", [])
    if isinstance(unmapped_profiles, list):
        for unmapped in unmapped_profiles:
            if isinstance(unmapped, dict) and isinstance(unmapped.get("toolbar"), dict):
                expand_toolbar_asset_paths(profile_id, unmapped["toolbar"])


def localize_toolbar_asset_paths(profile_id: str, toolbar_config: dict[str, Any], asset_dir: Path) -> None:
    logo = toolbar_config.get("logo", {})
    if isinstance(logo, dict):
        localize_asset_field(profile_id, logo, "image", asset_dir, "logo")
        launcher = logo.get("left_click_launcher")
        if isinstance(launcher, dict):
            localize_item_asset_paths(profile_id, launcher, asset_dir)
        for item in logo.get("menu_items", []):
            if isinstance(item, dict):
                localize_item_asset_paths(profile_id, item, asset_dir)
    for menu in toolbar_config.get("menus", []):
        if isinstance(menu, dict):
            localize_item_asset_paths(profile_id, menu, asset_dir)


def expand_toolbar_asset_paths(profile_id: str, toolbar_config: dict[str, Any]) -> None:
    logo = toolbar_config.get("logo", {})
    if isinstance(logo, dict):
        expand_asset_field(profile_id, logo, "image")
        launcher = logo.get("left_click_launcher")
        if isinstance(launcher, dict):
            expand_item_asset_paths(profile_id, launcher)
        for item in logo.get("menu_items", []):
            if isinstance(item, dict):
                expand_item_asset_paths(profile_id, item)
    for menu in toolbar_config.get("menus", []):
        if isinstance(menu, dict):
            expand_item_asset_paths(profile_id, menu)


def localize_item_asset_paths(profile_id: str, item: dict[str, Any], asset_dir: Path) -> None:
    for field in ("icon", "icon_path"):
        localize_asset_field(profile_id, item, field, asset_dir, str(item.get("id") or item.get("name") or field))
    for child in item.get("items", []):
        if isinstance(child, dict):
            localize_item_asset_paths(profile_id, child, asset_dir)


def expand_item_asset_paths(profile_id: str, item: dict[str, Any]) -> None:
    for field in ("icon", "icon_path"):
        expand_asset_field(profile_id, item, field)
    for child in item.get("items", []):
        if isinstance(child, dict):
            expand_item_asset_paths(profile_id, child)


def localize_asset_field(profile_id: str, item: dict[str, Any], field: str, asset_dir: Path, fallback_name: str) -> None:
    value = str(item.get(field) or "")
    if not value or value == DEFAULT_LOGO_IMAGE:
        return
    normalized = value.replace("\\", "/")
    profile_prefix = f"{USER_PROFILES_DIR}/{profile_id}/"
    if normalized.startswith(profile_prefix):
        existing_relative = normalized[len(profile_prefix):]
        if existing_relative.startswith(str(asset_dir).replace("\\", "/") + "/"):
            item[field] = existing_relative
            return
        source = app_base_path() / normalized
    elif normalized.startswith(("shared/", "monitor_profiles/")):
        if normalized.startswith(str(asset_dir).replace("\\", "/") + "/"):
            item[field] = normalized
            return
        source = user_profile_dir(profile_id) / normalized
    else:
        source = resolve_external_path(value)
    if not source.exists() or not source.is_file():
        return
    suffix = source.suffix.lower() or ".png"
    safe_name = "LOGO" if field == "image" and source.stem.upper() == "LOGO" else (safe_icon_id(fallback_name) or "asset")
    relative_path = asset_dir / f"{safe_name}{suffix}"
    destination = user_profile_dir(profile_id) / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if field == "image" and safe_name == "LOGO":
            for logo_suffix in (".png", ".gif"):
                stale = destination.with_suffix(logo_suffix)
                if stale != destination:
                    stale.unlink(missing_ok=True)
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
    except OSError:
        return
    item[field] = str(relative_path).replace("\\", "/")


def expand_asset_field(profile_id: str, item: dict[str, Any], field: str) -> None:
    value = str(item.get(field) or "")
    if not value or value == DEFAULT_LOGO_IMAGE:
        return
    normalized = value.replace("\\", "/")
    if normalized.startswith(f"{USER_PROFILES_DIR}/") or Path(value).is_absolute():
        return
    item[field] = str(Path(USER_PROFILES_DIR) / profile_id / normalized).replace("\\", "/")


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.stem}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def load_user_profile_json(profile_id: str) -> tuple[dict[str, Any] | None, str]:
    path = user_profile_json_path(profile_id)
    data, loaded = load_json_file(path)
    if not loaded or not isinstance(data, dict):
        return None, f"Could not load {path}"
    return data, ""


def list_user_profile_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    root = user_profiles_dir()
    if not root.exists():
        return records
    for path in sorted(root.glob("*/profile.json"), key=lambda item: str(item.parent.name).casefold()):
        data, loaded = load_json_file(path)
        if not loaded or not isinstance(data, dict):
            records.append({"profile_id": path.parent.name, "name": path.parent.name, "invalid": True, "error": f"Invalid profile file: {path}"})
            continue
        profile_id = safe_profile_id(str(data.get("profile_id") or path.parent.name))
        records.append(
            {
                "profile_id": profile_id,
                "name": str(data.get("name") or profile_id),
                "description": str(data.get("description") or ""),
                "path": str(path),
                "invalid": False,
                "error": "",
            }
        )
    return records


def load_all_user_profile_data() -> tuple[list[dict[str, Any]], list[str]]:
    profiles: list[dict[str, Any]] = []
    errors: list[str] = []
    root = user_profiles_dir()
    if not root.exists():
        return profiles, errors
    for path in sorted(root.glob("*/profile.json"), key=lambda item: str(item.parent.name).casefold()):
        data, loaded = load_json_file(path)
        if not loaded or not isinstance(data, dict):
            errors.append(f"Invalid profile file: {path}")
            continue
        profile_id = safe_profile_id(str(data.get("profile_id") or path.parent.name))
        if not profile_id:
            errors.append(f"Invalid profile id in {path}")
            continue
        data["profile_id"] = profile_id
        profiles.append(data)
    return profiles, errors


def save_user_profile_data(profile_data: dict[str, Any]) -> None:
    profile_id = safe_profile_id(str(profile_data.get("profile_id") or ""))
    if not profile_id:
        raise ValueError("A user profile ID is required.")
    profile_data = copy.deepcopy(profile_data)
    localize_profile_asset_paths(profile_data)
    temp_parent = user_profiles_dir()
    temp_parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(user_profile_json_path(profile_id), profile_data)


def remove_user_profile_folder(profile_id: str) -> None:
    profile_id = safe_profile_id(profile_id)
    if not profile_id:
        return
    target = user_profile_dir(profile_id)
    try:
        shutil.rmtree(target)
    except FileNotFoundError:
        return


def commit_user_profile_records(profiles: list[dict[str, Any]], deleted_ids: set[str]) -> None:
    valid_ids = {safe_profile_id(str(profile.get("profile_id") or "")) for profile in profiles}
    valid_ids.discard("")
    for profile in profiles:
        save_user_profile_data(profile)
    for profile_id in deleted_ids:
        if profile_id not in valid_ids:
            remove_user_profile_folder(profile_id)


def first_valid_user_profile_id() -> str:
    for record in list_user_profile_records():
        if not record.get("invalid"):
            return str(record.get("profile_id") or "")
    return ""


def save_runtime_user_profile(config: dict[str, Any]) -> dict[str, Any]:
    profile_id = safe_profile_id(str(config.get("active_user_profile_id") or "")) or new_profile_id()
    runtime = copy.deepcopy(config)
    runtime["active_user_profile_id"] = profile_id
    profile_data = profile_json_from_runtime(runtime)
    atomic_write_json(user_profile_json_path(profile_id), profile_data)
    return runtime_config_from_profile_json(
        root_config_from_runtime(runtime),
        profile_data,
    )


def create_default_user_profile_from_legacy(
    legacy_config: dict[str, Any],
    screen_count: int | None = None,
    connected_monitor_ids: list[str] | None = None,
) -> dict[str, Any]:
    profile_id = "default"
    runtime = validate_config(
        {
            **copy.deepcopy(legacy_config),
            "active_user_profile_id": profile_id,
            "user_profile_name": "Default",
            "user_profile_description": "",
        },
        screen_count,
        connected_monitor_ids,
    )
    write_backup_once(legacy_config)
    save_runtime_user_profile(runtime)
    atomic_write_json(config_file_path(), root_config_from_runtime(runtime))
    return runtime


def load_active_user_profile_config(
    root_config: dict[str, Any],
    screen_count: int | None = None,
    connected_monitor_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    active_id = safe_profile_id(str(root_config.get("active_user_profile_id") or ""))
    if not active_id:
        active_id = first_valid_user_profile_id()
    if not active_id:
        return None
    profile_data, error = load_user_profile_json(active_id)
    if profile_data is None:
        fallback_id = "default" if user_profile_json_path("default").exists() else first_valid_user_profile_id()
        if not fallback_id or fallback_id == active_id:
            logger.debug("active user profile missing and no fallback available: %s", error)
            return None
        profile_data, error = load_user_profile_json(fallback_id)
        if profile_data is None:
            logger.debug("fallback user profile load failed: %s", error)
            return None
        root_config = {**root_config, "active_user_profile_id": fallback_id}
    return runtime_config_from_profile_json(root_config, profile_data, screen_count, connected_monitor_ids)


def load_config(
    screen_count: int | None = None,
    connected_monitor_ids: list[str] | None = None,
) -> dict[str, Any]:
    path = config_file_path()
    if not path.exists():
        logger.debug("config load defaults path missing")
        config = create_default_user_profile_from_legacy(default_config(), screen_count, connected_monitor_ids)
        save_config(config, screen_count, connected_monitor_ids)
        return config

    data, loaded = load_json_file(path)
    if not loaded:
        logger.debug("config load failed; attempting backup recovery")
        preserve_damaged_config(path)
        backup_data, backup_loaded = load_json_file(backup_file_path())
        if backup_loaded:
            logger.debug("recovering config from backup")
            config = create_default_user_profile_from_legacy(backup_data, screen_count, connected_monitor_ids)
            save_config(config, screen_count, connected_monitor_ids)
            return config
        logger.debug("loading default config after config and backup recovery failed")
        return create_default_user_profile_from_legacy(default_config(), screen_count, connected_monitor_ids)

    if isinstance(data, dict) and data.get("active_user_profile_id"):
        active_config = load_active_user_profile_config(data, screen_count, connected_monitor_ids)
        if active_config is not None:
            return active_config

    migrated = migrate_managed_asset_paths(data) if isinstance(data, dict) else False
    config = create_default_user_profile_from_legacy(
        validate_config(data, screen_count, connected_monitor_ids),
        screen_count,
        connected_monitor_ids,
    )
    if data != config and not backup_file_path().exists():
        write_backup_once(data)
    if migrated or data != config:
        logger.debug("config migration/repair save")
        save_config(config, screen_count, connected_monitor_ids)
    return config


def load_json_file(path: Path) -> tuple[Any, bool]:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file), True
    except (OSError, json.JSONDecodeError):
        return None, False


def write_backup_once(data: Any) -> None:
    try:
        with backup_file_path().open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.write("\n")
    except OSError:
        logger.debug("failed to write initial backup", exc_info=True)


def preserve_damaged_config(path: Path) -> None:
    if not path.exists():
        return
    stamp = __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.stem}.damaged-{stamp}{path.suffix}")
    try:
        shutil.copy2(path, target)
    except OSError:
        logger.debug("failed to preserve damaged config", exc_info=True)


def save_config(
    config: dict[str, Any],
    screen_count: int | None = None,
    connected_monitor_ids: list[str] | None = None,
) -> dict[str, Any]:
    path = config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    validated = validate_config(config, screen_count, connected_monitor_ids)
    logger.debug("config save path=%s", path)
    saved_runtime = save_runtime_user_profile(validated)
    atomic_write_json(path, root_config_from_runtime(saved_runtime))
    return validate_config(saved_runtime, screen_count, connected_monitor_ids)
