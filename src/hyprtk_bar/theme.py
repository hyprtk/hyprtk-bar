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
    ``manual`` (colors from the config's ``theme`` block). The configured
    ``font`` block (family + size) is applied on top of every source.
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

    if source != "manual":
        if source == "waybar":
            imported = import_waybar_palette(theme)
            if imported is not None:
                palette = imported

        if "background_alpha" not in palette:
            # pywal (also the fallback when a waybar import fails)
            pywal = load_pywal_colors()
            if pywal:
                palette["background"] = pywal.get("background") or palette["background"]
                palette["foreground"] = pywal.get("foreground") or palette["foreground"]
                palette["accent"] = pywal.get("color5") or pywal.get("color4") or palette["accent"]
                palette["running"] = palette["accent"]
                # 2px bar border drawn in the pywal accent color.
                palette["border_width"] = 2
                palette["border_color"] = palette["accent"]

    # The configured font (family + size) applies to every theme source.
    font_cfg = cfg.get("font") or {}
    family = (font_cfg.get("family") or "").strip()
    if family:
        palette["font"] = family
    try:
        size = max(8, int(font_cfg.get("size", 16)))
    except (TypeError, ValueError):
        size = 16
    palette["font_size"] = size
    # Chips follow the configured base size too — an imported theme's
    # chip_font_size must not pin them to a stale size when the user changes it.
    palette["chip_font_size"] = size
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


def _padding_css(nums: list) -> str:
    return " ".join(f"{n:g}px" for n in nums)


def _vertical_padding(nums: list) -> float:
    if len(nums) == 1:
        return nums[0] * 2
    if len(nums) == 2:
        return nums[0] * 2
    if len(nums) == 3:
        return nums[0] + nums[2]
    return nums[0] + nums[2]


def gap_value(cfg: dict, key: str, default: int) -> int:
    """Coerce a gap config value to ``int >= 0``; ``default`` for missing/None.

    Unlike ``x or default``, a stored ``0`` is kept (0 is a valid gap).
    """
    value = cfg.get(key)
    if value is None or value == "":
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def pill_margins(cfg: dict) -> tuple[int, int, int, int]:
    """(top, right, bottom, left) CSS margins of the .taskbar pill.

    ``gap_out`` is always the side toward the screen edge and ``gap_in`` the
    side toward app windows, so the vertical margins flip with the bar's
    position. The left/right margins stay a small fixed inset (the pill's
    rounded ends never touch the screen edges).
    """
    gap_in = gap_value(cfg, "gap_in", 6)
    gap_out = gap_value(cfg, "gap_out", 6)
    h = 6
    if cfg.get("position") == "top":
        return gap_out, h, gap_in, h
    return gap_in, h, gap_out, h


def build_css(palette: dict, cfg: dict) -> str:
    top_m, right_m, bottom_m, left_m = pill_margins(cfg)
    radius = palette.get("border_radius", cfg.get("radius", 12))
    height = cfg.get("height", 42)
    # The imported theme's background alpha (if any) maps to the bar opacity;
    # otherwise the configured opacity applies.
    opacity = palette.get("background_alpha", cfg.get("opacity", 0.95))

    bg = _rgba(palette["background"], opacity)
    hover = _hover_color(palette["hover"])
    accent = palette["accent"]
    running = palette["running"]
    fg = palette["foreground"]
    active_fg = _contrast_fg(accent)
    font = palette.get("font")
    font_rule = f"  font-family: {font};\n" if font else ""
    font_size = palette.get("font_size")
    font_size_rule = f"  font-size: {font_size:g}px;\n" if font_size else ""
    glyph_font = "Symbols Nerd Font"
    try:
        glyph_font = ((cfg.get("quicklinks") or {}).get("glyph_font") or "").strip() or glyph_font
    except AttributeError:
        pass
    # Quicklink glyph color: a palette key (accent/fg/running) or an explicit
    # color. Defaults to the pywal accent, matching the other icon modules.
    glyph_color = accent
    try:
        gcolor = ((cfg.get("quicklinks") or {}).get("glyph_color") or "").strip()
        if gcolor:
            glyph_color = {
                "accent": accent,
                "fg": fg,
                "foreground": fg,
                "running": running,
            }.get(gcolor, gcolor)
    except AttributeError:
        pass

    border_rule = ""
    extra_v = 0.0
    border_width = palette.get("border_width")
    border_color = palette.get("border_color")
    if border_width and border_color:
        border_rule = f"  border: {border_width:g}px solid {border_color};\n"
        extra_v += 2 * border_width
    # Popups (notification center, quick settings, toasts, previews) and the
    # right-click menu use the theme's background/foreground/border. Popups stay
    # mostly opaque for readability but carry the theme's border and color.
    popup_alpha = max(opacity, 0.9)
    popup_border_rule = border_rule if (border_width and border_color) else ""
    menu_border = border_color or _rgba(palette["foreground"], 0.18)
    padding_rule = ""
    padding = palette.get("padding")
    if padding:
        padding_rule = f"  padding: {_padding_css(padding)};\n"
        extra_v += _vertical_padding(padding)
    min_height = max(20, int(round(height - extra_v)))

    # ── workspace chips (#workspaces button) ─────────────────────
    chip_padding_rule = ""
    chip_padding = palette.get("chip_padding")
    if chip_padding:
        chip_padding_rule = f"  padding: {_padding_css(chip_padding)};\n"
    else:
        chip_padding_rule = "  padding: 0 10px;\n"
    chip_radius = palette.get("chip_radius", max(radius - 6, 4))
    chip_border_rule = ""
    chip_bw = palette.get("chip_border_width")
    chip_bc = palette.get("chip_border_color")
    if chip_bw and chip_bc:
        chip_border_rule = f"  border: {chip_bw:g}px solid {chip_bc};\n"
    chip_bg_rule = ""
    chip_bg = palette.get("chip_bg")
    if chip_bg:
        chip_bg_rule = f"  background-color: {chip_bg};\n"
    chip_fg_rule = ""
    chip_fg = palette.get("chip_fg")
    if chip_fg:
        chip_fg_rule = f"  color: {chip_fg};\n"
    chip_fs_rule = ""
    chip_fs = palette.get("chip_font_size")
    if chip_fs:
        chip_fs_rule = f"  font-size: {chip_fs:g}px;\n"
    chip_fw_rule = ""
    chip_fw = palette.get("chip_font_weight")
    if chip_fw:
        chip_fw_rule = f"  font-weight: {chip_fw};\n"

    # active chip (focused)
    active_bg = palette.get("active_bg", accent)
    if "active_bg" in palette and "active_fg" in palette:
        active_fg_final = palette["active_fg"]
    else:
        active_fg_final = _contrast_fg(active_bg)
    occupied_fg = palette.get("occupied_fg", accent)

    return f"""
.taskbar {{
  background-color: {bg};
  border-radius: {radius}px;
  margin: {top_m}px {right_m}px {bottom_m}px {left_m}px;
  min-height: {min_height}px;
  color: {fg};
{font_size_rule}{border_rule}{padding_rule}{font_rule}}}
.task-button {{ padding: 2px 6px; border-radius: {max(radius - 6, 4)}px; }}
.task-button.hover {{ background-color: {hover}; }}
.quicklink-glyph {{ color: {glyph_color}; font-family: {glyph_font}; }}
.accent-icon {{ color: {accent}; }}
.tray-button {{ padding: 2px 6px; border-radius: {max(radius - 6, 4)}px; }}
.tray-button.hover {{ background-color: {hover}; }}
.dimmed {{ opacity: 0.45; }}
.task-dot {{
  min-width: 8px;
  min-height: 8px;
  border-radius: 4px;
  background-color: {_rgba(palette["foreground"], 0.55)};
}}
.task-button.active .task-dot {{
  min-width: 10px;
  min-height: 10px;
  background-color: {accent};
}}
.workspace-chip {{
  min-height: {max(height - 12, 16)}px;
  border-radius: {chip_radius}px;
  color: {chip_fg or fg};
{chip_padding_rule}{chip_border_rule}{chip_bg_rule}{chip_fs_rule}{chip_fw_rule}}}
.workspace-chip.hover {{ background-color: {hover}; }}
.workspace-chip.occupied {{ color: {occupied_fg}; }}
.workspace-chip.active {{
  background-color: {active_bg};
  color: {active_fg_final};
}}
.divider {{
  min-width: 1px;
  min-height: 22px;
  border-radius: 1px;
  background-color: {_rgba(palette["foreground"], 0.25)};
}}
.clock {{ padding: 0 10px; border-radius: {max(radius - 6, 4)}px; }}
.clock.hover {{ background-color: {hover}; }}
.clock-label {{ font-weight: bold; font-size: inherit; }}
.clock-date {{ opacity: 0.85; font-size: inherit; }}
.kbstate {{ padding: 0 8px; border-radius: {max(radius - 6, 4)}px; }}
.kbstate.hover {{ background-color: {hover}; }}
.kbstate-icon {{ color: {fg}; }}
.kbstate-icon.on {{ color: {accent}; }}
.kbstate-icon.off {{ opacity: 0.35; }}
.window {{ padding: 2px 10px; border-radius: {max(radius - 6, 4)}px; }}
.window.hover {{ background-color: {hover}; }}
.window label {{ font-size: inherit; }}
.sysmon {{ padding: 2px 8px; border-radius: {max(radius - 6, 4)}px; }}
.sysmon.hover {{ background-color: {hover}; }}
.sysmon-value {{ font-size: inherit; }}
.sysmon-value.warn {{ color: #facc15; }}
.sysmon-value.high {{ color: #f87171; }}
.updates {{ padding: 2px 8px; border-radius: {max(radius - 6, 4)}px; }}
.updates.hover {{ background-color: {hover}; }}
.updates-value {{ font-size: inherit; }}
.updates-value.warn {{ color: #facc15; }}
.updates-value.high {{ color: #f87171; }}
.popup-row {{ padding: 6px 8px; border-radius: 6px; }}
.popup-row.hover {{ background-color: {hover}; }}
.popup-title {{ font-weight: bold; padding-bottom: 4px; }}
.tooltip-label {{ font-size: 12px; }}
.popup-box {{
  background-color: {_rgba(palette["background"], popup_alpha)};
  border-radius: {radius}px;
  padding: 8px;
  color: {fg};
{popup_border_rule}}}
menu {{
  background-color: {_rgba(palette["background"], 0.97)};
  border: 1px solid {menu_border};
  border-radius: {max(radius - 2, 6)}px;
  padding: 4px;
  color: {fg};
}}
menu menuitem {{ padding: 6px 14px; border-radius: 4px; }}
menu menuitem:hover {{ background-color: {hover}; }}
menu separator {{
  background-color: {_rgba(palette["foreground"], 0.15)};
  min-height: 1px;
  margin: 3px 6px;
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
.notif-dot {{
  background-color: {accent};
  color: {active_fg};
  font-size: 9px;
  font-weight: bold;
  min-width: 14px;
  min-height: 14px;
  border-radius: 7px;
  padding: 0 3px;
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