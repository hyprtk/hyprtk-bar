"""Theming: resolve a palette (pywal + waybar import + config) and emit GTK CSS."""
from __future__ import annotations

import logging
import re

from .config import load_pywal_colors  # noqa: E402
from .waybar_theme import parse_palette  # noqa: E402

log = logging.getLogger("hyprtk_bar.theme")


def _contrast_fg(hex_color: str) -> str:
    """Pick black or white text that contrasts with the given hex background."""
    try:
        hex_color = hex_color.lstrip("#")
        if len(hex_color) == 3:
            hex_color = "".join(c * 2 for c in hex_color)
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#000000"
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#000000" if luminance > 140 else "#ffffff"


def _rgba(color: str, alpha: float) -> str:
    """Convert a #rgb/#rrggbb/#rrggbbaa/rgba()/rgb() color to an rgba() string."""
    color = color.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", color)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {alpha:.2f})"
    m = re.search(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", color, re.I)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"rgba({r}, {g}, {b}, {alpha:.2f})"
    m = re.search(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", color, re.I)
    if m:
        return f"rgba({int(m.group(1))}, {int(m.group(2))}, {int(m.group(3))}, {alpha:.2f})"
    return color


def _hover_color(color: str) -> str:
    """Return a translucent hover color, preserving the source's alpha.

    Hex colors get a subtle default alpha; rgba()/rgb() values are kept as-is so
    waybar-imported hover colors (already translucent) are not made opaque.
    """
    color = color.strip()
    if color.startswith("#"):
        return _rgba(color, 0.12)
    if color.lower().startswith("rgb"):
        return color
    return "rgba(255, 255, 255, 0.12)"


def resolve_palette(cfg: dict) -> dict:
    """Background/foreground/accent palette from the configured theme source.

    ``theme.source`` selects the source: ``pywal`` (live wallpaper palette),
    ``waybar`` (an imported waybar theme, dynamic to its pywal import), or
    ``manual`` (colors from the config's ``theme`` block).
    """
    theme = cfg.get("theme") or {}
    source = theme.get("source", "pywal" if cfg.get("use_pywal", True) else "manual")
    palette = {
        "background": theme.get("background", "#1a1b26"),
        "foreground": theme.get("foreground", "#c0caf5"),
        "accent": theme.get("accent", "#7aa2f7"),
        "hover": theme.get("hover", "rgba(255, 255, 255, 0.08)"),
        "running": theme.get("running", theme.get("accent", "#7aa2f7")),
    }

    if source == "manual":
        return palette

    if source == "waybar":
        imported = import_waybar_palette(theme)
        if imported is not None:
            return imported

    # pywal (also the fallback when a waybar import fails)
    pywal = load_pywal_colors()
    if pywal:
        palette["background"] = pywal.get("background") or palette["background"]
        palette["foreground"] = pywal.get("foreground") or palette["foreground"]
        palette["accent"] = pywal.get("color5") or pywal.get("color4") or palette["accent"]
        palette["running"] = palette["accent"]
    return palette


def import_waybar_palette(theme: dict) -> dict | None:
    """Import the configured waybar theme into a palette."""
    name = theme.get("waybar_theme")
    if not name:
        return None
    try:
        palette = parse_palette(name)
    except Exception as exc:  # never let a bad theme take down the bar
        log.warning("failed to import waybar theme %r: %s", name, exc)
        return None
    if palette is not None:
        palette["waybar_theme"] = name
    return palette


def build_css(palette: dict, cfg: dict) -> str:
    margin = cfg.get("margin", 6)
    radius = cfg.get("radius", 12)
    height = cfg.get("height", 42)
    opacity = cfg.get("opacity", 0.95)

    bg = _rgba(palette["background"], opacity)
    hover = _hover_color(palette["hover"])
    accent = palette["accent"]
    running = palette["running"]
    fg = palette["foreground"]
    active_fg = _contrast_fg(accent)
    font = palette.get("font")
    font_rule = f"  font-family: {font};\n" if font else ""

    return f"""
.taskbar {{
  background-color: {bg};
  border-radius: {radius}px;
  margin: {margin}px {margin}px {margin}px {margin}px;
  min-height: {height}px;
  color: {fg};
{font_rule}}}
.show-desktop {{
  background-color: {bg};
  border-radius: 5px;
  margin: 0;
  min-width: 10px;
  min-height: {height}px;
}}
.show-desktop.hover {{ background-color: {hover}; }}
.task-button {{ padding: 2px 6px; border-radius: {max(radius - 6, 4)}px; }}
.task-button.hover {{ background-color: {hover}; }}
.tray-button {{ padding: 2px 6px; border-radius: {max(radius - 6, 4)}px; }}
.tray-button.hover {{ background-color: {hover}; }}
.dimmed {{ opacity: 0.45; }}
.task-indicator {{
  min-width: 10px;
  min-height: 4px;
  border-radius: 2px;
  background-color: {running};
  margin: 0 3px;
}}
.task-button.active .task-indicator {{
  min-width: 22px;
  background-color: {accent};
}}
.workspace-chip {{
  padding: 0 10px;
  min-height: {max(height - 12, 16)}px;
  border-radius: {max(radius - 6, 4)}px;
  color: {fg};
}}
.workspace-chip.hover {{ background-color: {hover}; }}
.workspace-chip.occupied {{ color: {accent}; }}
.workspace-chip.active {{
  background-color: {accent};
  color: {active_fg};
}}
.divider {{
  min-width: 1px;
  min-height: 22px;
  border-radius: 1px;
  background-color: {_rgba(palette["foreground"], 0.25)};
}}
.clock {{ padding: 0 10px; border-radius: {max(radius - 6, 4)}px; }}
.clock.hover {{ background-color: {hover}; }}
.clock-label {{ font-weight: bold; }}
.clock-date {{ font-size: 10px; opacity: 0.85; }}
.sysmon {{ padding: 2px 8px; border-radius: {max(radius - 6, 4)}px; }}
.sysmon.hover {{ background-color: {hover}; }}
.sysmon-value {{ font-size: 11px; }}
.sysmon-value.warn {{ color: #facc15; }}
.sysmon-value.high {{ color: #f87171; }}
.popup-row {{ padding: 6px 8px; border-radius: 6px; }}
.popup-row.hover {{ background-color: {hover}; }}
.popup-title {{ font-weight: bold; padding-bottom: 4px; }}
.popup-box {{
  background-color: {_rgba(palette["background"], 1.0)};
  border-radius: {radius}px;
  padding: 8px;
  color: {fg};
}}
.qs-button {{ padding: 2px 6px; border-radius: {max(radius - 6, 4)}px; }}
.qs-button.hover {{ background-color: {hover}; }}
.qs-title {{ font-weight: bold; padding-bottom: 6px; }}
.qs-row {{ padding: 6px 8px; border-radius: 6px; }}
.qs-row.hover {{ background-color: {hover}; }}
.qs-switch {{
  min-width: 34px;
  min-height: 18px;
  border-radius: 9px;
  background-color: {_rgba(palette["foreground"], 0.22)};
}}
.qs-switch slider {{
  min-width: 14px;
  min-height: 14px;
  border-radius: 7px;
  margin: 2px;
  background-color: {fg};
}}
.qs-switch:checked {{
  background-color: {accent};
}}
.qs-switch:checked slider {{
  background-color: {_contrast_fg(accent)};
}}
.qs-scale trough {{
  min-height: 4px;
  border-radius: 2px;
  background-color: {_rgba(palette["foreground"], 0.22)};
}}
.qs-scale highlight {{
  min-height: 4px;
  border-radius: 2px;
  background-color: {accent};
}}
.qs-scale slider {{
  min-width: 12px;
  min-height: 12px;
  border-radius: 6px;
  background-color: {fg};
}}
.notif-button {{ padding: 2px 6px; border-radius: {max(radius - 6, 4)}px; }}
.notif-button.hover {{ background-color: {hover}; }}
.notif-badge {{
  background-color: {accent};
  color: {active_fg};
  font-size: 9px;
  font-weight: bold;
  min-width: 14px;
  min-height: 14px;
  border-radius: 7px;
  padding: 0 3px;
  margin: 0 0 2px 0;
}}
.notif-title {{ font-weight: bold; padding-bottom: 6px; }}
.notif-row {{
  background-color: {_rgba(palette["foreground"], 0.05)};
  border-radius: 8px;
  padding: 8px;
}}
.notif-app {{ font-size: 10px; opacity: 0.85; }}
.notif-time {{ font-size: 9px; opacity: 0.6; }}
.notif-summary {{ font-weight: bold; }}
.notif-body {{ font-size: 11px; opacity: 0.9; }}
.notif-action {{
  min-height: 20px;
  padding: 0 8px;
  border-radius: 6px;
  background-color: {_rgba(palette["accent"], 0.18)};
  color: {fg};
}}
.notif-clear {{ min-height: 22px; padding: 0 10px; border-radius: 6px; }}
"""