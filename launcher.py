from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from PyQt6 import QtWidgets

from target_detection import detect_target


WEBSITE_PREFIXES = ("http://", "https://")


def launch_item(item: dict, parent: QtWidgets.QWidget | None = None) -> None:
    try:
        launch_target(
            target=str(item.get("target") or ""),
            target_type=str(item.get("target_type") or "Auto Detect"),
            arguments=str(item.get("arguments") or ""),
            working_directory=str(item.get("working_directory") or ""),
            python_mode=str(item.get("python_mode") or "Automatic"),
        )
    except Exception as exc:
        QtWidgets.QMessageBox.critical(
            parent,
            "Launcher Error",
            f"Could not open '{item.get('name', 'Launcher')}'.\n\n{exc}",
        )

def launch_item_with_args(item: dict, extra_arguments: list[str], parent: QtWidgets.QWidget | None = None) -> None:
    try:
        launch_target(
            target=str(item.get("target") or ""),
            target_type=str(item.get("target_type") or "Auto Detect"),
            arguments=str(item.get("arguments") or ""),
            working_directory=str(item.get("working_directory") or ""),
            python_mode=str(item.get("python_mode") or "Automatic"),
            extra_arguments=extra_arguments,
        )
    except Exception as exc:
        QtWidgets.QMessageBox.critical(
            parent,
            "Launcher Error",
            f"Could not run '{item.get('name', 'Launcher')}' with dropped files.\n\n{exc}",
        )


def launch_target(
    target: str,
    target_type: str = "Auto Detect",
    arguments: str = "",
    working_directory: str = "",
    python_mode: str = "Automatic",
    extra_arguments: list[str] | None = None,
) -> None:
    target = target.strip()
    target_type = target_type.strip()
    working_directory = working_directory.strip()

    if not target:
        raise ValueError("No target was configured.")

    if target_type == "Auto Detect":
        detected = detect_target(target)
        target = detected["target"]
        target_type = detected["target_type"]

    if target.lower().startswith(WEBSITE_PREFIXES) or target_type == "Website":
        webbrowser.open(target)
        return

    expanded_target = os.path.expandvars(os.path.expanduser(target))
    path = Path(expanded_target)
    is_unc = expanded_target.startswith("\\\\")

    if not is_unc and not path.exists():
        raise FileNotFoundError(f"Target does not exist:\n{target}")

    cwd = None
    if working_directory:
        cwd_path = Path(os.path.expandvars(os.path.expanduser(working_directory)))
        if not cwd_path.exists():
            raise FileNotFoundError(f"Working directory does not exist:\n{working_directory}")
        cwd = str(cwd_path)

    suffix = path.suffix.lower()
    all_arguments = [*split_arguments(arguments), *(extra_arguments or [])]

    if path.is_dir() or is_unc or target_type == "Folder":
        os.startfile(expanded_target)
        return

    if suffix in {".py", ".pyw"} or target_type == "Python Script":
        run_python_script(expanded_target, all_arguments, cwd, python_mode, suffix)
        return

    if suffix == ".ps1" or target_type == "PowerShell Script":
        run_powershell_script(expanded_target, all_arguments, cwd)
        return

    if suffix in {".bat", ".cmd"} or target_type == "Command Script":
        run_command_script(expanded_target, all_arguments, cwd)
        return

    if suffix == ".exe" or target_type == "Program":
        run_program(expanded_target, all_arguments, cwd)
        return

    if all_arguments:
        run_program(expanded_target, all_arguments, cwd)
    else:
        os.startfile(expanded_target)


def split_arguments(arguments: str) -> list[str]:
    if not arguments.strip():
        return []
    import shlex

    return shlex.split(arguments, posix=False)


def run_python_script(path: str, arguments: list[str], cwd: str | None, python_mode: str, suffix: str) -> None:
    if python_mode == "Console Python":
        interpreter = shutil.which("python.exe") or sys.executable
    elif python_mode == "Windowed Python" or suffix == ".pyw":
        interpreter = shutil.which("pythonw.exe") or sys.executable
    else:
        interpreter = shutil.which("pythonw.exe") or sys.executable
    subprocess.Popen([interpreter, path, *arguments], cwd=cwd)


def run_powershell_script(path: str, arguments: list[str], cwd: str | None) -> None:
    subprocess.Popen(
        ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", path, *arguments],
        cwd=cwd,
    )

def run_command_script(
    path: str,
    arguments: list[str],
    cwd: str | None,
) -> None:
    comspec = os.environ.get("COMSPEC", "cmd.exe")

    argument_text = subprocess.list2cmdline(
        [str(argument) for argument in arguments]
    )

    inner_command = f'"{path}"'
    if argument_text:
        inner_command += f" {argument_text}"

    command_line = (
        f'"{comspec}" /d /s /c '
        f'"{inner_command}"'
    )

    subprocess.Popen(
        command_line,
        cwd=cwd or str(Path(path).parent),
        shell=False,
    )

def run_program(path: str, arguments: list[str], cwd: str | None) -> None:
    suffix = Path(path).suffix.lower()
    if suffix in {".bat", ".cmd"}:
        run_command_script(path, arguments, cwd)
        return
    subprocess.Popen([path, *arguments], cwd=cwd)
