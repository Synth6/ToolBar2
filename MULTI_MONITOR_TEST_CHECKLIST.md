# ToolBar2 Multi-Monitor Test Checklist

Use this on a Windows desktop with two or more monitors. For each item, mark Pass/Fail and add notes.

| Section | Action | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|
| A. One-monitor mode | Select `One monitor`, choose Monitor 1, save, restart. | Exactly one toolbar appears on Monitor 1. |  |  |
| A. One-monitor mode | Change the selected monitor and save. | The single toolbar moves to the selected monitor. |  |  |
| B. Selected shared | Select two monitors in `Selected monitors - same toolbar`. | One identical shared toolbar appears on each checked connected monitor. |  |  |
| B. Selected shared | Edit a menu on one toolbar. | Every active shared toolbar refreshes with the same menu. |  |  |
| C. All shared | Select `All connected monitors - same toolbar`. | One identical shared toolbar appears on every connected monitor. |  |  |
| C. All shared | Connect another monitor. | A toolbar appears on the new monitor after a short delay. |  |  |
| D. Unique toolbars | Select `Selected monitors - unique toolbar on each`. | One toolbar appears on each checked connected monitor. |  |  |
| D. Unique toolbars | Edit Monitor 2 menu/color/logo. | Monitor 2 changes; Monitor 1 and shared root do not change. |  |  |
| E. Connect/disconnect | Disconnect a selected monitor. | Only that monitor's toolbar is removed; its ID and profile remain saved. |  |  |
| E. Connect/disconnect | Reconnect that monitor. | Its toolbar returns automatically with the correct shared/profile config. |  |  |
| F. Resolution/scale | Change resolution or Windows scaling. | The affected toolbar repositions correctly and popups do not remain stranded. |  |  |
| G. Portrait monitor | Rotate a monitor to portrait. | The toolbar uses the portrait screen width and top edge correctly. |  |  |
| H. Negative coordinates | Place a monitor left/above primary. | Top-edge activation and toolbar geometry work with negative coordinates. |  |  |
| I. Primary changes | Change the primary monitor. | Stable selections are preserved; fallback uses the new primary only when needed. |  |  |
| J. Profile switching | Switch `Editing toolbar for` between monitors with unsaved edits. | Edits are preserved in the draft until Save or discarded on Cancel. |  |  |
| K. Copy Toolbar From | Copy an existing profile to another monitor and save. | Target profile matches source but uses independent profile assets. |  |  |
| L. Reset This Toolbar | Reset one profile to shared root and save. | Only that profile resets; other profiles and shared root remain unchanged. |  |  |
| M. Icons/logos | Replace one profile icon/logo. | Only that profile preview and toolbar update. |  |  |
| M. Icons/logos | Change `Logo height` and `Maximum logo width` on one unique monitor toolbar. | Only that monitor toolbar updates, and the logo stays vertically centered and inside the toolbar. |  |  |
| N. Drag/drop launchers | Drop files/folders on each toolbar. | Shortcuts are added to the correct shared/profile config. |  |  |
| O. accept_dropped_files | Drop files onto enabled launchers. | Launcher receives files unless Ctrl is held for shortcut creation. |  |  |
| P. Folder menus | Open folder menus and refresh them. | Folder contents load without blocking and cleanup works after monitor removal. |  |  |
| P. Web Search bar | Enable `Show Web Search bar` in a shared-toolbar mode. | The Web Search bar appears on every active shared toolbar and opens searches in the default browser. |  |  |
| P. Web Search bar | Enable `Show Web Search bar` in unique-toolbar mode and assign different settings per monitor. | Each monitor toolbar preserves its own Web Search visibility, provider, width, and position after Save and reopen. |  |  |
| P. Web Search bar | Drag `Web Search Bar` before and after other top-level items in the Menus editor. | The tree order and live toolbar order stay synchronized, including when menus move across the Web Search bar. |  |  |
| Q. Tray icon | Use Show, Hide, double-click, Exit. | One tray icon controls all active toolbars. |  |  |
| R. Exit behavior | Use red X, toolbar context Exit, tray Exit. | App exits cleanly once; no duplicate prompts or ghost windows. |  |  |
| S. Config migration | Start with an older config backup copy. | Config migrates to version 3 and preserves menus/icons/profiles. |  |  |
| S. Config migration | Import an older `.mci-profile.zip` package with the legacy `mci_toolbar_profiles` manifest value. | Import succeeds without editing the source ZIP, and imported profiles, logos, and icons remain intact. |  |  |
| T. EXE restart | Build EXE, run, edit settings, restart. | Settings, selected IDs, profiles, icons, logos, and menus persist. |  |  |
| T. EXE restart | Export one profile and all profiles after branding update. | New files use `*.ToolBar2-profile.zip` and `ToolBar2-Profiles-YYYY-MM-DD.zip` naming. |  |  |
| T. EXE restart | Open Help from blank toolbar space and from Settings. | `help/index.html` opens in the default browser in source mode and the bundled EXE, and the header logo shows `img/ToolBar2.png`. |  |  |
| T. EXE restart | Change `Top/bottom edge padding` at multiple toolbar heights. | Controls remain vertically centered, and large padding values are reduced automatically when the toolbar is too short. |  |  |
| T. EXE restart | Make live-preview changes to Web Search, logo sizing, and padding, then press Cancel. | The runtime toolbar returns to the last saved state on every active monitor. |  |  |
