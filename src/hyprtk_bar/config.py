"""Configuration loading for hyprtk-bar.

Config lives at ~/.config/hyprtk-bar/config.json (JSON).
On first run a default config is written so the user can edit it.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "hyprtk-bar"
CONFIG_PATH = CONFIG_DIR / "config.json"
PYWAL_PATH = Path.home() / ".cache" / "wal" / "colors.json"
ROFI_SYNC_SH = Path.home() / ".config" / "rofi" / "scripts" / "sync-rofi-theme.sh"

log = logging.getLogger("hyprtk_bar.config")

# Module ids and their positions. The bar builds its widgets from ``layout``;
# drag & drop reorders the same set of module ids between the left/center/right
# sections, and the bar menu can show/hide individual modules.
MODULE_IDS = [
    "start_button",
    "quicklinks",
    "workspaces",
    "tasklist",
    "window",
    "sysmon",
    "kbstate",
    "clock",
    "notifications",
    "tray",
    "quicksettings",
]

MODULE_LABELS = {
    "start_button": "Start button",
    "quicklinks": "Quick links",
    "workspaces": "Workspaces",
    "tasklist": "Task list",
    "window": "Active window",
    "sysmon": "System monitor",
    "kbstate": "Keyboard state",
    "clock": "Clock",
    "notifications": "Notification center",
    "tray": "System tray",
    "quicksettings": "Quick settings",
}

DEFAULT_LAYOUT = {
    "left": ["start_button", "quicklinks", "workspaces", "tasklist"],
    "center": ["window"],
    "right": ["sysmon", "kbstate", "clock", "notifications", "tray", "quicksettings"],
}

DEFAULT_PINNED = [
    {"class": "firefox", "command": "firefox", "icon": "firefox"},
    {"class": "kitty", "command": "kitty", "icon": "kitty"},
    {"class": "thunar", "command": "thunar", "icon": "system-file-manager"},
]

DEFAULT_LINKS = [
    {
        "id": "apps",
        "label": "Apps menu",
        "icon": "\uf00a",  # nf-fa-bars
        "command": "~/hyprtk/installer/scripts/appsmenu.sh",
    },
    {
        "id": "terminal",
        "label": "Terminal",
        "icon": "\uf120",  # nf-fa-terminal
        "command": "alacritty",
    },
    {
        "id": "files",
        "label": "File manager",
        "icon": "\uf07c",  # nf-fa-folder_open_o
        "command": "thunar",
    },
    {
        "id": "web",
        "label": "Web browser",
        "icon": "\uf0ac",  # nf-fa-globe
        "command": "",
    },
    {
        "id": "wallpaper",
        "label": "Wallpaper",
        "icon": "\uf03e",  # nf-fa-picture_o
        "command": "~/.local/bin/theme-gui",
        "command_right": "~/hyprtk/installer/scripts/updatewal-awww.sh",
    },
    {
        "id": "cliphist",
        "label": "Clipboard history",
        "icon": "\uf0ea",  # nf-fa-clipboard
        "command": "sleep 0.1 && ~/hyprtk/installer/scripts/cliphist.sh",
        "command_right": "sleep 0.1 && ~/hyprtk/installer/scripts/cliphist.sh d",
        "command_middle": "sleep 0.1 && ~/hyprtk/installer/scripts/cliphist.sh w",
    },
    {
        "id": "screenshot",
        "label": "Screenshot",
        "icon": "\uf083",  # nf-fa-camera
        "command": "~/hyprtk/installer/scripts/ssdetect.sh",
    },
]

DEFAULTS = {
    "position": "bottom",            # bottom | top
    "height": 42,                    # taskbar pill height in px
    "gap_in": 6,                     # transparent gap between the pill and app windows
    "gap_out": 6,                    # transparent gap between the pill and the screen edge
    "radius": 12,                    # pill corner radius
    "opacity": 0.95,                 # pill background alpha
    "width": "100%",                 # pill width: px int or "NN%" of the monitor
    "align": "center",               # pill placement when width < 100%: left|center|right
    "use_pywal": True,               # legacy: seed theme.source from this on first run
    "monitors": "primary",           # primary | all | [connector, ...] (e.g. ["DP-1", "HDMI-A-1"])
    "theme": {
        "source": "pywal",           # pywal | waybar | manual
        "waybar_theme": "",          # name of an imported theme (source=waybar)
        "background": "#1a1b26",
        "foreground": "#c0caf5",
        "accent": "#7aa2f7",
        "hover": "rgba(255, 255, 255, 0.08)",
        "running": "#7aa2f7",
    },
    "font": {
        "family": "",                # "" = system default font
        "size": 16,                  # base text size (px); module icons scale from it
        "icon_size": 0,              # 0 = auto (scales with the font size), else px
    },
    "layout": DEFAULT_LAYOUT,
    "quicklinks": {
        "enabled": True,
        "glyph_font": "Symbols Nerd Font",
        "glyph_color": "accent",
        "icon_size": 0,
        "links": DEFAULT_LINKS,
    },
    "center": {
        "start_button": True,
        "start_icon": "view-grid-symbolic",
        "start_glyph": "\uf015",
        "start_command": "hyprtk-menu",
        "pinned": DEFAULT_PINNED,
    },
    "workspaces": {
        "enabled": True,
        "show_empty": True,          # render all workspace chips up to max
        "max": 5,                    # number of workspace chips to show
    },
    "clock": {
        "enabled": True,
        "format": "%H:%M",
        "date_format": "%a %d %b",
        "calendar": True,
    },
    "sysmon": {
        "enabled": True,
        "interval": 2,          # seconds between reads
        "disk_path": "/",       # mount point to monitor
    },
    "window": {
        "enabled": True,
        "max_length": 40,       # active-window title max chars
        "width": 220,           # fixed module width (px) so neighbors never shift
    },
    "tray": {
        "enabled": True,
        "icon_size": 20,
        "reset_nm_applet": True,   # kill + relaunch nm-applet on startup so it
                                   # re-registers with this bar's watcher
    },
    "quicksettings": {
        "enabled": True,
    },
    "notifications": {
        "enabled": True,
        "max_stored": 50,           # notifications kept in the center at once
        "default_timeout": 5000,    # ms a toast stays before auto-dismiss (0 = persist)
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Return a copy of ``base`` with ``override`` applied recursively."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def validate(cfg: dict) -> dict:
    """Coerce/correct known config fields, falling back to defaults."""
    cfg = dict(cfg)
    # Legacy ``margin`` (symmetric inset) migrates to gap_in/gap_out.
    if "margin" in cfg and "gap_in" not in cfg and "gap_out" not in cfg:
        try:
            margin = max(0, int(cfg["margin"]))
        except (TypeError, ValueError):
            margin = DEFAULTS["gap_in"]
        cfg["gap_in"] = margin
        cfg["gap_out"] = margin
    valid = _deep_merge(DEFAULTS, cfg)

    if valid.get("position") not in ("bottom", "top"):
        log.warning("Unknown position %r, using bottom", valid.get("position"))
        valid["position"] = "bottom"

    for key in ("height", "gap_in", "gap_out", "radius"):
        try:
            valid[key] = max(0, int(valid.get(key, DEFAULTS[key])))
        except (TypeError, ValueError):
            valid[key] = DEFAULTS[key]

    try:
        valid["opacity"] = max(0.0, min(1.0, float(valid.get("opacity", 0.95))))
    except (TypeError, ValueError):
        valid["opacity"] = 0.95

    valid["width"] = _normalize_width(valid.get("width", "100%"))

    if valid.get("align") not in ("left", "center", "right"):
        log.warning("Unknown align %r, using center", valid.get("align"))
        valid["align"] = "center"

    valid["use_pywal"] = bool(valid.get("use_pywal", True))

    # ── monitors ─────────────────────────────────────────────────
    monitors = valid.get("monitors", "primary")
    if isinstance(monitors, list):
        valid["monitors"] = [str(m) for m in monitors if str(m).strip()]
    elif monitors not in ("primary", "all"):
        log.warning("Unknown monitors %r, using primary", monitors)
        valid["monitors"] = "primary"
    else:
        valid["monitors"] = monitors

    # ── notifications ────────────────────────────────────────────
    notif = valid.get("notifications")
    if not isinstance(notif, dict):
        valid["notifications"] = dict(DEFAULTS["notifications"])
    else:
        try:
            valid["notifications"]["max_stored"] = max(
                1, int(notif.get("max_stored", 50))
            )
        except (TypeError, ValueError):
            valid["notifications"]["max_stored"] = 50
        try:
            valid["notifications"]["default_timeout"] = max(
                0, int(notif.get("default_timeout", 5000))
            )
        except (TypeError, ValueError):
            valid["notifications"]["default_timeout"] = 5000
        valid["notifications"]["enabled"] = bool(notif.get("enabled", True))

    # ── font ─────────────────────────────────────────────────────
    font = valid.get("font")
    if not isinstance(font, dict):
        valid["font"] = dict(DEFAULTS["font"])
    else:
        valid["font"]["family"] = str(font.get("family", "") or "")
        try:
            valid["font"]["size"] = max(8, int(font.get("size", 16)))
        except (TypeError, ValueError):
            valid["font"]["size"] = 16
        try:
            valid["font"]["icon_size"] = max(0, int(font.get("icon_size", 0)))
        except (TypeError, ValueError):
            valid["font"]["icon_size"] = 0

    # ── theme source ─────────────────────────────────────────────
    theme = valid.get("theme") or {}
    source = theme.get("source")
    if source not in ("pywal", "waybar", "manual"):
        # migrate the legacy use_pywal flag into an explicit source
        source = "pywal" if valid.get("use_pywal", True) else "manual"
    theme["source"] = source
    theme["waybar_theme"] = str(theme.get("waybar_theme", "") or "")
    valid["theme"] = theme

    # ── layout ───────────────────────────────────────────────────
    valid["layout"] = _normalize_layout(cfg, valid)

    center = valid.get("center") or {}
    raw_center = cfg.get("center")
    if isinstance(raw_center, dict) and "pinned" in raw_center:
        # Explicit pinned list (even empty) is honored as-is.
        center["pinned"] = (
            [p for p in raw_center["pinned"] if isinstance(p, dict)]
            if isinstance(raw_center["pinned"], list)
            else []
        )
    else:
        # Null / missing / empty center block means no pinned apps. The default
        # pinned set only ships with a fresh config (DEFAULTS written on first
        # run); an edited config is taken as the user's explicit choice.
        center["pinned"] = []
    valid["center"] = center

    for section in ("workspaces", "clock"):
        sub = valid.get(section)
        if not isinstance(sub, dict):
            valid[section] = dict(DEFAULTS[section])

    return valid


def _normalize_width(value) -> str:
    """Return a canonical width: an int px string or a clamped "NN%" string."""
    if isinstance(value, (int, float)):
        return str(max(0, int(value)))
    value = str(value).strip()
    if value.endswith("%"):
        try:
            pct = max(0.0, min(100.0, float(value[:-1].strip())))
        except ValueError:
            log.warning("Bad width %r, using 100%%", value)
            return "100%"
        return f"{int(round(pct))}%"
    try:
        return str(max(0, int(value)))
    except ValueError:
        log.warning("Bad width %r, using 100%%", value)
        return "100%"


def _normalize_layout(raw: dict, valid: dict) -> dict:
    """Return a sanitized layout dict.

    If the user config carries an explicit ``layout``, sanitize it (known ids,
    no duplicates) and leave modules the user omitted out — the bar menu can
    add them back. Otherwise migrate the legacy ``*.enabled`` flags into a
    layout so existing configs keep their visible modules.
    """
    user_layout = raw.get("layout")
    if isinstance(user_layout, dict):
        seen: list[str] = []
        layout: dict[str, list[str]] = {}
        for section in ("left", "center", "right"):
            cleaned: list[str] = []
            for mid in user_layout.get(section) or []:
                if mid in MODULE_IDS and mid not in seen:
                    cleaned.append(mid)
                    seen.append(mid)
            layout[section] = cleaned
        return layout

    layout = {"left": [], "center": [], "right": []}
    center = valid.get("center") or {}
    workspaces = valid.get("workspaces") or {}
    clock = valid.get("clock") or {}
    sysmon = valid.get("sysmon") or {}
    tray = valid.get("tray") or {}
    qs = valid.get("quicksettings") or {}
    notif = valid.get("notifications") or {}
    win = valid.get("window") or {}

    if center.get("start_button", True):
        layout["center"].append("start_button")
    ql = valid.get("quicklinks") or {}
    if ql.get("enabled", True):
        layout["left"].append("quicklinks")
    if workspaces.get("enabled", True):
        layout["center"].append("workspaces")
    layout["center"].append("tasklist")
    if win.get("enabled", True):
        layout["center"].append("window")
    if sysmon.get("enabled", True):
        layout["right"].append("sysmon")
    if clock.get("enabled", True):
        layout["right"].append("clock")
    if notif.get("enabled", True):
        layout["right"].append("notifications")
    if tray.get("enabled", True):
        layout["right"].append("tray")
    if qs.get("enabled", True):
        layout["right"].append("quicksettings")
    return layout


def load() -> dict:
    """Load config from disk, writing defaults on first run."""
    if not CONFIG_PATH.is_file():
        save(DEFAULTS)
        return dict(DEFAULTS)

    try:
        raw = json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read config (%s); using defaults", exc)
        return dict(DEFAULTS)

    return validate(raw)


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


def load_pywal_colors() -> dict | None:
    """Read ~/.cache/wal/colors.json; returns color map or None if unavailable."""
    try:
        data = json.loads(PYWAL_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    out = dict(data.get("colors") or {})
    special = data.get("special") or {}
    out["background"] = special.get("background")
    out["foreground"] = special.get("foreground")
    return out or None


def icon_size_for(font_size, icon_size=0) -> int:
    """Derive a module-icon pixel size.

    ``icon_size`` > 0 is used verbatim (manual override); otherwise the icon
    scales with the bar's base font size.
    """
    try:
        icon_size = int(icon_size)
    except (TypeError, ValueError):
        icon_size = 0
    if icon_size > 0:
        return max(14, icon_size)
    try:
        return max(14, int(round(int(font_size) * 1.25)))
    except (TypeError, ValueError):
        return 20