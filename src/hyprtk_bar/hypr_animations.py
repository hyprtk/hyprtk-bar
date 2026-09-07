"""Hyprland border animation mirror for the bar.

The bar's border is normally a static accent color. Hyprland itself animates
window borders (``border`` / ``borderangle`` leaves) and the speed/style of
those animations is chosen at runtime by which animations file is enabled in
``hyprland.lua`` (``animations-high`` vs ``animations-low``). This module
mirrors that decision so the bar border animates at the same pace.

The active animations file is detected by reading ``hyprland.lua`` for a
non-commented ``require("animations-...")``; the file's ``border`` and
``borderangle`` ``hl.animation`` blocks supply the speed. Pure stdlib — no
GTK, so it is trivially testable.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("hyprtk_bar.hypr_animations")

HYPR_DIRS = (
    Path.home() / ".config" / "hypr",
    Path.home() / "hyprtk" / "hypr",
)

_ANIM_BLOCK = re.compile(r"hl\.animation\(\{(.*?)\}\)", re.DOTALL)
_REQ = re.compile(r'require\(\s*["\']animations-([\w-]+)["\']\s*\)')
_ANIM_ENABLED = re.compile(r"animations\s*=\s*\{\s*enabled\s*=\s*(true|false)", re.DOTALL)


def _find_hypr_dir() -> Path | None:
    for d in HYPR_DIRS:
        if (d / "hyprland.lua").is_file():
            return d
    return None


def active_animations_file() -> str | None:
    """Name of the animations file Hyprland loads (``high``/``low``/None).

    ``hyprland.lua`` lists the files via ``require("animations-...")`` with the
    inactive one commented out; the first non-comment require wins.
    """
    d = _find_hypr_dir()
    if d is None:
        return None
    try:
        text = (d / "hyprland.lua").read_text()
    except OSError:
        return None
    for line in text.splitlines():
        if line.lstrip().startswith("--"):
            continue
        m = _REQ.search(line)
        if m:
            return m.group(1).lower()
    return None


def _parse_animations(path: Path) -> dict:
    """Parse ``hl.animation`` blocks into {leaf: {enabled, speed, bezier, style}}."""
    try:
        text = path.read_text()
    except OSError:
        return {}
    out: dict = {}
    for block in _ANIM_BLOCK.finditer(text):
        body = block.group(1)
        leaf_m = re.search(r'leaf\s*=\s*["\']([\w]+)["\']', body)
        if not leaf_m:
            continue
        leaf = leaf_m.group(1)
        speed = re.search(r"speed\s*=\s*(\d+)", body)
        enabled = re.search(r"enabled\s*=\s*(true|false)", body)
        bezier = re.search(r'bezier\s*=\s*["\']([\w]+)["\']', body)
        style = re.search(r'style\s*=\s*["\']([\w %]+)["\']', body)
        out[leaf] = {
            "enabled": (enabled.group(1) if enabled else "true") == "true",
            "speed": int(speed.group(1)) if speed else None,
            "bezier": bezier.group(1) if bezier else None,
            "style": style.group(1) if style else None,
        }
    return out


def border_animation() -> dict | None:
    """Border animation mirror for the bar, or None when Hyprland has none.

    Returns ``{"speed": int, "leaf": str}`` — the border color loops hue at a
    period derived from the enabled animations file's ``borderangle`` speed
    (falling back to ``border``). None when Hyprland's global animations are
    disabled, neither leaf is enabled, or the hypr config is unavailable.
    """
    name = active_animations_file()
    d = _find_hypr_dir()
    if not name or d is None:
        return None
    path = d / f"animations-{name}.lua"
    if not path.is_file():
        return None
    anims = _parse_animations(path)
    # Respect a global ``animations.enabled = false`` in the same file.
    try:
        text = path.read_text()
    except OSError:
        text = ""
    m = _ANIM_ENABLED.search(text)
    if m and m.group(1) == "false":
        return None
    # The looping gradient border is ``borderangle``; ``border`` is the
    # active/inactive color transition. Prefer borderangle's speed.
    for leaf in ("borderangle", "border"):
        info = anims.get(leaf)
        if info and info.get("enabled") and info.get("speed"):
            return {"leaf": leaf, "speed": int(info["speed"])}
    return None