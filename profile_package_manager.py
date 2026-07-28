from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from config_manager import (
    default_config,
    new_profile_id,
    runtime_config_from_profile_json,
    safe_profile_id,
    user_profile_dir,
    user_profile_json_path,
    user_profile_staging_dir,
)


PACKAGE_FORMAT = "ToolBar2_profiles"
LEGACY_PACKAGE_FORMATS = {"mci_toolbar_profiles"}
FORMAT_VERSION = 1
MAX_ZIP_ENTRIES = 2500
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
SUPPORTED_ASSET_SUFFIXES = {".png", ".gif", ".jpg", ".jpeg", ".webp", ".svg", ".ico"}


@dataclass
class ExportResult:
    success: bool
    destination: Path
    exported_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class PackageInspection:
    success: bool
    package_type: str = ""
    active_profile_id: str = ""
    profiles: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class TargetIssue:
    profile_id: str
    profile_name: str
    launcher_name: str
    target_type: str
    target: str
    field: str
    status: str


@dataclass
class MonitorToolbarInfo:
    source_monitor_id: str
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProfileInspection:
    profile_id: str
    name: str
    path: str
    valid: bool
    error: str = ""
    mode: str = "Shared"
    monitor_toolbars: list[MonitorToolbarInfo] = field(default_factory=list)
    missing_targets: list[TargetIssue] = field(default_factory=list)
    profile_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetailedPackageInspection:
    success: bool
    package_type: str = ""
    active_profile_id: str = ""
    profiles: list[ProfileInspection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class MonitorMappingPlan:
    source_monitor_id: str
    action: str
    target_monitor_id: str = ""


@dataclass
class ImportProfilePlan:
    package_profile_id: str
    action: str
    target_profile_id: str = ""
    monitor_mappings: list[MonitorMappingPlan] = field(default_factory=list)
    profile_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportResult:
    success: bool
    imported_profiles: list[dict[str, Any]] = field(default_factory=list)
    selected_profile_id: str = ""
    imported_as_new: int = 0
    replaced: int = 0
    skipped: int = 0
    unmapped_monitor_toolbars: int = 0
    missing_targets_left: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def export_profile_package(
    destination: Path,
    profile_ids: list[str],
    active_profile_id: str,
) -> ExportResult:
    destination = Path(destination)
    warnings: list[str] = []
    errors: list[str] = []
    records: list[tuple[str, dict[str, Any], Path]] = []
    seen: set[str] = set()

    for requested_id in profile_ids:
        profile_id = safe_profile_id(str(requested_id or ""))
        if not profile_id or profile_id in seen:
            continue
        seen.add(profile_id)
        profile_data, error = load_committed_profile(profile_id)
        if profile_data is None:
            warnings.append(error or f"Skipped invalid profile: {profile_id}")
            continue
        records.append((profile_id, profile_data, user_profile_dir(profile_id)))

    if not records:
        return ExportResult(False, destination, warnings=warnings, errors=["No valid profiles were available to export."])

    manifest_profiles = [
        {
            "profile_id": profile_id,
            "name": str(profile_data.get("name") or profile_id),
            "path": f"profiles/{profile_id}/profile.json",
        }
        for profile_id, profile_data, _folder in records
    ]
    manifest = {
        "package_format": PACKAGE_FORMAT,
        "format_version": FORMAT_VERSION,
        "package_type": "single_profile" if len(records) == 1 else "profile_bundle",
        "active_profile_id": safe_profile_id(str(active_profile_id or "")),
        "profiles": manifest_profiles,
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.",
            suffix=".tmp",
            dir=str(destination.parent),
        )
        os.close(handle)
        with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
            for profile_id, _profile_data, folder in records:
                write_profile_folder_to_zip(package, profile_id, folder)
        os.replace(temp_name, destination)
    except Exception as exc:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        return ExportResult(False, destination, warnings=warnings, errors=[str(exc) or "The profile export failed."])

    return ExportResult(True, destination, exported_count=len(records), warnings=warnings)


def inspect_profile_package(zip_path: Path) -> PackageInspection:
    with tempfile.TemporaryDirectory(prefix="ToolBar2-profile-inspect-") as temp_dir:
        extracted = Path(temp_dir)
        errors = validate_and_extract_zip(Path(zip_path), extracted)
        if errors:
            return PackageInspection(False, errors=errors)
        manifest, errors = load_manifest(extracted)
        if errors:
            return PackageInspection(False, errors=errors)
        return PackageInspection(
            True,
            package_type=str(manifest.get("package_type") or ""),
            active_profile_id=str(manifest.get("active_profile_id") or ""),
            profiles=[
                {
                    "profile_id": str(profile.get("profile_id") or ""),
                    "name": str(profile.get("name") or ""),
                    "path": str(profile.get("path") or ""),
                }
                for profile in manifest.get("profiles", [])
                if isinstance(profile, dict)
            ],
        )


def inspect_profile_package_detailed(zip_path: Path) -> DetailedPackageInspection:
    with tempfile.TemporaryDirectory(prefix="ToolBar2-profile-inspect-") as temp_dir:
        extracted = Path(temp_dir)
        errors = validate_and_extract_zip(Path(zip_path), extracted)
        if errors:
            return DetailedPackageInspection(False, errors=errors)
        manifest, errors = load_manifest(extracted)
        if errors:
            return DetailedPackageInspection(False, errors=errors)

        profiles: list[ProfileInspection] = []
        warnings: list[str] = []
        for manifest_profile in manifest.get("profiles", []):
            if not isinstance(manifest_profile, dict):
                warnings.append("Skipped unreadable profile manifest entry.")
                continue
            profile_path = str(manifest_profile.get("path") or "")
            profile_id = safe_profile_id(str(manifest_profile.get("profile_id") or ""))
            profile_name = str(manifest_profile.get("name") or profile_id or "Imported Profile")
            try:
                profile_data = load_profile_json_from_path(extracted / profile_path)
                profile_id = safe_profile_id(str(profile_data.get("profile_id") or profile_id))
                profile_name = str(profile_data.get("name") or profile_name)
                validate_profile_asset_references(profile_data)
                runtime_config_from_profile_json(default_config(), profile_data)
                monitor_infos = monitor_toolbar_infos(profile_data)
                profiles.append(
                    ProfileInspection(
                        profile_id=profile_id,
                        name=profile_name,
                        path=profile_path,
                        valid=True,
                        mode="Monitor-specific" if monitor_infos else "Shared",
                        monitor_toolbars=monitor_infos,
                        missing_targets=collect_profile_target_issues(profile_id, profile_name, profile_data),
                        profile_data=profile_data,
                    )
                )
            except Exception as exc:
                profiles.append(
                    ProfileInspection(
                        profile_id=profile_id,
                        name=profile_name,
                        path=profile_path,
                        valid=False,
                        error=str(exc) or "Invalid profile.",
                    )
                )
        return DetailedPackageInspection(
            True,
            package_type=str(manifest.get("package_type") or ""),
            active_profile_id=str(manifest.get("active_profile_id") or ""),
            profiles=profiles,
            warnings=warnings,
        )


def import_profile_package_to_staging(
    zip_path: Path,
    staging_session_id: str,
    existing_profiles: list[dict[str, Any]],
) -> ImportResult:
    with tempfile.TemporaryDirectory(prefix="ToolBar2-profile-import-") as temp_dir:
        extracted = Path(temp_dir)
        errors = validate_and_extract_zip(Path(zip_path), extracted)
        if errors:
            return ImportResult(False, errors=errors)

        manifest, errors = load_manifest(extracted)
        if errors:
            return ImportResult(False, errors=errors)

        existing_names = {
            str(profile.get("name") or "").strip().casefold()
            for profile in existing_profiles
            if isinstance(profile, dict)
        }
        existing_ids = {
            safe_profile_id(str(profile.get("profile_id") or ""))
            for profile in existing_profiles
            if isinstance(profile, dict)
        }
        imported: list[dict[str, Any]] = []
        staged_copies: list[Path] = []

        for manifest_profile in manifest.get("profiles", []):
            if not isinstance(manifest_profile, dict):
                continue
            profile_path = str(manifest_profile.get("path") or "")
            profile_file = extracted / profile_path
            try:
                profile_data = load_profile_json_from_path(profile_file)
                validate_profile_asset_references(profile_data)
                runtime_config_from_profile_json(default_config(), profile_data)
                old_profile_id = safe_profile_id(str(profile_data.get("profile_id") or ""))
                if not old_profile_id:
                    raise ValueError(f"Invalid profile id in {profile_path}")
                source_folder = extracted / "profiles" / old_profile_id
                if not source_folder.exists():
                    raise ValueError(f"Missing profile folder for {old_profile_id}")
                new_id = unique_new_profile_id(existing_ids)
                existing_ids.add(new_id)
                imported_name = unique_imported_name(str(profile_data.get("name") or "Imported Profile"), existing_names)
                existing_names.add(imported_name.casefold())
                staged_folder = user_profile_staging_dir(staging_session_id) / new_id
                shutil.copytree(source_folder, staged_folder)
                staged_copies.append(staged_folder)
                imported_profile = copy.deepcopy(profile_data)
                imported_profile["profile_id"] = new_id
                imported_profile["name"] = imported_name
                rewrite_asset_paths_for_staging(imported_profile, staging_session_id, new_id)
                runtime_config_from_profile_json(default_config(), imported_profile)
                imported.append(imported_profile)
            except Exception as exc:
                cleanup_paths(staged_copies)
                return ImportResult(False, errors=[str(exc) or "The profile package could not be imported."])

        if not imported:
            return ImportResult(False, errors=["The package did not contain any valid profiles."])

        return ImportResult(
            True,
            imported_profiles=imported,
            selected_profile_id=str(imported[0].get("profile_id") or ""),
            imported_as_new=len(imported),
            missing_targets_left=sum(len(collect_profile_target_issues(str(profile.get("profile_id") or ""), str(profile.get("name") or ""), profile)) for profile in imported),
        )


def import_profile_package_plan_to_staging(
    zip_path: Path,
    staging_session_id: str,
    existing_profiles: list[dict[str, Any]],
    plans: list[ImportProfilePlan],
) -> ImportResult:
    selected_plans = [plan for plan in plans if plan.action in {"new", "replace"}]
    skipped = sum(1 for plan in plans if plan.action == "skip")
    if not selected_plans:
        return ImportResult(True, skipped=skipped)

    with tempfile.TemporaryDirectory(prefix="ToolBar2-profile-import-") as temp_dir:
        extracted = Path(temp_dir)
        errors = validate_and_extract_zip(Path(zip_path), extracted)
        if errors:
            return ImportResult(False, skipped=skipped, errors=errors)
        manifest, errors = load_manifest(extracted)
        if errors:
            return ImportResult(False, skipped=skipped, errors=errors)

        manifest_by_id: dict[str, dict[str, Any]] = {}
        for profile in manifest.get("profiles", []):
            if isinstance(profile, dict):
                manifest_by_id[safe_profile_id(str(profile.get("profile_id") or ""))] = profile

        existing_names = {
            str(profile.get("name") or "").strip().casefold()
            for profile in existing_profiles
            if isinstance(profile, dict)
        }
        existing_ids = {
            safe_profile_id(str(profile.get("profile_id") or ""))
            for profile in existing_profiles
            if isinstance(profile, dict)
        }
        imported: list[dict[str, Any]] = []
        staged_copies: list[Path] = []
        imported_as_new = 0
        replaced = 0
        unmapped_count = 0
        warnings: list[str] = []

        try:
            for plan in selected_plans:
                manifest_profile = manifest_by_id.get(safe_profile_id(plan.package_profile_id))
                if manifest_profile is None:
                    warnings.append(f"Profile not found in package: {plan.package_profile_id}")
                    skipped += 1
                    continue
                profile_path = str(manifest_profile.get("path") or "")
                profile_data = copy.deepcopy(plan.profile_data) if plan.profile_data else load_profile_json_from_path(extracted / profile_path)
                validate_profile_asset_references(profile_data)
                runtime_config_from_profile_json(default_config(), profile_data)
                old_profile_id = safe_profile_id(str(plan.package_profile_id or profile_data.get("profile_id") or ""))
                source_folder = extracted / "profiles" / old_profile_id
                if not source_folder.exists():
                    raise ValueError(f"Missing profile folder for {old_profile_id}")

                if plan.action == "replace":
                    final_id = safe_profile_id(plan.target_profile_id)
                    if not final_id:
                        warnings.append(f"Skipped {profile_data.get('name', old_profile_id)}: no replacement target selected.")
                        skipped += 1
                        continue
                    final_name = str(profile_data.get("name") or final_id)
                    replaced += 1
                else:
                    final_id = unique_new_profile_id(existing_ids)
                    base_name = str(profile_data.get("name") or "Imported Profile").strip() or "Imported Profile"
                    final_name = base_name if base_name.casefold() not in existing_names else unique_imported_name(base_name, existing_names)
                    imported_as_new += 1
                existing_ids.add(final_id)
                existing_names.add(final_name.casefold())

                planned_profile = copy.deepcopy(profile_data)
                apply_monitor_mappings(planned_profile, plan.monitor_mappings)
                planned_profile["profile_id"] = final_id
                planned_profile["name"] = final_name
                staged_folder = user_profile_staging_dir(staging_session_id) / final_id
                if staged_folder.exists():
                    shutil.rmtree(staged_folder)
                shutil.copytree(source_folder, staged_folder)
                staged_copies.append(staged_folder)
                rewrite_asset_paths_for_staging(planned_profile, staging_session_id, final_id)
                runtime_config_from_profile_json(default_config(), planned_profile)
                unmapped_count += len(planned_profile.get("unmapped_monitor_profiles", []) if isinstance(planned_profile.get("unmapped_monitor_profiles"), list) else [])
                imported.append(planned_profile)
        except Exception as exc:
            cleanup_paths(staged_copies)
            return ImportResult(False, skipped=skipped, warnings=warnings, errors=[str(exc) or "The profile package could not be imported."])

        return ImportResult(
            True,
            imported_profiles=imported,
            selected_profile_id=str(imported[0].get("profile_id") or "") if imported else "",
            imported_as_new=imported_as_new,
            replaced=replaced,
            skipped=skipped,
            unmapped_monitor_toolbars=unmapped_count,
            missing_targets_left=sum(
                len(collect_profile_target_issues(str(profile.get("profile_id") or ""), str(profile.get("name") or ""), profile))
                for profile in imported
            ),
            warnings=warnings,
        )


def load_committed_profile(profile_id: str) -> tuple[dict[str, Any] | None, str]:
    path = user_profile_json_path(profile_id)
    try:
        profile_data = load_profile_json_from_path(path)
        validate_profile_asset_references(profile_data, allow_committed_prefix=True)
        runtime_config_from_profile_json(default_config(), profile_data)
        return profile_data, ""
    except Exception as exc:
        return None, f"{profile_id}: {exc}"


def monitor_toolbar_infos(profile_data: dict[str, Any]) -> list[MonitorToolbarInfo]:
    monitor_profiles = profile_data.get("monitor_profiles", {})
    if not isinstance(monitor_profiles, dict):
        return []
    known = profile_data.get("monitoring", {}).get("known_monitors", {})
    if not isinstance(known, dict):
        known = {}
    infos: list[MonitorToolbarInfo] = []
    for index, monitor_id in enumerate(monitor_profiles):
        metadata = copy.deepcopy(known.get(monitor_id, {})) if isinstance(known.get(monitor_id), dict) else {}
        label = str(metadata.get("display_name") or f"Imported Monitor {index + 1}")
        infos.append(MonitorToolbarInfo(monitor_id, label, metadata))
    return infos


def apply_monitor_mappings(profile_data: dict[str, Any], mappings: list[MonitorMappingPlan]) -> None:
    if not mappings:
        return
    monitor_profiles = profile_data.get("monitor_profiles", {})
    if not isinstance(monitor_profiles, dict):
        return
    monitoring = profile_data.setdefault("monitoring", {})
    known = monitoring.get("known_monitors", {})
    if not isinstance(known, dict):
        known = {}
        monitoring["known_monitors"] = known
    selected_ids: list[str] = []
    next_profiles: dict[str, Any] = {}
    unmapped = profile_data.get("unmapped_monitor_profiles", [])
    if not isinstance(unmapped, list):
        unmapped = []
    mapping_by_source = {mapping.source_monitor_id: mapping for mapping in mappings}

    for source_id, toolbar in monitor_profiles.items():
        mapping = mapping_by_source.get(str(source_id))
        if mapping is None:
            next_profiles[str(source_id)] = toolbar
            selected_ids.append(str(source_id))
            continue
        if mapping.action == "shared":
            for key in ("appearance", "behavior", "logo", "menus"):
                profile_data.setdefault("shared", {})[key] = copy.deepcopy(toolbar.get(key))
            continue
        if mapping.action == "monitor" and mapping.target_monitor_id:
            target_id = str(mapping.target_monitor_id)
            if target_id not in next_profiles:
                next_profiles[target_id] = toolbar
                selected_ids.append(target_id)
            continue
        metadata = copy.deepcopy(known.get(source_id, {})) if isinstance(known.get(source_id), dict) else {}
        unmapped.append(
            {
                "source_monitor_id": str(source_id),
                "source_monitor_metadata": metadata,
                "toolbar": copy.deepcopy(toolbar),
            }
        )

    profile_data["monitor_profiles"] = next_profiles
    profile_data["unmapped_monitor_profiles"] = unmapped
    current_selected = [
        str(item)
        for item in monitoring.get("selected_monitor_ids", [])
        if str(item) in next_profiles
    ]
    merged_selected = []
    for monitor_id in [*current_selected, *selected_ids]:
        if monitor_id and monitor_id not in merged_selected:
            merged_selected.append(monitor_id)
    monitoring["selected_monitor_ids"] = merged_selected
    if next_profiles and str(monitoring.get("mode") or "") == "per_monitor":
        monitoring["mode"] = "per_monitor"


def collect_profile_target_issues(
    profile_id: str,
    profile_name: str,
    profile_data: dict[str, Any],
) -> list[TargetIssue]:
    issues: list[TargetIssue] = []
    collect_toolbar_target_issues(profile_id, profile_name, profile_data.get("shared", {}), issues)
    monitor_profiles = profile_data.get("monitor_profiles", {})
    if isinstance(monitor_profiles, dict):
        for toolbar in monitor_profiles.values():
            if isinstance(toolbar, dict):
                collect_toolbar_target_issues(profile_id, profile_name, toolbar, issues)
    unmapped = profile_data.get("unmapped_monitor_profiles", [])
    if isinstance(unmapped, list):
        for item in unmapped:
            if isinstance(item, dict) and isinstance(item.get("toolbar"), dict):
                collect_toolbar_target_issues(profile_id, profile_name, item["toolbar"], issues)
    return issues


def collect_toolbar_target_issues(
    profile_id: str,
    profile_name: str,
    toolbar_config: Any,
    issues: list[TargetIssue],
) -> None:
    if not isinstance(toolbar_config, dict):
        return
    logo = toolbar_config.get("logo", {})
    if isinstance(logo, dict):
        launcher = logo.get("left_click_launcher")
        if isinstance(launcher, dict):
            collect_launcher_issue(profile_id, profile_name, launcher, "target", issues)
        for item in logo.get("menu_items", []):
            if isinstance(item, dict):
                collect_item_target_issues(profile_id, profile_name, item, issues)
    for menu in toolbar_config.get("menus", []):
        if isinstance(menu, dict):
            collect_item_target_issues(profile_id, profile_name, menu, issues)


def collect_item_target_issues(
    profile_id: str,
    profile_name: str,
    item: dict[str, Any],
    issues: list[TargetIssue],
) -> None:
    item_type = str(item.get("type") or "")
    if item_type in {"launcher", "top_launcher"}:
        collect_launcher_issue(profile_id, profile_name, item, "target", issues)
    elif item_type == "folder_menu":
        collect_launcher_issue(profile_id, profile_name, item, "folder_path", issues)
    for child in item.get("items", []):
        if isinstance(child, dict):
            collect_item_target_issues(profile_id, profile_name, child, issues)


def collect_launcher_issue(
    profile_id: str,
    profile_name: str,
    item: dict[str, Any],
    field_name: str,
    issues: list[TargetIssue],
) -> None:
    target = str(item.get(field_name) or "")
    if not target:
        return
    target_type = str(item.get("target_type") or ("Folder" if field_name == "folder_path" else "Auto Detect"))
    status = classify_launcher_target(target, target_type)
    if status in {"Missing local path", "Network or UNC path unavailable"}:
        issues.append(
            TargetIssue(
                profile_id=profile_id,
                profile_name=profile_name,
                launcher_name=str(item.get("name") or "Launcher"),
                target_type=target_type,
                target=target,
                field=field_name,
                status=status,
            )
        )


def classify_launcher_target(target: str, target_type: str) -> str:
    normalized = target.strip()
    if not normalized:
        return "Unknown or unsupported"
    if normalized.lower().startswith(("http://", "https://")) or target_type == "Website":
        return "Website URL"
    expanded = os.path.expandvars(os.path.expanduser(normalized))
    path = Path(expanded)
    if expanded.startswith("\\\\"):
        return "Existing local path" if path.exists() else "Network or UNC path unavailable"
    if path.exists():
        return "Existing local path"
    if target_type in {"Program", "File", "Folder", "Command Script", "PowerShell Script", "Python Script", "Auto Detect"}:
        return "Missing local path"
    return "Unknown or unsupported"


def write_profile_folder_to_zip(package: zipfile.ZipFile, profile_id: str, folder: Path) -> None:
    root = folder.resolve()
    profile_path = folder / "profile.json"
    package.write(profile_path, f"profiles/{profile_id}/profile.json")
    for path in folder.rglob("*"):
        if path.is_symlink() or not path.is_file() or path.name == "profile.json":
            continue
        relative = path.relative_to(folder).as_posix()
        if not is_allowed_profile_asset_path(relative):
            continue
        package.write(path, f"profiles/{profile_id}/{relative}")


def validate_and_extract_zip(zip_path: Path, destination: Path) -> list[str]:
    if zip_path.suffix.lower() != ".zip":
        return ["Choose a .zip profile package."]
    try:
        with zipfile.ZipFile(zip_path, "r") as package:
            infos = package.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                return ["The ZIP contains too many entries."]
            total_size = sum(info.file_size for info in infos)
            if total_size > MAX_UNCOMPRESSED_BYTES:
                return ["The ZIP is too large to import safely."]
            for info in infos:
                error = validate_zip_entry(info)
                if error:
                    return [error]
            package.extractall(destination)
    except zipfile.BadZipFile:
        return ["The selected file is not a valid ZIP package."]
    except OSError as exc:
        return [str(exc) or "The ZIP package could not be opened."]
    return []


def validate_zip_entry(info: zipfile.ZipInfo) -> str:
    name = info.filename.replace("\\", "/")
    if not name or name.startswith("/"):
        return f"Unsafe ZIP path: {info.filename}"
    if re.match(r"^[A-Za-z]:", name):
        return f"Unsafe ZIP path: {info.filename}"
    parts = PurePosixPath(name).parts
    if ".." in parts:
        return f"Unsafe ZIP path: {info.filename}"
    if info.external_attr >> 16 & 0o170000 == 0o120000:
        return f"ZIP symlinks are not supported: {info.filename}"
    if info.is_dir():
        return "" if is_allowed_directory_path(name) else f"Unexpected ZIP folder: {info.filename}"
    if name == "manifest.json":
        return ""
    if not name.startswith("profiles/"):
        return f"Unexpected ZIP entry: {info.filename}"
    relative = name[len("profiles/"):]
    profile_parts = PurePosixPath(relative).parts
    if len(profile_parts) < 2:
        return f"Unexpected ZIP entry: {info.filename}"
    inside_profile = "/".join(profile_parts[1:])
    if inside_profile == "profile.json":
        return ""
    if is_allowed_profile_asset_path(inside_profile):
        return ""
    return f"Unsupported ZIP entry: {info.filename}"


def is_allowed_directory_path(name: str) -> bool:
    if name in {"profiles/", "profiles"}:
        return True
    if not name.startswith("profiles/"):
        return False
    parts = PurePosixPath(name.rstrip("/")).parts
    if len(parts) in {2, 3, 4} and parts[:1] == ("profiles",):
        return True
    if len(parts) == 5 and parts[2] == "monitor_profiles":
        return True
    return False


def is_allowed_profile_asset_path(relative: str) -> bool:
    path = PurePosixPath(relative.replace("\\", "/"))
    parts = path.parts
    if len(parts) == 3 and parts[0] == "shared" and parts[1] == "icons":
        return path.suffix.lower() in SUPPORTED_ASSET_SUFFIXES
    if len(parts) == 4 and parts[0] == "monitor_profiles" and parts[2] == "icons":
        return path.suffix.lower() in SUPPORTED_ASSET_SUFFIXES
    return False


def load_manifest(root: Path) -> tuple[dict[str, Any], list[str]]:
    path = root / "manifest.json"
    if not path.exists():
        return {}, ["The ZIP does not contain manifest.json."]
    try:
        with path.open("r", encoding="utf-8") as file:
            manifest = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}, ["manifest.json could not be read."]
    if not isinstance(manifest, dict):
        return {}, ["manifest.json is not valid."]
    package_format = str(manifest.get("package_format") or "")
    if package_format != PACKAGE_FORMAT and package_format not in LEGACY_PACKAGE_FORMATS:
        return {}, ["This is not a ToolBar2 profile package."]
    if manifest.get("format_version") != FORMAT_VERSION:
        return {}, ["This profile package version is not supported."]
    if manifest.get("package_type") not in {"single_profile", "profile_bundle"}:
        return {}, ["The profile package type is not supported."]
    profiles = manifest.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        return {}, ["The profile package does not list any profiles."]
    for profile in profiles:
        if not isinstance(profile, dict):
            return {}, ["The profile package manifest contains an invalid profile entry."]
        profile_path = str(profile.get("path") or "")
        if not profile_path.startswith("profiles/") or not profile_path.endswith("/profile.json"):
            return {}, [f"Invalid profile path in manifest: {profile_path}"]
        if not (root / profile_path).exists():
            return {}, [f"Missing profile JSON: {profile_path}"]
    return manifest, []


def load_profile_json_from_path(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid profile file: {path}")
    return data


def unique_new_profile_id(existing_ids: set[str]) -> str:
    profile_id = new_profile_id()
    while profile_id in existing_ids:
        profile_id = new_profile_id()
    return profile_id


def unique_imported_name(name: str, existing_names: set[str]) -> str:
    base = f"{name.strip() or 'Imported Profile'} Imported"
    candidate = base
    index = 2
    while candidate.casefold() in existing_names:
        candidate = f"{base} {index}"
        index += 1
    return candidate


def rewrite_asset_paths_for_staging(profile_data: dict[str, Any], staging_session_id: str, new_profile_id: str) -> None:
    prefix = f"user_profiles/.staging/{safe_profile_id(staging_session_id)}/{new_profile_id}/"
    rewrite_toolbar_asset_paths(profile_data.get("shared", {}), prefix)
    monitor_profiles = profile_data.get("monitor_profiles", {})
    if isinstance(monitor_profiles, dict):
        for monitor_profile in monitor_profiles.values():
            if isinstance(monitor_profile, dict):
                rewrite_toolbar_asset_paths(monitor_profile, prefix)


def rewrite_toolbar_asset_paths(toolbar_config: Any, prefix: str) -> None:
    if not isinstance(toolbar_config, dict):
        return
    logo = toolbar_config.get("logo", {})
    if isinstance(logo, dict):
        rewrite_asset_field(logo, "image", prefix)
        launcher = logo.get("left_click_launcher")
        if isinstance(launcher, dict):
            rewrite_item_asset_paths(launcher, prefix)
        for item in logo.get("menu_items", []):
            if isinstance(item, dict):
                rewrite_item_asset_paths(item, prefix)
    for menu in toolbar_config.get("menus", []):
        if isinstance(menu, dict):
            rewrite_item_asset_paths(menu, prefix)


def rewrite_item_asset_paths(item: dict[str, Any], prefix: str) -> None:
    rewrite_asset_field(item, "icon", prefix)
    rewrite_asset_field(item, "icon_path", prefix)
    for child in item.get("items", []):
        if isinstance(child, dict):
            rewrite_item_asset_paths(child, prefix)


def rewrite_asset_field(item: dict[str, Any], field: str, prefix: str) -> None:
    value = str(item.get(field) or "")
    if not value or value.startswith("user_profiles/") or Path(value).is_absolute():
        return
    normalized = value.replace("\\", "/")
    if normalized.startswith(("shared/icons/", "monitor_profiles/")):
        item[field] = prefix + normalized


def validate_profile_asset_references(
    profile_data: dict[str, Any],
    allow_committed_prefix: bool = False,
) -> None:
    profile_id = safe_profile_id(str(profile_data.get("profile_id") or ""))
    validate_toolbar_asset_references(profile_data.get("shared", {}), profile_id, allow_committed_prefix)
    monitor_profiles = profile_data.get("monitor_profiles", {})
    if isinstance(monitor_profiles, dict):
        for monitor_profile in monitor_profiles.values():
            if isinstance(monitor_profile, dict):
                validate_toolbar_asset_references(monitor_profile, profile_id, allow_committed_prefix)


def validate_toolbar_asset_references(
    toolbar_config: Any,
    profile_id: str,
    allow_committed_prefix: bool,
) -> None:
    if not isinstance(toolbar_config, dict):
        return
    logo = toolbar_config.get("logo", {})
    if isinstance(logo, dict):
        validate_asset_field(logo, "image", profile_id, allow_committed_prefix)
        launcher = logo.get("left_click_launcher")
        if isinstance(launcher, dict):
            validate_item_asset_references(launcher, profile_id, allow_committed_prefix)
        for item in logo.get("menu_items", []):
            if isinstance(item, dict):
                validate_item_asset_references(item, profile_id, allow_committed_prefix)
    for menu in toolbar_config.get("menus", []):
        if isinstance(menu, dict):
            validate_item_asset_references(menu, profile_id, allow_committed_prefix)


def validate_item_asset_references(
    item: dict[str, Any],
    profile_id: str,
    allow_committed_prefix: bool,
) -> None:
    validate_asset_field(item, "icon", profile_id, allow_committed_prefix)
    validate_asset_field(item, "icon_path", profile_id, allow_committed_prefix)
    for child in item.get("items", []):
        if isinstance(child, dict):
            validate_item_asset_references(child, profile_id, allow_committed_prefix)


def validate_asset_field(
    item: dict[str, Any],
    field: str,
    profile_id: str,
    allow_committed_prefix: bool,
) -> None:
    value = str(item.get(field) or "")
    if not value:
        return
    normalized = value.replace("\\", "/")
    if normalized == "img/ToolBar2.png":
        return
    if allow_committed_prefix and profile_id and normalized.startswith(f"user_profiles/{profile_id}/"):
        relative = normalized[len(f"user_profiles/{profile_id}/"):]
    else:
        relative = normalized
    if Path(relative).is_absolute() or re.match(r"^[A-Za-z]:", relative) or ".." in PurePosixPath(relative).parts:
        raise ValueError(f"Unsafe asset path in profile: {value}")
    if relative.startswith("shared/icons/") or relative.startswith("monitor_profiles/"):
        if not is_allowed_profile_asset_path(relative):
            raise ValueError(f"Unsupported asset path in profile: {value}")
        return
    raise ValueError(f"Profile asset path is outside the profile folder: {value}")


def cleanup_paths(paths: list[Path]) -> None:
    for path in paths:
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass
