from __future__ import annotations

import configparser
import os
import subprocess
from pathlib import Path


def detect_target(target: str) -> dict[str, str]:
    original = target.strip()
    if not original:
        return {"target": "", "target_type": "Auto Detect", "name": "New Launcher"}

    if original.lower().startswith(("http://", "https://")):
        return {"target": original, "target_type": "Website", "name": website_name(original)}

    expanded = os.path.expandvars(os.path.expanduser(original))
    path = Path(expanded)
    suffix = path.suffix.lower()

    if suffix == ".url" and path.exists():
        url = read_url_shortcut(path)
        if url:
            return {"target": url, "target_type": "Website", "name": display_name(path)}

    if suffix == ".lnk" and path.exists():
        shortcut = resolve_lnk(path)
        resolved = shortcut.get("target", "")
        if resolved:
            detected = detect_target(resolved)
            detected["name"] = display_name(path)
            detected["arguments"] = shortcut.get("arguments", "")
            detected["working_directory"] = shortcut.get("working_directory", "")
            return detected
        return {"target": str(path), "target_type": "File", "name": display_name(path)}

    if expanded.startswith("\\\\") and (not suffix or path.is_dir()):
        return {"target": expanded, "target_type": "Folder", "name": path.name or expanded}
    if path.is_dir():
        return {"target": str(path), "target_type": "Folder", "name": display_name(path)}
    if suffix == ".exe":
        return {"target": str(path), "target_type": "Program", "name": display_name(path)}
    if suffix in {".py", ".pyw"}:
        return {"target": str(path), "target_type": "Python Script", "name": display_name(path)}
    if suffix in {".bat", ".cmd"}:
        return {"target": str(path), "target_type": "Command Script", "name": display_name(path)}
    if suffix == ".ps1":
        return {"target": str(path), "target_type": "PowerShell Script", "name": display_name(path)}
    return {"target": str(path), "target_type": "File", "name": display_name(path)}


def display_name(path: Path) -> str:
    if path.suffix:
        return path.stem
    return path.name or str(path)


def website_name(url: str) -> str:
    text = url.removeprefix("https://").removeprefix("http://").strip("/")
    return text or "Website"


def read_url_shortcut(path: Path) -> str:
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
        return parser.get("InternetShortcut", "URL", fallback="")
    except configparser.Error:
        return ""


def resolve_lnk(path: Path) -> dict[str, str]:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($args[0]);"
        "Write-Output $s.TargetPath;"
        "Write-Output $s.Arguments;"
        "Write-Output $s.WorkingDirectory",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return {"target": "", "arguments": "", "working_directory": ""}
    lines = result.stdout.splitlines()
    return {
        "target": lines[0].strip() if len(lines) > 0 else "",
        "arguments": lines[1].strip() if len(lines) > 1 else "",
        "working_directory": lines[2].strip() if len(lines) > 2 else "",
    }
