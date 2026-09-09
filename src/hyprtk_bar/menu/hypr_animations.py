"""Hyprland border-animation mirror for hyprtk-menu.

Hyprland animates window borders (``borderangle`` / ``border``) at a speed
chosen by which animations file is enabled (``animations-high`` vs
``animations-low``), plus the hyprtk-bar config's ``animations.mode``
(``low`` / ``high`` / ``custom``). This mirrors that decision so the menu's
panel border animates at the same pace as the bar's.

The active animations file is found by reading ``hyprland.lua`` for a
non-commented ``require("animations-...")``; the file's ``borderangle`` speed
(falling back to ``border``) supplies the pace. Pure stdlib — no GTK.
"""

# ─────────────────────────────────────────────────────────────────
#   HYPRTK · hyprtk-bar · hypr_animations
#   Part of the Hyprtk desktop suite · github.com/hyprtk
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import re

HYPR_DIRS = (
    os.path.expanduser("~/.config/hypr"),
    os.path.expanduser("~/hyprtk/hypr"),
)
BAR_CONFIG = os.path.expanduser("~/.config/hyprtk-bar/config.json")

_ANIM_BLOCK = re.compile(r"hl\.animation\(\{(.*?)\}\)", re.DOTALL)
_REQ = re.compile(r'require\(\s*["\']animations-([\w-]+)["\']\s*\)')


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _find_hypr_dir() -> str | None:
    for d in HYPR_DIRS:
        if os.path.isfile(os.path.join(d, "hyprland.lua")):
            return d
    return None


def _parse_animations(path: str) -> dict:
    """Parse ``hl.animation`` blocks into {leaf: {enabled, speed}}."""
    out: dict = {}
    for block in _ANIM_BLOCK.finditer(_read(path)):
        body = block.group(1)
        leaf_m = re.search(r'leaf\s*=\s*["\']([\w]+)["\']', body)
        if not leaf_m:
            continue
        leaf = leaf_m.group(1)
        speed = re.search(r"speed\s*=\s*(\d+)", body)
        enabled = re.search(r"enabled\s*=\s*(true|false)", body)
        out[leaf] = {
            "enabled": (enabled.group(1) if enabled else "true") == "true",
            "speed": int(speed.group(1)) if speed else None,
        }
    return out


def _file_border_speed(name: str) -> int | None:
    """``borderangle`` (fallback ``border``) speed from animations-<name>.lua."""
    d = _find_hypr_dir()
    if d is None:
        return None
    anims = _parse_animations(os.path.join(d, f"animations-{name}.lua"))
    for leaf in ("borderangle", "border"):
        info = anims.get(leaf)
        if info and info.get("enabled") and info.get("speed"):
            return int(info["speed"])
    return None


def border_period_ms() -> int | None:
    """Menu border-animation period in ms, or None when border animation is off.

    Mirrors hyprtk-bar: ``animations.mode`` low/high read the matching
    animations file's speed (speed * 100 ms per loop, matching Hyprland);
    ``custom`` uses ``animations.speed`` directly. None when animations are
    disabled or the bar config has border_animation off.
    """
    try:
        import json

        with open(BAR_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return None
    if not (cfg.get("theme") or {}).get("border_animation", True):
        return None
    mode = str((cfg.get("animations") or {}).get("mode") or "high").lower()
    if mode == "custom":
        try:
            speed = max(1, int((cfg.get("animations") or {}).get("speed")))
        except (TypeError, ValueError):
            return None
        return max(200, int(speed * 100))
    if mode in ("low", "high"):
        speed = _file_border_speed(mode)
        if speed:
            return max(200, int(speed * 100))
    return None

# ── active border colours (mirrors Hyprland's window.lua) ───────

def active_border_colors():
    """The two ``active_border`` colours Hyprland uses, as ``#rrggbb``.

    ``window.lua`` reads ``~/.cache/wal/colors-hyprland.lua`` and sets
    ``active_border = { color11, color4 }``. The borderangle loop rotates the
    gradient between exactly these two colours — return them (hex, ``#``
    prefixed) or None when the palette is unavailable.
    """
    import json

    try:
        with open(os.path.expanduser("~/.cache/wal/colors.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    colors = data.get("colors") or {}
    c1 = colors.get("color11")
    c2 = colors.get("color4")
    if not c1 or not c2:
        return None

    def _norm(c):
        c = c.strip()
        return c if c.startswith("#") else "#" + c

    return _norm(c1), _norm(c2)


def lerp_color(c1, c2, t):
    """Linear interpolation between two ``#rrggbb`` colours (t in 0..1)."""
    def _rgb(c):
        h = c.lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    try:
        r1, g1, b1 = _rgb(c1)
        r2, g2, b2 = _rgb(c2)
    except ValueError:
        return c1
    t = max(0.0, min(1.0, t))
    return "#{:02x}{:02x}{:02x}".format(
        int(round(r1 + (r2 - r1) * t)),
        int(round(g1 + (g2 - g1) * t)),
        int(round(b1 + (b2 - b1) * t)),
    )
