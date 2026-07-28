from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from app_icon import apply_window_icon
from profile_package_manager import (
    DetailedPackageInspection,
    ImportProfilePlan,
    MonitorMappingPlan,
    ProfileInspection,
    TargetIssue,
)


class TargetReviewDialog(QtWidgets.QDialog):
    def __init__(
        self,
        profile: ProfileInspection,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.issues = list(profile.missing_targets)
        self.setWindowTitle("Review Launcher Targets")
        apply_window_icon(self)
        self.resize(980, 520)

        layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Profile", "Launcher name", "Target type", "Imported target", "Status", "Replacement target"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        for issue in self.issues:
            self.add_issue_row(issue)

        row_buttons = QtWidgets.QHBoxLayout()
        browse_file = QtWidgets.QPushButton("Browse File")
        browse_folder = QtWidgets.QPushButton("Browse Folder")
        clear_target = QtWidgets.QPushButton("Clear Target")
        browse_file.clicked.connect(self.browse_file)
        browse_folder.clicked.connect(self.browse_folder)
        clear_target.clicked.connect(self.clear_selected_targets)
        row_buttons.addWidget(browse_file)
        row_buttons.addWidget(browse_folder)
        row_buttons.addWidget(clear_target)
        row_buttons.addStretch()
        layout.addLayout(row_buttons)

        prefix_group = QtWidgets.QGroupBox("Path Prefix Replacement")
        prefix_layout = QtWidgets.QFormLayout(prefix_group)
        self.old_prefix_edit = QtWidgets.QLineEdit()
        self.new_prefix_edit = QtWidgets.QLineEdit()
        self.include_working_dirs_check = QtWidgets.QCheckBox("Include working directories and folder menus")
        preview_button = QtWidgets.QPushButton("Preview Count")
        apply_prefix_button = QtWidgets.QPushButton("Apply Prefix")
        preview_button.clicked.connect(self.preview_prefix_count)
        apply_prefix_button.clicked.connect(self.apply_prefix_replacement)
        prefix_layout.addRow("Old", self.old_prefix_edit)
        prefix_layout.addRow("New", self.new_prefix_edit)
        prefix_layout.addRow("", self.include_working_dirs_check)
        prefix_buttons = QtWidgets.QHBoxLayout()
        prefix_buttons.addWidget(preview_button)
        prefix_buttons.addWidget(apply_prefix_button)
        prefix_buttons.addStretch()
        prefix_layout.addRow("", prefix_buttons)
        layout.addWidget(prefix_group)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_issue_row(self, issue: TargetIssue) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            issue.profile_name,
            issue.launcher_name,
            issue.target_type,
            issue.target,
            issue.status,
            "",
        ]
        for column, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(value)
            if column != 5:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, column, item)

    def selected_rows(self) -> list[int]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        return rows or ([self.table.currentRow()] if self.table.currentRow() >= 0 else [])

    def browse_file(self) -> None:
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(self, "Replacement File")
        if path:
            self.set_replacement_for_selected(path)

    def browse_folder(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Replacement Folder")
        if path:
            self.set_replacement_for_selected(path)

    def set_replacement_for_selected(self, value: str) -> None:
        for row in self.selected_rows():
            self.table.item(row, 5).setText(value)

    def clear_selected_targets(self) -> None:
        self.set_replacement_for_selected("")

    def preview_prefix_count(self) -> None:
        count = len(self.prefix_matches())
        QtWidgets.QMessageBox.information(self, "Prefix Replacement", f"{count} target path{'s' if count != 1 else ''} would be updated.")

    def apply_prefix_replacement(self) -> None:
        old = self.old_prefix_edit.text().strip()
        new = self.new_prefix_edit.text().strip()
        if not old:
            return
        count = 0
        for row, issue in enumerate(self.issues):
            replaced = replace_path_prefix(issue.target, old, new)
            if replaced != issue.target:
                self.table.item(row, 5).setText(replaced)
                count += 1
        QtWidgets.QMessageBox.information(self, "Prefix Replacement", f"Updated {count} replacement target{'s' if count != 1 else ''}.")

    def prefix_matches(self) -> list[TargetIssue]:
        old = self.old_prefix_edit.text().strip()
        if not old:
            return []
        return [issue for issue in self.issues if replace_path_prefix(issue.target, old, "X") != issue.target]

    def accept(self) -> None:
        remaining: list[TargetIssue] = []
        for row, issue in enumerate(self.issues):
            replacement = self.table.item(row, 5).text().strip()
            if replacement:
                replace_first_matching_target(self.profile.profile_data, issue, replacement)
            else:
                remaining.append(issue)
        self.profile.missing_targets = remaining
        super().accept()


class ProfileImportDialog(QtWidgets.QDialog):
    def __init__(
        self,
        inspection: DetailedPackageInspection,
        existing_profiles: list[dict[str, Any]],
        connected_monitors: list[dict[str, Any]],
        active_profile_id: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.inspection = inspection
        self.existing_profiles = copy.deepcopy(existing_profiles)
        self.connected_monitors = connected_monitors
        self.active_profile_id = active_profile_id
        self.row_profiles: dict[int, ProfileInspection] = {}
        self.profiles_by_id: dict[str, ProfileInspection] = {
            profile.profile_id: profile for profile in inspection.profiles
        }
        self.mapping_tables: dict[str, QtWidgets.QTableWidget] = {}

        self.setWindowTitle("Import Profiles")
        apply_window_icon(self)
        self.resize(1120, 680)

        layout = QtWidgets.QVBoxLayout(self)
        self.summary_label = QtWidgets.QLabel()
        layout.addWidget(self.summary_label)

        controls = QtWidgets.QHBoxLayout()
        select_all = QtWidgets.QPushButton("Select All")
        select_none = QtWidgets.QPushButton("Select None")
        select_all.clicked.connect(lambda: self.set_all_checked(True))
        select_none.clicked.connect(lambda: self.set_all_checked(False))
        controls.addWidget(select_all)
        controls.addWidget(select_none)
        controls.addStretch()
        layout.addLayout(controls)

        self.table = QtWidgets.QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            [
                "Import",
                "Profile name",
                "Package profile ID",
                "Mode",
                "Monitor toolbars",
                "Missing targets",
                "Conflict status",
                "Import action",
                "Replace target",
                "Confirm replace",
            ]
        )
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.currentCellChanged.connect(lambda *_args: self.refresh_mapping_stack())
        layout.addWidget(self.table, 1)

        self.review_targets_button = QtWidgets.QPushButton("Review Targets...")
        self.review_targets_button.clicked.connect(self.review_targets)
        layout.addWidget(self.review_targets_button, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        self.mapping_stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.mapping_stack)

        if inspection.warnings:
            warning = QtWidgets.QLabel("Warnings: " + "; ".join(inspection.warnings))
            warning.setWordWrap(True)
            layout.addWidget(warning)

        buttons = QtWidgets.QDialogButtonBox()
        self.import_button = buttons.addButton("Import Selected", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Cancel", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.populate()

    def populate(self) -> None:
        self.table.setSortingEnabled(False)
        for profile in self.inspection.profiles:
            self.add_profile_row(profile)
        self.table.setSortingEnabled(True)
        self.refresh_summary()
        self.refresh_mapping_stack()

    def add_profile_row(self, profile: ProfileInspection) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.row_profiles[row] = profile

        checkbox = QtWidgets.QCheckBox()
        checkbox.setChecked(profile.valid)
        checkbox.setEnabled(profile.valid)
        checkbox.toggled.connect(lambda _checked=False: self.refresh_summary())
        self.table.setCellWidget(row, 0, centered_widget(checkbox))

        values = [
            profile.name,
            profile.profile_id,
            profile.mode,
            str(len(profile.monitor_toolbars)),
            str(len(profile.missing_targets)),
            self.conflict_status(profile),
        ]
        for offset, value in enumerate(values, start=1):
            item = QtWidgets.QTableWidgetItem(value)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, profile.profile_id)
            if not profile.valid:
                item.setToolTip(profile.error)
                item.setForeground(QtGui.QBrush(QtGui.QColor("#888888")))
            self.table.setItem(row, offset, item)

        action_combo = QtWidgets.QComboBox()
        action_combo.addItem("Import as New", "new")
        action_combo.addItem("Replace Existing", "replace")
        action_combo.addItem("Skip", "skip")
        action_combo.setCurrentIndex(0 if profile.valid else 2)
        action_combo.setEnabled(profile.valid)
        action_combo.currentIndexChanged.connect(lambda _index, target_row=row: self.update_row_replace_state(target_row))
        self.table.setCellWidget(row, 7, action_combo)

        replace_combo = QtWidgets.QComboBox()
        replace_combo.addItem("Select local profile...", "")
        for existing in self.existing_profiles:
            profile_id = str(existing.get("profile_id") or "")
            replace_combo.addItem(f"{existing.get('name', profile_id)} ({profile_id})", profile_id)
        default_target = self.default_replace_target(profile)
        if default_target:
            index = replace_combo.findData(default_target)
            if index >= 0:
                replace_combo.setCurrentIndex(index)
        self.table.setCellWidget(row, 8, replace_combo)

        confirm = QtWidgets.QCheckBox()
        self.table.setCellWidget(row, 9, centered_widget(confirm))
        self.update_row_replace_state(row)
        self.add_mapping_page(profile)

    def add_mapping_page(self, profile: ProfileInspection) -> None:
        page = QtWidgets.QWidget()
        page.setProperty("profile_id", profile.profile_id)
        layout = QtWidgets.QVBoxLayout(page)
        if not profile.monitor_toolbars:
            label = QtWidgets.QLabel("This profile uses the shared toolbar.")
            layout.addWidget(label)
            self.mapping_stack.addWidget(page)
            return
        label = QtWidgets.QLabel(f"Monitor Mapping for {profile.name}")
        layout.addWidget(label)
        table = QtWidgets.QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Imported monitor toolbar", "Imported metadata", "Destination"])
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        used_targets: set[str] = set()
        for index, monitor in enumerate(profile.monitor_toolbars):
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(monitor.label))
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(format_monitor_metadata(monitor.metadata)))
            combo = QtWidgets.QComboBox()
            for connected in self.connected_monitors:
                combo.addItem(str(connected.get("label") or connected.get("monitor_id")), str(connected.get("monitor_id") or ""))
            combo.addItem("Keep Unmapped", "__unmapped__")
            combo.addItem("Use as Shared Toolbar", "__shared__")
            default_target = self.default_monitor_target(profile, monitor, index, used_targets)
            combo.setCurrentIndex(max(0, combo.findData(default_target)))
            if default_target and default_target not in {"__unmapped__", "__shared__"}:
                used_targets.add(default_target)
            table.setCellWidget(row, 2, combo)
        self.mapping_tables[profile.profile_id] = table
        self.mapping_stack.addWidget(page)

    def conflict_status(self, profile: ProfileInspection) -> str:
        id_match = any(str(item.get("profile_id") or "") == profile.profile_id for item in self.existing_profiles)
        name_match = any(str(item.get("name") or "").casefold() == profile.name.casefold() for item in self.existing_profiles)
        if id_match and name_match:
            return "Name and ID already exist"
        if id_match:
            return "Profile ID already exists"
        if name_match:
            return "Name already exists"
        if not profile.valid:
            return profile.error or "Invalid profile"
        return "No conflict"

    def default_replace_target(self, profile: ProfileInspection) -> str:
        id_target = next((str(item.get("profile_id") or "") for item in self.existing_profiles if str(item.get("profile_id") or "") == profile.profile_id), "")
        name_target = next((str(item.get("profile_id") or "") for item in self.existing_profiles if str(item.get("name") or "").casefold() == profile.name.casefold()), "")
        return id_target if id_target and (not name_target or name_target == id_target) else name_target

    def update_row_replace_state(self, row: int) -> None:
        action = self.row_action(row)
        replace_combo = self.table.cellWidget(row, 8)
        confirm_widget = self.table.cellWidget(row, 9)
        confirm = confirm_widget.findChild(QtWidgets.QCheckBox) if confirm_widget else None
        enabled = action == "replace"
        if replace_combo is not None:
            replace_combo.setEnabled(enabled)
        if confirm is not None:
            confirm.setEnabled(enabled)

    def default_monitor_target(
        self,
        profile: ProfileInspection,
        monitor: Any,
        index: int,
        used_targets: set[str],
    ) -> str:
        source_id = monitor.source_monitor_id
        for connected in self.connected_monitors:
            monitor_id = str(connected.get("monitor_id") or "")
            if monitor_id == source_id and monitor_id not in used_targets:
                return monitor_id
        if len(profile.monitor_toolbars) == 1:
            primary = next((str(item.get("monitor_id") or "") for item in self.connected_monitors if item.get("primary")), "")
            if primary and primary not in used_targets:
                return primary
        if index < len(self.connected_monitors):
            monitor_id = str(self.connected_monitors[index].get("monitor_id") or "")
            if monitor_id and monitor_id not in used_targets:
                return monitor_id
        return "__unmapped__"

    def set_all_checked(self, checked: bool) -> None:
        for row in range(self.table.rowCount()):
            profile = self.profile_for_row(row)
            checkbox = self.row_checkbox(row)
            if checkbox is not None and profile is not None and profile.valid:
                checkbox.setChecked(checked)
        self.refresh_summary()

    def refresh_summary(self) -> None:
        selected = sum(1 for row in range(self.table.rowCount()) if self.row_checked(row))
        total = len(self.inspection.profiles)
        self.summary_label.setText(f"{total} profile{'s' if total != 1 else ''} in package. {selected} selected for import.")

    def refresh_mapping_stack(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        profile = self.profile_for_row(row)
        if profile is not None:
            self.set_mapping_page(profile.profile_id)
        self.review_targets_button.setEnabled(bool(profile and profile.missing_targets))

    def review_targets(self) -> None:
        profile = self.profile_for_row(self.table.currentRow())
        if profile is None or not profile.missing_targets:
            return
        dialog = TargetReviewDialog(profile, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            row = self.table.currentRow()
            if row >= 0:
                self.table.item(row, 5).setText(str(len(profile.missing_targets)))
            self.refresh_mapping_stack()

    def row_checkbox(self, row: int) -> QtWidgets.QCheckBox | None:
        widget = self.table.cellWidget(row, 0)
        return widget.findChild(QtWidgets.QCheckBox) if widget else None

    def row_checked(self, row: int) -> bool:
        checkbox = self.row_checkbox(row)
        return bool(checkbox and checkbox.isChecked())

    def profile_for_row(self, row: int) -> ProfileInspection | None:
        if row < 0:
            return None
        item = self.table.item(row, 1)
        profile_id = str(item.data(QtCore.Qt.ItemDataRole.UserRole) or "") if item is not None else ""
        return self.profiles_by_id.get(profile_id)

    def set_mapping_page(self, profile_id: str) -> None:
        for index in range(self.mapping_stack.count()):
            widget = self.mapping_stack.widget(index)
            if str(widget.property("profile_id") or "") == profile_id:
                self.mapping_stack.setCurrentIndex(index)
                return

    def row_action(self, row: int) -> str:
        combo = self.table.cellWidget(row, 7)
        return str(combo.currentData() or "skip") if isinstance(combo, QtWidgets.QComboBox) else "skip"

    def accept(self) -> None:
        for row in range(self.table.rowCount()):
            profile = self.profile_for_row(row)
            if profile is None:
                continue
            if not self.row_checked(row):
                continue
            if self.row_action(row) == "replace":
                target = self.replace_target(row)
                confirmed = self.replace_confirmed(row)
                if not target or not confirmed:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Import Profiles",
                        f"Confirm the local profile to replace for {profile.name}.",
                    )
                    return
        super().accept()

    def replace_target(self, row: int) -> str:
        combo = self.table.cellWidget(row, 8)
        return str(combo.currentData() or "") if isinstance(combo, QtWidgets.QComboBox) else ""

    def replace_confirmed(self, row: int) -> bool:
        widget = self.table.cellWidget(row, 9)
        checkbox = widget.findChild(QtWidgets.QCheckBox) if widget else None
        return bool(checkbox and checkbox.isChecked())

    def import_plans(self) -> list[ImportProfilePlan]:
        plans: list[ImportProfilePlan] = []
        for row in range(self.table.rowCount()):
            profile = self.profile_for_row(row)
            if profile is None:
                continue
            action = self.row_action(row) if self.row_checked(row) else "skip"
            mappings = self.monitor_mappings_for_profile(profile)
            plans.append(
                ImportProfilePlan(
                    package_profile_id=profile.profile_id,
                    action=action,
                    target_profile_id=self.replace_target(row) if action == "replace" else "",
                    monitor_mappings=mappings,
                    profile_data=copy.deepcopy(profile.profile_data),
                )
            )
        return plans

    def monitor_mappings_for_profile(self, profile: ProfileInspection) -> list[MonitorMappingPlan]:
        table = self.mapping_tables.get(profile.profile_id)
        if table is None:
            return []
        mappings: list[MonitorMappingPlan] = []
        for row, monitor in enumerate(profile.monitor_toolbars):
            combo = table.cellWidget(row, 2)
            value = str(combo.currentData() or "__unmapped__") if isinstance(combo, QtWidgets.QComboBox) else "__unmapped__"
            if value == "__shared__":
                mappings.append(MonitorMappingPlan(monitor.source_monitor_id, "shared"))
            elif value == "__unmapped__":
                mappings.append(MonitorMappingPlan(monitor.source_monitor_id, "unmapped"))
            else:
                mappings.append(MonitorMappingPlan(monitor.source_monitor_id, "monitor", value))
        return mappings


def centered_widget(widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
    container = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addStretch()
    layout.addWidget(widget)
    layout.addStretch()
    return container


def format_monitor_metadata(metadata: dict[str, Any]) -> str:
    parts = []
    display = str(metadata.get("display_name") or "")
    if display:
        parts.append(display)
    geometry = metadata.get("last_geometry")
    if isinstance(geometry, list) and len(geometry) >= 4:
        parts.append(f"{geometry[2]} x {geometry[3]}")
    manufacturer = str(metadata.get("manufacturer") or "")
    model = str(metadata.get("model") or "")
    hardware = " ".join(part for part in (manufacturer, model) if part)
    if hardware:
        parts.append(hardware)
    return " | ".join(parts)


def replace_path_prefix(value: str, old_prefix: str, new_prefix: str) -> str:
    if value.lower().startswith(("http://", "https://")):
        return value
    old = old_prefix.rstrip("\\/")
    candidate = value
    compare_candidate = os.path.normcase(candidate)
    compare_old = os.path.normcase(old)
    if not compare_candidate.startswith(compare_old):
        return value
    remainder = candidate[len(old):]
    if remainder and remainder[0] not in {"\\", "/"}:
        return value
    return new_prefix.rstrip("\\/") + remainder


def replace_first_matching_target(profile_data: dict[str, Any], issue: TargetIssue, replacement: str) -> None:
    replace_targets_in_toolbar(profile_data.get("shared", {}), issue, replacement)
    monitor_profiles = profile_data.get("monitor_profiles", {})
    if isinstance(monitor_profiles, dict):
        for toolbar in monitor_profiles.values():
            if isinstance(toolbar, dict):
                replace_targets_in_toolbar(toolbar, issue, replacement)


def replace_targets_in_toolbar(toolbar: Any, issue: TargetIssue, replacement: str) -> bool:
    if not isinstance(toolbar, dict):
        return False
    logo = toolbar.get("logo", {})
    if isinstance(logo, dict):
        launcher = logo.get("left_click_launcher")
        if isinstance(launcher, dict) and replace_item_target(launcher, issue, replacement):
            return True
        for item in logo.get("menu_items", []):
            if isinstance(item, dict) and replace_targets_in_item(item, issue, replacement):
                return True
    for menu in toolbar.get("menus", []):
        if isinstance(menu, dict) and replace_targets_in_item(menu, issue, replacement):
            return True
    return False


def replace_targets_in_item(item: dict[str, Any], issue: TargetIssue, replacement: str) -> bool:
    if replace_item_target(item, issue, replacement):
        return True
    for child in item.get("items", []):
        if isinstance(child, dict) and replace_targets_in_item(child, issue, replacement):
            return True
    return False


def replace_item_target(item: dict[str, Any], issue: TargetIssue, replacement: str) -> bool:
    if str(item.get("name") or "Launcher") != issue.launcher_name:
        return False
    if str(item.get(issue.field) or "") != issue.target:
        return False
    item[issue.field] = replacement
    return True
