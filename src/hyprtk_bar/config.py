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

log = logging.getLogger("hyprtk_bar.config")

DEFAULT_PINNED = [
    {"class": "firefox", "command": "firefox", "icon": "firefox"},
    {"class": "kitty", "command": "kitty", "icon": "kitty"},
    {"class": "thunar", "command": "thunar", "icon": "system-file-manager"},
]

DEFAULTS = {
    "position": "bottom",            # bottom | top
    "height": 42,                    # taskbar pill height in px
    "margin": 6,                     # transparent inset around the pill
    "radius": 12,                    # pill corner radius
    "opacity": 0.95,                 # pill background alpha
    "use_pywal": True,               # theme background/foreground/accent from pywal
    "monitors": "primary",           # primary | all (multi-monitor = later)
    "theme": {
        "background": "#1a1b26",
        "foreground": "#c0caf5",
        "accent": "#7aa2f7",
        "hover": "rgba(255, 255, 255, 0.08)",
        "running": "#7aa2f7",
    },
    "center": {
        "start_button": True,
        "start_icon": "view-grid-symbolic",
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
    "show_desktop": True,
    "tray": {
        "enabled": True,
        "icon_size": 20,
        "reset_nm_applet": True,   # kill + relaunch nm-applet on startup so it
                                   # re-registers with this bar's watcher
    },
    "quicksettings": {
        "enabled": True,
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
    valid = _deep_merge(DEFAULTS, cfg)

    if valid.get("position") not in ("bottom", "top"):
        log.warning("Unknown position %r, using bottom", valid.get("position"))
        valid["position"] = "bottom"

    for key in ("height", "margin", "radius"):
        try:
            valid[key] = max(0, int(valid.get(key, DEFAULTS[key])))
        except (TypeError, ValueError):
            valid[key] = DEFAULTS[key]

    try:
        valid["opacity"] = max(0.0, min(1.0, float(valid.get("opacity", 0.95))))
    except (TypeError, ValueError):
        valid["opacity"] = 0.95

    valid["use_pywal"] = bool(valid.get("use_pywal", True))

    center = valid.get("center") or {}
    if not isinstance(center.get("pinned"), list):
        center["pinned"] = list(DEFAULT_PINNED)
    valid["center"] = center

    for section in ("workspaces", "clock"):
        sub = valid.get(section)
        if not isinstance(sub, dict):
            valid[section] = dict(DEFAULTS[section])

    return valid


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