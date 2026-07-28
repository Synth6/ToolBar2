from __future__ import annotations

import logging
import copy

from PyQt6 import QtCore, QtGui, QtWidgets

from app_icon import application_icon
from config_manager import (
    atomic_write_json,
    config_file_path,
    commit_staged_asset_deletes,
    effective_config_for_monitor,
    ensure_monitor_profile,
    list_user_profile_records,
    load_user_profile_json,
    load_config,
    profile_for_monitor,
    rollback_staged_asset_deletes,
    root_config_from_runtime,
    runtime_config_from_profile_json,
    safe_profile_id,
    save_config,
    stage_delete_monitor_profile_assets,
    update_monitor_profile,
    validate_config,
)
from monitor_utils import (
    connected_monitor_ids,
    connected_monitor_map,
    index_for_monitor_id,
    monitor_id,
    monitor_metadata,
    monitor_tray_display_name,
    primary_monitor_id,
)
from settings_window import SettingsWindow
from startup_manager import sync_startup_registration
from toolbar_window import ToolbarWindow


logger = logging.getLogger(__name__)


def copy_shared_config(config: dict) -> dict:
    return copy.deepcopy(config)


class ToolbarManager(QtCore.QObject):
    def __init__(self, app: QtWidgets.QApplication) -> None:
        super().__init__()
        self.app = app
        self.config: dict = {}
        self.toolbar_windows: dict[str, ToolbarWindow] = {}
        self.settings_window: SettingsWindow | None = None
        self.tray_icon: QtWidgets.QSystemTrayIcon | None = None
        self.tray_menu: QtWidgets.QMenu | None = None
        self.profiles_menu: QtWidgets.QMenu | None = None
        self.toolbars_menu: QtWidgets.QMenu | None = None
        self.exiting = False
        self.screen_signal_ids: set[int] = set()
        self.screen_id_by_object: dict[int, str] = {}
        self.monitor_reconcile_timer = QtCore.QTimer(self)
        self.monitor_reconcile_timer.setSingleShot(True)
        self.monitor_reconcile_timer.setInterval(350)
        self.monitor_reconcile_timer.timeout.connect(self.reconcile_after_monitor_change)

    def start(self) -> None:
        self.config = load_config(len(QtGui.QGuiApplication.screens()), connected_monitor_ids())
        gui_app = QtGui.QGuiApplication.instance()
        if gui_app is not None:
            gui_app.screenAdded.connect(self.handle_screen_added)
            gui_app.screenRemoved.connect(self.handle_screen_removed)
        self.connect_all_screen_signals()
        self.update_known_monitors()
        self.create_tray_icon()
        self.sync_startup_registration_at_start()
        self.reconcile_toolbar_windows()

    def startup_enabled_from_config(self, config: dict) -> bool:
        application = config.get("application", {})
        return bool(application.get("start_with_windows", False)) if isinstance(application, dict) else False

    def sync_startup_registration_at_start(self) -> None:
        try:
            sync_startup_registration(self.startup_enabled_from_config(self.config))
        except Exception:
            logger.exception("Windows startup synchronization failed")
            self.show_tray_message("Windows startup could not be updated.")

    def create_tray_icon(self) -> None:
        if self.tray_icon is not None:
            return
        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        icon = application_icon()
        if icon.isNull():
            icon = self.app.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("ToolBar2")

        tray_menu = QtWidgets.QMenu()
        self.tray_menu = tray_menu
        settings_action = tray_menu.addAction("Open Toolbar Settings...")
        settings_action.triggered.connect(lambda _checked=False: self.open_settings())
        self.profiles_menu = tray_menu.addMenu("Profiles")
        self.profiles_menu.aboutToShow.connect(lambda: self.populate_profiles_menu(self.profiles_menu))
        self.toolbars_menu = tray_menu.addMenu("Toolbars")
        reload_action = tray_menu.addAction("Reload Toolbars")
        reload_action.triggered.connect(lambda _checked=False: self.reload_toolbars())
        tray_menu.addSeparator()
        exit_action = tray_menu.addAction("Exit")
        exit_action.triggered.connect(self.exit_application)
        tray_menu.aboutToShow.connect(self.refresh_tray_menu)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)
        self.tray_icon.show()

    def refresh_tray_menu(self) -> None:
        if self.profiles_menu is not None:
            self.populate_profiles_menu(self.profiles_menu)
        self.rebuild_tray_toolbars_menu()

    def valid_user_profile_records(self) -> list[dict]:
        records = []
        for record in list_user_profile_records():
            profile_id = safe_profile_id(str(record.get("profile_id") or ""))
            profile_path = str(record.get("path") or "").replace("\\", "/")
            if not profile_id or "/.staging/" in profile_path or record.get("invalid"):
                continue
            records.append({**record, "profile_id": profile_id})
        return sorted(
            records,
            key=lambda item: (
                str(item.get("name") or item.get("profile_id") or "").casefold(),
                str(item.get("profile_id") or "").casefold(),
            ),
        )

    def populate_profiles_menu(self, menu: QtWidgets.QMenu | None) -> None:
        if menu is None:
            return
        menu.clear()
        records = self.valid_user_profile_records()
        if not records:
            action = menu.addAction("No saved profiles")
            action.setEnabled(False)
            return
        active_profile_id = str(self.config.get("active_user_profile_id") or "")
        group = QtGui.QActionGroup(menu)
        group.setExclusive(True)
        for record in records:
            profile_id = str(record.get("profile_id") or "")
            name = str(record.get("name") or profile_id or "Saved Profile")
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(profile_id == active_profile_id)
            action.setData(profile_id)
            group.addAction(action)
            action.triggered.connect(
                lambda _checked=False, target_id=profile_id: self.activate_user_profile(target_id)
            )

    def confirm_settings_profile_switch(self) -> bool:
        if self.settings_window is None or not self.settings_window.isVisible():
            return True
        if not self.settings_window.has_unsaved_changes():
            return True

        message = QtWidgets.QMessageBox(self.settings_window)
        message.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message.setWindowTitle("Switch Profile")
        message.setText("Settings contains unsaved changes.")
        message.setInformativeText("Switch profiles and discard those changes?")
        switch_button = message.addButton(
            "Switch Profile",
            QtWidgets.QMessageBox.ButtonRole.AcceptRole,
        )
        message.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(switch_button)
        message.exec()
        return message.clickedButton() is switch_button

    def activate_user_profile(self, profile_id: str) -> bool:
        profile_id = safe_profile_id(str(profile_id or ""))
        if not profile_id:
            return False
        if profile_id == str(self.config.get("active_user_profile_id") or ""):
            return True
        profile_name = profile_id
        for record in self.valid_user_profile_records():
            if str(record.get("profile_id") or "") == profile_id:
                profile_name = str(record.get("name") or profile_id)
                break

        if not self.confirm_settings_profile_switch():
            self.refresh_tray_menu()
            return False

        previous_config = copy.deepcopy(self.config)
        try:
            profile_data, error = load_user_profile_json(profile_id)
            if profile_data is None:
                raise ValueError(error or f"Could not load profile {profile_name}.")
            root_config = root_config_from_runtime(self.config)
            root_config["active_user_profile_id"] = profile_id
            next_config = runtime_config_from_profile_json(
                root_config,
                profile_data,
                len(QtGui.QGuiApplication.screens()),
                connected_monitor_ids(),
            )
            if str(next_config.get("monitoring", {}).get("mode") or "single") == "per_monitor":
                for monitor_id_value in next_config.get("monitoring", {}).get("selected_monitor_ids", []):
                    ensure_monitor_profile(next_config, str(monitor_id_value))
            atomic_write_json(config_file_path(), root_config_from_runtime(next_config))
        except Exception:
            self.config = previous_config
            logger.exception("user profile activation failed profile_id=%s", profile_id)
            self.show_tray_message(f"Profile could not be loaded: {profile_name}")
            self.refresh_tray_menu()
            return False

        self.config = next_config
        self.reconcile_toolbar_windows()
        if self.settings_window is not None:
            self.settings_window.discard_working_session_and_refresh(self.config)
        self.refresh_tray_menu()
        return True

    def rebuild_tray_toolbars_menu(self) -> None:
        if self.toolbars_menu is None:
            return
        self.toolbars_menu.clear()
        screens = QtGui.QGuiApplication.screens()
        monitoring = self.config.get("monitoring", {})
        mode = str(monitoring.get("mode") or "single")
        selected_ids = set(
            self.unique_ids([str(item) for item in monitoring.get("selected_monitor_ids", []) if str(item or "").strip()])
        )
        all_shared = mode == "all_shared"
        if not screens:
            action = self.toolbars_menu.addAction("No connected monitors")
            action.setEnabled(False)
            return
        for index, screen in enumerate(screens):
            screen_id = monitor_id(screen)
            if not screen_id:
                continue
            action = self.toolbars_menu.addAction(monitor_tray_display_name(screen, index))
            action.setData(screen_id)
            action.setCheckable(True)
            action.setChecked(all_shared or screen_id in selected_ids)
            action.setEnabled(not all_shared)
            action.triggered.connect(lambda _checked=False, target_id=screen_id: self.toggle_tray_monitor(target_id))

    def toggle_tray_monitor(self, target_monitor_id: str) -> None:
        target_monitor_id = str(target_monitor_id or "").strip()
        if not target_monitor_id:
            return
        previous_config = copy.deepcopy(self.config)
        try:
            updated = copy.deepcopy(self.config)
            monitoring = updated.setdefault("monitoring", {})
            mode = str(monitoring.get("mode") or "single")
            selected_ids = self.unique_ids(
                [str(item) for item in monitoring.get("selected_monitor_ids", []) if str(item or "").strip()]
            )

            if mode == "all_shared":
                self.rebuild_tray_toolbars_menu()
                return

            if mode == "single":
                if selected_ids[:1] == [target_monitor_id]:
                    self.rebuild_tray_toolbars_menu()
                    return
                selected_ids = [target_monitor_id]
            elif mode in {"selected_shared", "per_monitor"}:
                if target_monitor_id in selected_ids:
                    next_ids = [monitor_id_value for monitor_id_value in selected_ids if monitor_id_value != target_monitor_id]
                    if not next_ids:
                        self.show_tray_message("At least one toolbar monitor must remain selected.")
                        self.rebuild_tray_toolbars_menu()
                        return
                    selected_ids = next_ids
                else:
                    selected_ids = self.unique_ids([*selected_ids, target_monitor_id])
                    if mode == "per_monitor":
                        ensure_monitor_profile(updated, target_monitor_id)
            else:
                mode = "single"
                monitoring["mode"] = mode
                selected_ids = [target_monitor_id]

            monitoring["selected_monitor_ids"] = selected_ids
            self.synchronize_legacy_screen_index(updated, selected_ids)
            self.apply_config(updated)
        except Exception as exc:
            self.config = previous_config
            logger.exception("tray monitor selection failed")
            self.show_tray_message(f"Toolbar monitor could not be changed: {exc}")
            self.rebuild_tray_toolbars_menu()

    def monitoring_mode(self) -> str:
        return str(self.config.get("monitoring", {}).get("mode") or "single")

    def selected_monitor_ids(self, config: dict | None = None) -> list[str]:
        source = config or self.config
        monitoring = source.get("monitoring", {})
        if not isinstance(monitoring, dict):
            return []
        return self.unique_ids(
            [str(item) for item in monitoring.get("selected_monitor_ids", []) if str(item or "").strip()]
        )

    def is_monitor_selected(self, monitor_id: str) -> bool:
        return str(monitor_id or "").strip() in self.selected_monitor_ids()

    def can_disable_toolbar_for_monitor(self, monitor_id: str) -> bool:
        monitor_id = str(monitor_id or "").strip()
        mode = self.monitoring_mode()
        if mode not in {"selected_shared", "per_monitor"}:
            return False
        selected_connected = [item for item in self.desired_monitor_ids() if item in self.selected_monitor_ids()]
        return monitor_id in selected_connected and len(selected_connected) > 1

    def can_move_toolbar_for_monitor(self, monitor_id: str) -> bool:
        monitor_id = str(monitor_id or "").strip()
        return (
            self.monitoring_mode() == "per_monitor"
            and monitor_id in self.selected_monitor_ids()
            and profile_for_monitor(self.config, monitor_id) is not None
        )

    def can_delete_toolbar_for_monitor(self, monitor_id: str) -> bool:
        monitor_id = str(monitor_id or "").strip()
        return self.can_move_toolbar_for_monitor(monitor_id) and self.can_disable_toolbar_for_monitor(monitor_id)

    def move_toolbar_to_monitor(self, source_monitor_id: str, destination_monitor_id: str) -> None:
        source_monitor_id = str(source_monitor_id or "").strip()
        destination_monitor_id = str(destination_monitor_id or "").strip()
        if not source_monitor_id or not destination_monitor_id or source_monitor_id == destination_monitor_id:
            return
        previous_config = copy.deepcopy(self.config)
        try:
            updated = validate_config(copy.deepcopy(self.config), len(QtGui.QGuiApplication.screens()), connected_monitor_ids())
            if str(updated.get("monitoring", {}).get("mode") or "single") != "per_monitor":
                raise ValueError("Toolbar moves are only available for unique per-monitor toolbars.")
            profiles = updated.setdefault("toolbar_profiles", {})
            if not isinstance(profiles, dict):
                raise ValueError("Toolbar profile data is invalid.")
            if source_monitor_id not in profiles:
                raise ValueError("This monitor does not have a unique saved toolbar profile.")
            if destination_monitor_id in profiles:
                raise ValueError("The destination monitor already has a saved toolbar profile.")

            profiles[destination_monitor_id] = copy.deepcopy(profiles[source_monitor_id])
            profiles.pop(source_monitor_id, None)
            selected_ids = [
                destination_monitor_id if item == source_monitor_id else item
                for item in self.selected_monitor_ids(updated)
            ]
            if destination_monitor_id not in selected_ids:
                selected_ids.append(destination_monitor_id)
            selected_ids = [item for item in self.unique_ids(selected_ids) if item != source_monitor_id]
            updated.setdefault("monitoring", {})["selected_monitor_ids"] = selected_ids
            self.synchronize_legacy_screen_index(updated, selected_ids)
            self.apply_config(updated)
            self.refresh_tray_menu()
        except Exception as exc:
            self.config = previous_config
            logger.exception("toolbar move failed")
            raise OSError(str(exc) or "The toolbar could not be moved.") from exc

    def swap_monitor_toolbars(self, source_monitor_id: str, destination_monitor_id: str) -> None:
        source_monitor_id = str(source_monitor_id or "").strip()
        destination_monitor_id = str(destination_monitor_id or "").strip()
        if not source_monitor_id or not destination_monitor_id or source_monitor_id == destination_monitor_id:
            return
        previous_config = copy.deepcopy(self.config)
        try:
            updated = validate_config(copy.deepcopy(self.config), len(QtGui.QGuiApplication.screens()), connected_monitor_ids())
            if str(updated.get("monitoring", {}).get("mode") or "single") != "per_monitor":
                raise ValueError("Toolbar swaps are only available for unique per-monitor toolbars.")
            profiles = updated.setdefault("toolbar_profiles", {})
            if not isinstance(profiles, dict):
                raise ValueError("Toolbar profile data is invalid.")
            if source_monitor_id not in profiles or destination_monitor_id not in profiles:
                raise ValueError("Both monitors must have saved toolbar profiles to swap.")
            profiles[source_monitor_id], profiles[destination_monitor_id] = (
                copy.deepcopy(profiles[destination_monitor_id]),
                copy.deepcopy(profiles[source_monitor_id]),
            )
            selected_ids = self.unique_ids([*self.selected_monitor_ids(updated), source_monitor_id, destination_monitor_id])
            updated.setdefault("monitoring", {})["selected_monitor_ids"] = selected_ids
            self.synchronize_legacy_screen_index(updated, selected_ids)
            self.apply_config(updated)
            self.refresh_tray_menu()
        except Exception as exc:
            self.config = previous_config
            logger.exception("toolbar swap failed")
            raise OSError(str(exc) or "The toolbars could not be swapped.") from exc

    def disable_toolbar_for_monitor(self, monitor_id: str) -> None:
        monitor_id = str(monitor_id or "").strip()
        if not monitor_id:
            return
        previous_config = copy.deepcopy(self.config)
        try:
            if not self.can_disable_toolbar_for_monitor(monitor_id):
                raise ValueError("At least one other toolbar must remain active.")
            updated = copy.deepcopy(self.config)
            selected_ids = [item for item in self.selected_monitor_ids(updated) if item != monitor_id]
            updated.setdefault("monitoring", {})["selected_monitor_ids"] = selected_ids
            self.synchronize_legacy_screen_index(updated, selected_ids)
            self.apply_config(updated)
            self.refresh_tray_menu()
        except Exception as exc:
            self.config = previous_config
            logger.exception("toolbar disable failed")
            raise OSError(str(exc) or "The toolbar could not be disabled.") from exc

    def delete_toolbar_for_monitor(self, monitor_id: str) -> None:
        monitor_id = str(monitor_id or "").strip()
        if not monitor_id:
            return
        previous_config = copy.deepcopy(self.config)
        staged_deletes: list[tuple] = []
        config_saved = False
        try:
            if not self.can_delete_toolbar_for_monitor(monitor_id):
                raise ValueError("This toolbar cannot be deleted because at least one other active toolbar must remain.")
            updated = validate_config(copy.deepcopy(self.config), len(QtGui.QGuiApplication.screens()), connected_monitor_ids())
            profiles = updated.setdefault("toolbar_profiles", {})
            if not isinstance(profiles, dict):
                raise ValueError("Toolbar profile data is invalid.")
            profile = profiles.get(monitor_id)
            if not isinstance(profile, dict):
                raise ValueError("This monitor does not have a unique saved toolbar profile.")
            monitor_profile_id = safe_profile_id(str(profile.get("profile_id") or ""))
            profiles.pop(monitor_id, None)
            selected_ids = [item for item in self.selected_monitor_ids(updated) if item != monitor_id]
            updated.setdefault("monitoring", {})["selected_monitor_ids"] = selected_ids
            self.synchronize_legacy_screen_index(updated, selected_ids)
            staged_deletes = stage_delete_monitor_profile_assets(updated, monitor_profile_id)
            self.apply_config(updated)
            config_saved = True
            commit_staged_asset_deletes(staged_deletes)
            self.refresh_tray_menu()
        except Exception as exc:
            rollback_staged_asset_deletes(staged_deletes)
            if config_saved:
                try:
                    self.apply_config(previous_config)
                except Exception:
                    logger.exception("toolbar delete config rollback failed")
                    self.config = previous_config
                    self.reconcile_toolbar_windows()
            else:
                self.config = previous_config
            logger.exception("toolbar delete failed")
            raise OSError(str(exc) or "The toolbar could not be deleted.") from exc

    def synchronize_legacy_screen_index(self, config: dict, selected_ids: list[str]) -> None:
        behavior = config.setdefault("behavior", {})
        legacy_monitor_id = selected_ids[0] if selected_ids else primary_monitor_id()
        screen_index = index_for_monitor_id(legacy_monitor_id)
        if screen_index is None:
            screen_index = 0
        behavior["screen_index"] = screen_index

    def show_tray_message(self, message: str) -> None:
        if self.tray_icon is not None and self.tray_icon.isVisible():
            self.tray_icon.showMessage("ToolBar2", message, QtWidgets.QSystemTrayIcon.MessageIcon.Information, 2500)

    def tray_icon_activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:
        if reason != QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick:
            return
        self.toggle_toolbars()

    def configured_monitor_id(self) -> str:
        ids = self.desired_monitor_ids()
        return ids[0] if ids else ""

    def desired_monitor_ids(self, config: dict | None = None) -> list[str]:
        config = config or self.config
        connected_ids = self.unique_ids(list(connected_monitor_map().keys()))
        if not connected_ids:
            return []

        monitoring = config.get("monitoring", {})
        mode = str(monitoring.get("mode") or "single")
        settings_live_preview = bool(monitoring.get("settings_live_preview", False)) if isinstance(monitoring, dict) else False
        selected_ids = self.unique_ids(
            [str(item) for item in monitoring.get("selected_monitor_ids", []) if str(item or "").strip()]
        )
        selected_connected = [monitor_id for monitor_id in connected_ids if monitor_id in selected_ids]

        if mode == "all_shared":
            return connected_ids
        if mode == "selected_shared" and selected_connected:
            return selected_connected
        if mode == "per_monitor" and selected_connected:
            return selected_connected
        if settings_live_preview and mode in {"selected_shared", "per_monitor"}:
            return []
        if mode == "single" and selected_connected:
            return [selected_connected[0]]

        primary_id = primary_monitor_id()
        if primary_id and primary_id in connected_ids:
            return [primary_id]
        return [connected_ids[0]]

    def unique_ids(self, monitor_ids: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for monitor_id in monitor_ids:
            if monitor_id and monitor_id not in seen:
                seen.add(monitor_id)
                result.append(monitor_id)
        return result

    def create_toolbar_for_monitor(self, monitor_id: str) -> ToolbarWindow:
        if monitor_id in self.toolbar_windows:
            return self.toolbar_windows[monitor_id]
        window = ToolbarWindow(self, self.config_for_monitor(monitor_id), monitor_id)
        self.toolbar_windows[monitor_id] = window
        window.show()
        logger.debug("toolbar created for monitor %s", monitor_id)
        return window

    def remove_toolbar_for_monitor(self, monitor_id: str) -> None:
        window = self.toolbar_windows.pop(monitor_id, None)
        if window is None:
            return
        window.prepare_for_removal()
        window.close()
        window.deleteLater()
        logger.debug("toolbar removed for monitor %s", monitor_id)

    def reconcile_toolbar_windows(self, config_override: dict | None = None) -> None:
        source_config = config_override or self.config
        logger.debug("reconciliation start mode=%s", source_config.get("monitoring", {}).get("mode"))
        if config_override is None:
            self.update_known_monitors()
        connected_map = connected_monitor_map()
        desired_ids = self.desired_monitor_ids(source_config)
        desired_set = set(desired_ids)
        logger.debug("desired runtime monitor ids=%s", desired_ids)

        for monitor_id in list(self.toolbar_windows):
            if monitor_id not in desired_set or monitor_id not in connected_map:
                self.remove_toolbar_for_monitor(monitor_id)

        for monitor_id in desired_ids:
            if monitor_id not in connected_map:
                continue
            if monitor_id not in self.toolbar_windows:
                if config_override is None:
                    self.create_toolbar_for_monitor(monitor_id)
                else:
                    window = ToolbarWindow(self, self.config_for_monitor(monitor_id, source_config), monitor_id)
                    self.toolbar_windows[monitor_id] = window
                    window.show()
            else:
                self.toolbar_windows[monitor_id].refresh_config(self.config_for_monitor(monitor_id, source_config), monitor_id)
        logger.debug("reconciliation complete active monitor ids=%s", list(self.toolbar_windows))

    def refresh_toolbar_windows(self) -> None:
        self.reconcile_toolbar_windows()

    def reload_toolbars(self) -> None:
        logger.debug("toolbar reload requested")
        self.monitor_reconcile_timer.stop()
        for monitor_id in list(self.toolbar_windows):
            self.remove_toolbar_for_monitor(monitor_id)
        self.reconcile_toolbar_windows()
        if self.settings_window is not None:
            self.settings_window.refresh_from_config(self.config)

    def apply_config(self, config: dict) -> None:
        validated = validate_config(config, len(QtGui.QGuiApplication.screens()), connected_monitor_ids())
        if str(validated.get("monitoring", {}).get("mode") or "single") == "per_monitor":
            for monitor_id in validated.get("monitoring", {}).get("selected_monitor_ids", []):
                ensure_monitor_profile(validated, str(monitor_id))
        logger.debug("config save monitoring mode=%s", validated.get("monitoring", {}).get("mode"))
        previous_startup_enabled = self.startup_enabled_from_config(self.config)
        requested_startup_enabled = self.startup_enabled_from_config(validated)
        startup_changed = requested_startup_enabled != previous_startup_enabled
        if startup_changed:
            try:
                sync_startup_registration(requested_startup_enabled)
            except Exception as exc:
                logger.exception("Windows startup registry update failed")
                raise OSError("Windows startup could not be updated.") from exc
        try:
            saved_config = save_config(validated, len(QtGui.QGuiApplication.screens()), connected_monitor_ids())
        except Exception as exc:
            if startup_changed:
                try:
                    sync_startup_registration(previous_startup_enabled)
                except Exception:
                    logger.exception("Windows startup rollback failed after config save failure")
            raise OSError(str(exc) or "The toolbar configuration could not be saved.") from exc
        self.config = saved_config
        self.reconcile_toolbar_windows()
        if self.settings_window is not None:
            self.settings_window.refresh_from_config(self.config)

    def save_settings_config(self, config: dict) -> dict:
        validated = validate_config(config, len(QtGui.QGuiApplication.screens()), connected_monitor_ids())
        previous_startup_enabled = self.startup_enabled_from_config(self.config)
        requested_startup_enabled = self.startup_enabled_from_config(validated)
        startup_changed = requested_startup_enabled != previous_startup_enabled
        if startup_changed:
            sync_startup_registration(requested_startup_enabled)
        try:
            saved_config = save_config(validated, len(QtGui.QGuiApplication.screens()), connected_monitor_ids())
        except Exception as exc:
            if startup_changed:
                sync_startup_registration(previous_startup_enabled)
            raise OSError(str(exc) or "The toolbar configuration could not be saved.") from exc
        self.config = saved_config
        self.reconcile_toolbar_windows()
        return self.config

    def preview_working_config(self, config: dict) -> None:
        preview_config = validate_config(config, len(QtGui.QGuiApplication.screens()), None)
        self.reconcile_toolbar_windows(preview_config)

    def preview_toolbar_appearance(
        self,
        appearance: dict,
        mode: str,
        active_monitor_id: str,
    ) -> None:
        target_ids: list[str]
        if mode == "per_monitor":
            target_ids = [str(active_monitor_id or "")]
        else:
            target_ids = list(self.toolbar_windows.keys())

        for monitor_id in target_ids:
            if not monitor_id:
                continue
            window = self.toolbar_windows.get(monitor_id)
            if window is None:
                continue
            preview_config = copy.deepcopy(self.config_for_monitor(monitor_id))
            preview_config["appearance"] = copy.deepcopy(appearance)
            window.refresh_config(preview_config, monitor_id)

    def rollback_toolbar_preview(self) -> None:
        self.reconcile_toolbar_windows()

    def config_for_monitor(self, monitor_id: str, config: dict | None = None) -> dict:
        source_config = config or self.config
        if str(source_config.get("monitoring", {}).get("mode") or "single") == "per_monitor":
            ensure_monitor_profile(source_config, monitor_id)
            return effective_config_for_monitor(source_config, monitor_id)
        return copy_shared_config(source_config)

    def profile_id_for_monitor(self, monitor_id: str) -> str | None:
        profile = profile_for_monitor(self.config, monitor_id)
        return str(profile.get("profile_id") or "") if isinstance(profile, dict) else None

    def apply_toolbar_change(self, monitor_id: str, updated_toolbar_config: dict) -> None:
        config = validate_config(self.config, len(QtGui.QGuiApplication.screens()), connected_monitor_ids())
        if str(config.get("monitoring", {}).get("mode") or "single") == "per_monitor":
            update_monitor_profile(config, monitor_id, updated_toolbar_config)
            validated = validate_config(config, len(QtGui.QGuiApplication.screens()), connected_monitor_ids())
            logger.debug("per-monitor profile update monitor_id=%s", monitor_id)
            self.config = save_config(validated, len(QtGui.QGuiApplication.screens()), connected_monitor_ids())
            window = self.toolbar_windows.get(monitor_id)
            if window is not None:
                window.refresh_config(self.config_for_monitor(monitor_id), monitor_id)
            if self.settings_window is not None:
                self.settings_window.refresh_from_config(self.config)
            return
        for key in ("appearance", "behavior", "logo", "menus"):
            if key in updated_toolbar_config:
                config[key] = updated_toolbar_config[key]
        logger.debug("shared toolbar update from monitor_id=%s", monitor_id)
        self.apply_config(config)

    def open_settings(self, preferred_monitor_id: str | None = None) -> None:
        if self.settings_window is None:
            self.settings_window = SettingsWindow(
                self.config,
                self.save_settings_config,
                self.preview_toolbar_appearance,
                self.rollback_toolbar_preview,
                self.preview_working_config,
                None,
            )
            self.settings_window.destroyed.connect(self.clear_settings_window)
        self.settings_window.refresh_from_config(self.config)
        if preferred_monitor_id:
            self.settings_window.select_profile_monitor(preferred_monitor_id)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()
        self.show_toolbars()

    def clear_settings_window(self) -> None:
        self.settings_window = None

    def settings_is_visible(self) -> bool:
        return self.settings_window is not None and self.settings_window.isVisible()

    def show_toolbars(self) -> None:
        self.reconcile_toolbar_windows()
        for window in self.toolbar_windows.values():
            window.show_on_configured_screen()

    def hide_toolbars(self) -> None:
        for window in self.toolbar_windows.values():
            window.hide_menu()

    def any_toolbar_visible(self) -> bool:
        return any(window.is_open for window in self.toolbar_windows.values())

    def toggle_toolbars(self) -> None:
        if self.any_toolbar_visible():
            self.hide_toolbars()
        else:
            self.show_toolbars()

    def exit_application(self) -> None:
        if self.exiting:
            return
        self.exiting = True
        logger.debug("application exit")
        self.monitor_reconcile_timer.stop()
        for monitor_id in list(self.toolbar_windows):
            self.remove_toolbar_for_monitor(monitor_id)
        gui_app = QtGui.QGuiApplication.instance()
        if gui_app is not None:
            try:
                gui_app.screenAdded.disconnect(self.handle_screen_added)
            except (TypeError, RuntimeError):
                pass
            try:
                gui_app.screenRemoved.disconnect(self.handle_screen_removed)
            except (TypeError, RuntimeError):
                pass
        if self.settings_window is not None:
            self.settings_window.close()
            self.settings_window = None
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self.app.quit()

    def connect_all_screen_signals(self) -> None:
        for screen in QtGui.QGuiApplication.screens():
            self.connect_screen_signals(screen)

    def connect_screen_signals(self, screen: QtGui.QScreen | None) -> None:
        if screen is None:
            return
        key = id(screen)
        if key in self.screen_signal_ids:
            return
        screen_id = monitor_id(screen)
        self.screen_signal_ids.add(key)
        self.screen_id_by_object[key] = screen_id
        for signal_name in (
            "geometryChanged",
            "availableGeometryChanged",
            "logicalDotsPerInchChanged",
            "physicalDotsPerInchChanged",
            "orientationChanged",
            "primaryOrientationChanged",
        ):
            signal = getattr(screen, signal_name, None)
            if signal is not None:
                try:
                    signal.connect(lambda *args, target=screen: self.handle_screen_geometry_changed(target))
                except (TypeError, RuntimeError):
                    pass
        logger.debug("screen signals connected monitor_id=%s", screen_id)

    def disconnect_screen_signals(self, screen: QtGui.QScreen | None) -> None:
        if screen is None:
            return
        key = id(screen)
        self.screen_signal_ids.discard(key)
        self.screen_id_by_object.pop(key, None)

    def handle_screen_added(self, screen: QtGui.QScreen) -> None:
        logger.debug("screen added monitor_id=%s", monitor_id(screen))
        self.connect_screen_signals(screen)
        self.schedule_monitor_reconciliation()

    def handle_screen_removed(self, screen: QtGui.QScreen) -> None:
        removed_id = self.screen_id_by_object.get(id(screen)) or monitor_id(screen)
        logger.debug("screen removed monitor_id=%s", removed_id)
        self.disconnect_screen_signals(screen)
        if removed_id:
            self.remove_toolbar_for_monitor(removed_id)
        self.schedule_monitor_reconciliation()

    def handle_screen_geometry_changed(self, screen: QtGui.QScreen) -> None:
        screen_id = monitor_id(screen)
        logger.debug("screen geometry changed monitor_id=%s", screen_id)
        window = self.toolbar_windows.get(screen_id)
        if window is not None:
            window.refresh_screen_geometry()
        self.schedule_monitor_reconciliation()

    def schedule_monitor_reconciliation(self) -> None:
        self.monitor_reconcile_timer.start()

    def reconcile_after_monitor_change(self) -> None:
        self.connect_all_screen_signals()
        self.reconcile_toolbar_windows()
        if self.settings_window is not None:
            self.settings_window.refresh_monitor_list(
                QtGui.QGuiApplication.screens(),
                self.config.get("monitoring", {}).get("known_monitors", {}),
                preserve_unsaved=True,
            )
            self.ensure_settings_on_connected_screen()

    def update_known_monitors(self) -> None:
        monitoring = self.config.setdefault("monitoring", {})
        known = monitoring.get("known_monitors")
        if not isinstance(known, dict):
            known = {}
            monitoring["known_monitors"] = known
        for index, screen in enumerate(QtGui.QGuiApplication.screens()):
            screen_id = monitor_id(screen)
            if not screen_id:
                continue
            existing = known.get(screen_id, {})
            metadata = monitor_metadata(screen, index)
            if isinstance(existing, dict):
                metadata = {**existing, **metadata}
            known[screen_id] = metadata

    def ensure_settings_on_connected_screen(self) -> None:
        if self.settings_window is None or not self.settings_window.isVisible():
            return
        screens = QtGui.QGuiApplication.screens()
        if not screens:
            return
        center = self.settings_window.frameGeometry().center()
        if QtGui.QGuiApplication.screenAt(center) is not None:
            return
        target = QtGui.QGuiApplication.primaryScreen() or screens[0]
        geometry = target.geometry()
        frame = self.settings_window.frameGeometry()
        self.settings_window.move(geometry.center() - QtCore.QPoint(frame.width() // 2, frame.height() // 2))
