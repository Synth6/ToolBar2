from __future__ import annotations

from config_manager import runtime_config_from_profile_json


def test_runtime_config_expands_shared_profile_asset_paths() -> None:
    profile_id = "asset_profile"
    profile = {
        "profile_id": profile_id,
        "name": "Asset Profile",
        "description": "",
        "monitoring": {"mode": "single", "selected_monitor_ids": []},
        "shared": {
            "logo": {
                "image": "shared/icons/LOGO.png",
                "left_click_launcher": {
                    "type": "launcher",
                    "name": "Logo Action",
                    "icon": "shared/icons/logo_action.png",
                },
                "menu_items": [
                    {
                        "type": "launcher",
                        "name": "Logo Menu Launcher",
                        "icon": "shared/icons/logo_menu_launcher.png",
                    }
                ],
            },
            "menus": [
                {
                    "type": "menu",
                    "name": "Main",
                    "icon_path": "shared/icons/menu.png",
                    "items": [
                        {
                            "type": "launcher",
                            "name": "Launcher",
                            "icon": "shared/icons/launcher.png",
                        }
                    ],
                }
            ],
        },
        "monitor_profiles": {},
    }

    runtime = runtime_config_from_profile_json(
        {"active_user_profile_id": profile_id, "application": {}, "monitoring": {}},
        profile,
    )

    prefix = f"user_profiles/{profile_id}/shared/icons"
    assert runtime["logo"]["image"] == f"{prefix}/LOGO.png"
    assert runtime["logo"]["left_click_launcher"]["icon"] == f"{prefix}/logo_action.png"
    assert runtime["logo"]["menu_items"][0]["icon"] == f"{prefix}/logo_menu_launcher.png"
    assert runtime["menus"][0]["icon_path"] == f"{prefix}/menu.png"
    assert runtime["menus"][0]["items"][0]["icon"] == f"{prefix}/launcher.png"
