# ToolBar2

ToolBar2 is a Windows desktop toolbar built with Python and PyQt6. It provides configurable top-edge toolbars, saved user profiles, menu and launcher editing, profile import/export, and shared or per-monitor toolbar layouts.

## Main Features

- One or more auto-hiding toolbar windows across connected monitors.
- Shared toolbar modes and unique per-monitor toolbar mode.
- Saved User Profiles with quick switching from toolbar blank-space menus and the system tray.
- Editable logo, appearance, behavior, top-level menus, top-level launchers, nested submenus, folder menus, headings, separators, and launchers.
- Launcher support for programs, scripts, files, folders, websites, and auto-detected targets.
- Optional launcher icons and top-level launcher button styling.
- Optional built-in Web Search bar with movable top-level placement and provider selection.
- Drag and drop shortcuts onto blank toolbar space.
- Folder launchers can accept dropped files and folders, then move or copy them into the target folder.
- Executable and script launchers can receive dropped paths as command-line arguments.
- Profile ZIP import/export with profile-owned images included.
- Fully offline interactive Help that opens in the default browser from both the toolbar and Settings.
- Monitor identification overlays from the Behavior tab.
- Config backup and damaged-config preservation.

## Requirements

- Windows 10 or Windows 11.
- Python 3.11 or newer is recommended for running from source or building the EXE. This workspace was verified with Python 3.13.7.
- Packages listed in `requirements.txt`:
  - `PyQt6`
  - `pyinstaller`

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run from source:

```powershell
python toolbar.py
```

## Release Folder Layout

The application stores writable user data beside `ToolBar2.exe` in release builds, or beside the Python files when running from source.

```text
ToolBar2/
  ToolBar2.exe
  help/
    index.html
    help.css
    help.js
    images/
  toolbar_config.json
  toolbar_config.backup.json
  user_profiles/
    profile_xxxxxxxx/
      profile.json
      shared/
        icons/
          LOGO.png
          launcher-id.png
      monitor_profiles/
        monitor-profile-id/
          icons/
            LOGO.png
            launcher-id.png
```

Embedded UI assets are bundled into the EXE from `img/gear.svg`, `img/ToolBar2.png`, and `img/ToolBar2.ico`. User-managed profile logos and launcher icons are stored under `user_profiles`.

`toolbar_config.json` keeps application-global settings, including the active User Profile selection. Complete toolbar profile data is stored in `user_profiles/<profile_id>/profile.json`.

## User Profiles

Open Settings and use the `Profiles` tab to create, rename, duplicate, delete, load, import, and export saved User Profiles.

Each User Profile contains its toolbar menus, launchers, logo settings, appearance, behavior, monitor mode, selected monitors, per-monitor toolbar profiles, and profile-owned image assets. Application-global settings, such as startup behavior and the active profile ID, remain in `toolbar_config.json`.

Quick profile switching is available from:

- Blank toolbar space right-click menu: `Profiles >`
- System tray menu: `Profiles >`

The profile submenu is rebuilt when it opens, so newly created, renamed, deleted, or imported profiles appear without restarting. The active profile is checked. Switching profiles immediately refreshes toolbar windows, menus, logo, appearance, behavior, monitor mode, and tray menus.

If Settings is open with unsaved changes, quick switching asks before discarding the current Settings session. It does not automatically save unsaved edits.

## Toolbar Modes

Open Settings with the gear button, the toolbar context menu, or the system tray menu.

- `One monitor`: one toolbar on one selected monitor.
- `Selected monitors - same toolbar`: the same shared toolbar on checked monitors.
- `All connected monitors - same toolbar`: the same shared toolbar on every connected monitor.
- `Selected monitors - unique toolbar on each`: a separate toolbar configuration for each checked monitor.

In unique mode, use `Editing toolbar for` to choose which monitor toolbar is being edited. `Copy Toolbar From...` copies another monitor toolbar into the selected monitor toolbar. `Reset This Toolbar` resets only the selected monitor toolbar from the shared toolbar.

Disconnected selected monitors remain saved. Per-monitor toolbar profiles are preserved and return when the monitor reconnects. Imported per-monitor toolbars that are not mapped to a current monitor can be assigned later with `Assign Imported Toolbar...`.

Use `Identify Monitors` on the Behavior tab to show a temporary overlay on every connected monitor. The overlay displays the monitor number, display name, resolution, primary status when applicable, and the stable monitor ID when available.

## Creating Menus and Launchers

Use the Menus tab to edit the toolbar structure.

Supported top-level items include:

- Menus
- Folder menus
- Top-level launchers

Supported nested menu items include:

- Launchers
- Submenus
- Folder menus
- Headings
- Separators

Launcher target types include:

- `Auto Detect`
- `Program`
- `Command Script`
- `PowerShell Script`
- `Python Script`
- `File`
- `Folder`
- `Website`

Toolbar menus and nested items can be duplicated, copied, or moved. The context menu includes `Copy To...` and `Move To...` commands where supported.

Top-level launchers can use custom toolbar button colors and icon-only display. When a top-level launcher is moved into a normal menu, toolbar-button-only styling is stripped because nested launchers do not use top-level toolbar button styling.

When `Show Web Search bar` is enabled, the Menus editor also shows a special top-level `Web Search Bar` row. It can be moved left or right among other top-level items, edited, or hidden without being stored inside `config["menus"]`.

## Appearance and Logo Controls

The Appearance tab controls toolbar colors, opacity, size, spacing, and toolbar controls. Important current settings include:

- `Toolbar height`
- `Auto toolbar width`
- `Toolbar width`
- `Horizontal alignment`
- `Horizontal offset`
- `Button height`
- `Corner radius`
- `Left/right edge padding`
- `Top/bottom edge padding`
- `Menu button spacing`
- `Top menu position`
- `Show Settings gear`
- `Show Exit button`
- `Show Web Search bar`
- `Web Search width`
- `Web Search placeholder`
- `Search engine`
- `Custom search URL`

The toolbar automatically shrinks buttons, logo display, icons, text, and controls when the selected toolbar height is too small. Top/bottom padding is also reduced automatically when needed so content stays vertically centered.

Logo sizing is controlled from `Logo > Appearance`. `Logo height` is authoritative there, alongside `Maximum logo width`, `Preserve aspect ratio`, and `Logo opacity`.

## Dropping Files Onto Launchers

Dropping files or folders onto blank toolbar space opens the normal Add Shortcut workflow.

For executable and script launchers, enabling `Accept dropped files` passes dropped paths as command-line arguments to the launcher.

For Folder launchers, enabling `Accept dropped items` lets the launcher move or copy dropped files and folders into the launcher's target folder. Choose one of:

- `Move to this folder`
- `Copy to this folder`
- `Ask each time`

Folder transfers support multiple local files and folders, mapped network drives, and UNC paths. Existing destination items are not overwritten silently; conflicts offer `Replace`, `Keep Both`, `Skip`, and `Cancel`, with an `Apply to all conflicts` option for multi-item drops.

Slow folder transfers run in a Qt worker thread with a small modal progress dialog showing the current item.

## Profile Import and Export

Profile packages are ZIP files. The suggested filename for one profile is `Profile Name.ToolBar2-profile.zip`; exporting all profiles suggests `ToolBar2-Profiles-YYYY-MM-DD.zip`.

Each package contains:

```text
manifest.json
profiles/
  profile_xxxxxxxx/
    profile.json
    shared/
      icons/
    monitor_profiles/
      monitor-profile-id/
        icons/
```

The manifest uses:

- `package_format`: `ToolBar2_profiles`
- `format_version`: `1`
- `package_type`: `single_profile` or `profile_bundle`

Exports include saved profile configuration and profile-owned images. They do not include `toolbar_config.json`, application-global settings, staging folders, or external launcher target files.

Import is available from the Profiles tab with `Import...`, or by dropping a `.zip` package onto the saved profile list. The import review dialog supports importing as new, replacing an existing profile, skipping profiles, mapping imported monitor toolbars to connected monitors, and reviewing missing launcher targets.

Backward compatibility is preserved for older package branding. ToolBar2 still imports legacy packages that use the old `mci_toolbar_profiles` manifest value or `.mci-profile.zip` filenames, but all newly exported packages use ToolBar2 branding.

Imported profiles and assets remain staged until the main Settings `Save` is clicked. `Cancel` discards the import staging session.

## Web Search Bar

Enable the Web Search bar from `Appearance > Toolbar Controls`. Current public providers are:

- `Google`
- `Bing`
- `DuckDuckGo`
- `Yahoo`
- `Custom`

When `Custom` is selected, the URL must contain `{query}`. Pressing Enter URL-encodes the text and opens the search in the default Windows browser. The field supports the toolbar edit and move actions, plus right-click `Paste`, `Select All`, and `Hide`.

## Offline Help

ToolBar2 includes a fully offline interactive help system in `help/`. Open it from:

- blank toolbar space right-click menu: `Help`
- the Settings action bar: `Help`

The help header uses `img/ToolBar2.png`. In source mode and bundled EXE builds, Help opens `help/index.html` in the default browser through the shared Qt desktop-services helper.

## Backups

Back up these items while the app is closed:

- `toolbar_config.json`
- `toolbar_config.backup.json`
- the entire `user_profiles` folder

If `toolbar_config.json` is damaged, the app attempts to recover from `toolbar_config.backup.json` and preserves the damaged file with a name like `toolbar_config.damaged-YYYYMMDD-HHMMSS.json`.

## Settings Behavior

Settings edits are staged in the open Settings window. Toolbar windows are not permanently changed until Settings is saved.

Use `Save` to commit profile and application changes. Use `Cancel` to discard the current Settings session, including staged imported profile assets.

Quick profile switching from the tray or toolbar context menu does not save open Settings edits. If Settings has unsaved changes, the app asks whether to switch profiles and discard those changes.

## Building the EXE

Build the normal GUI release:

```powershell
.\Make EXE.bat
```

Build with a debug console:

```powershell
.\Make EXE.bat debug
```

The script runs:

```powershell
python -m PyInstaller "ToolBar2.spec"
```

The final EXE is created at:

```text
dist\ToolBar2.exe
```

The build script removes only `build` and `dist`. It does not delete `toolbar_config.json`, `toolbar_config.backup.json`, or `user_profiles`.

## Tests

There is currently one pytest-style automated smoke test at `test_profile_asset_expansion.py`. `pytest` is not listed in `requirements.txt`, so install it separately if you want to run this test:

```powershell
python -m pip install pytest
python -m pytest test_profile_asset_expansion.py
```

The old `python -m unittest discover` command does not run this test because it is not a unittest test case.

Manual multi-monitor validation is documented in [MULTI_MONITOR_TEST_CHECKLIST.md](MULTI_MONITOR_TEST_CHECKLIST.md).

## Important Notes

- Close the app before manually editing or replacing config/profile files.
- Do not edit files inside `user_profiles/.staging`; that folder is temporary Settings/import workspace.
- Keep `toolbar_config.json` and `user_profiles` together when moving the app to another folder.
- Profile exports include profile-owned icons and logos, but not external files or programs referenced by launcher targets.
- Folder launcher drops operate on real filesystem items. Review the destination folder and conflict prompts before choosing replace or move actions.
