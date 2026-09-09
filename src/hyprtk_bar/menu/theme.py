"""CSS assembly for hyprtk-menu.

The menu shares hyprtk-bar's theming model: it reads the SAME ``theme.source``
(``pywal`` | ``imported`` | ``manual``) and ``theme_name`` from the bar's config
so both resolve an identical palette. The resolved palette is then mapped onto
the menu's semantic tokens (panel_bg, text, accent, ...) that the base
``assets/style.css`` and layout CSS consume.
"""

# ─────────────────────────────────────────────────────────────────
#   HYPRTK · hyprtk-bar · theme
#   Part of the Hyprtk desktop suite · github.com/hyprtk
# ─────────────────────────────────────────────────────────────────


import colorsys
import os
import re

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, Gtk

from . import config as cfg
from .theme_import import find_themes_dir, list_themes, parse_palette

# The bar project root holds the menu's assets (copied to the install dir by
# install.sh). theme.py lives at <root>/src/hyprtk_bar/menu/theme.py, so four
# parent hops reach the root where assets/ lives.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
STYLE_CSS = os.path.join(BASE_DIR, "assets", "style.css")


def hue_rotate(hex_color: str, degrees: float) -> str:
    """Rotate a ``#rrggbb`` color's hue by ``degrees`` (loop-friendly)."""
    hex_color = (hex_color or "").strip()
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return hex_color
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return hex_color
    hue, lum, sat = colorsys.rgb_to_hls(r, g, b)
    hue = (hue + (degrees / 360.0)) % 1.0
    r, g, b = colorsys.hls_to_rgb(hue, lum, sat)
    return "#{:02x}{:02x}{:02x}".format(
        int(round(r * 255)), int(round(g * 255)), int(round(b * 255))
    )

LAYOUT_ICONS = {
    "whisker": "\uf0ca",
    "win7": "\uf108",
    "win11": "\uf108",
    "plasma": "\uf042",
}
LAYOUT_ORDER = list(cfg.LAYOUTS)


# Fallback palette (hyprtk defaults) when the pywal cache is missing.
FALLBACK = {
    "color0": "#11111b",
    "color1": "#f38ba8",
    "color2": "#a6e3a1",
    "color3": "#f9e2af",
    "color4": "#89b4fa",
    "color5": "#c084fc",
    "color6": "#22d3ee",
    "color7": "#cdd6f4",
    "color8": "#6c7086",
    "color9": "#f38ba8",
    "color10": "#a6e3a1",
    "color11": "#f9e2af",
    "color12": "#89b4fa",
    "color13": "#c084fc",
    "color14": "#22d3ee",
    "color15": "#f5f5f5",
    "background": "#1e1e2e",
    "foreground": "#cdd6f4",
}


def _contrast_fg(hex_color):
    """Pick black or white text that contrasts with the given hex background."""
    try:
        hex_color = hex_color.lstrip("#")
        if len(hex_color) == 3:
            hex_color = "".join(c * 2 for c in hex_color)
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, TypeError):
        return "#ffffff"
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#000000" if luminance > 140 else "#ffffff"


def _rgba(color, alpha):
    """Convert a #rgb/#rrggbb/#rrggbbaa/rgba()/rgb() color to rgba() string."""
    color = color.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", color)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {alpha:.2f})"
    m = re.search(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", color, re.I)
    if m:
        return f"rgba({int(m.group(1))}, {int(m.group(2))}, {int(m.group(3))}, {alpha:.2f})"
    m = re.search(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", color, re.I)
    if m:
        return f"rgba({int(m.group(1))}, {int(m.group(2))}, {int(m.group(3))}, {alpha:.2f})"
    return color


def _hover_color(color):
    """Return a translucent hover color, preserving the source's alpha."""
    color = color.strip()
    if color.startswith("#"):
        return _rgba(color, 0.12)
    if color.lower().startswith("rgb"):
        return color
    return "rgba(255, 255, 255, 0.12)"


# ── palette resolution (mirrors hyprtk-bar) ─────────────────────

def _import_theme_palette(theme):
    """Parse the bar's selected imported theme into a palette (or None)."""
    name = theme.get("theme_name")
    if not name:
        return None
    try:
        palette = parse_palette(name)
    except Exception:
        return None
    if palette is not None:
        palette["theme_name"] = name
    return palette


def resolve_palette():
    """Resolve the menu palette from the bar's theme.source.

    Returns a dict with ``background``/``foreground``/``accent``/``hover`` plus
    optional ``border_color``/``border_radius``/``theme_name`` when an imported
    theme is active — the same palette hyprtk-bar builds.

    When ``menu.follow_bar`` is off the menu resolves its OWN palette from pywal
    instead of mirroring the bar's chosen theme.
    """
    menu_cfg = cfg.load_config()
    follow_bar = bool(menu_cfg.get("follow_bar", True))
    if not follow_bar:
        return _own_palette()

    theme = cfg.load_bar_theme()
    source = theme.get("source", "pywal")
    palette = {
        "background": theme.get("background", "#1a1b26"),
        "foreground": theme.get("foreground", "#c0caf5"),
        "accent": theme.get("accent", "#7aa2f7"),
        "hover": theme.get("hover", "rgba(255, 255, 255, 0.08)"),
    }

    if source != "manual":
        if source == "imported":
            imported = _import_theme_palette(theme)
            if imported is not None:
                palette = imported
        if "background_alpha" not in palette:
            pywal = cfg.load_pywal_colors()
            if pywal:
                palette["background"] = pywal.get("background") or palette["background"]
                palette["foreground"] = pywal.get("foreground") or palette["foreground"]
                palette["accent"] = pywal.get("color5") or pywal.get("color4") or palette["accent"]
                palette["hover"] = _rgba(palette["foreground"], 0.08)
                palette["border_color"] = palette["accent"]
    return palette


def _own_palette():
    """The menu's own palette (menu.follow_bar = false): pywal-driven."""
    pywal = cfg.load_pywal_colors()
    if not pywal:
        return {
            "background": FALLBACK.get("background", "#1e1e2e"),
            "foreground": FALLBACK.get("foreground", "#cdd6f4"),
            "accent": FALLBACK.get("color5", "#c084fc"),
            "hover": "rgba(255, 255, 255, 0.08)",
        }
    accent = pywal.get("color5") or pywal.get("color4") or "#c084fc"
    return {
        "background": pywal.get("background") or FALLBACK.get("background", "#1e1e2e"),
        "foreground": pywal.get("foreground") or FALLBACK.get("foreground", "#cdd6f4"),
        "accent": accent,
        "hover": _rgba(pywal.get("foreground", "#cdd6f4"), 0.08),
        "border_color": accent,
    }


# ── palette -> menu semantic tokens ─────────────────────────────

def _palette_to_tokens(palette, pywal):
    """Map a resolved palette onto the menu's semantic CSS tokens."""
    accent = palette.get("accent", "#7aa2f7")
    fg = palette.get("foreground", "#c0caf5")
    bg = palette.get("background", "#1a1b26")
    selected_fg = _contrast_fg(accent)
    border = palette.get("border_color") or _rgba(accent, 0.35)
    accent_alt = (pywal or {}).get("color6") or accent
    return {
        "panel_bg": _rgba(bg, 0.92),
        "panel_border": border,
        "text": fg,
        "muted": _rgba(fg, 0.6),
        "selected_text": selected_fg,
        "accent": accent,
        "accent_alt": accent_alt,
        "surface": _rgba(accent, 0.07),
        "selected_bg": _rgba(accent, 0.28),
        "selected_border": _rgba(accent, 0.5),
        "input_bg": _rgba(accent, 0.08),
        "input_border": _rgba(accent, 0.25),
    }


def _palette_to_css(colors):
    lines = ["/* pywal palette */"]
    for name in FALLBACK:
        lines.append("@define-color %s %s;" % (name, colors.get(name, FALLBACK[name])))
    return "\n".join(lines)


def _tokens_to_css(tokens):
    lines = ["/* bar theme tokens */"]
    for key, value in tokens.items():
        lines.append("@define-color %s %s;" % (key, value))
    return "\n".join(lines)


def active_layout():
    """Current layout name, validated against known layouts."""
    name = cfg.load_config().get("layout", "whisker")
    return name if name in cfg.LAYOUTS else "whisker"


def layout_css(name):
    """Contents of the layout CSS file for `name` (empty if missing)."""
    path = os.path.join(BASE_DIR, "assets", "layout-%s.css" % name)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def build_css():
    """Assemble the final CSS: pywal palette, base rules, tokens, layout."""
    pywal = cfg.load_pywal_colors()
    colors = pywal or dict(FALLBACK)
    palette = resolve_palette()
    parts = [_palette_to_css(colors)]
    with open(STYLE_CSS, encoding="utf-8") as f:
        parts.append(f.read())
    parts.append(_tokens_to_css(_palette_to_tokens(palette, pywal)))
    parts.append(layout_css(active_layout()))
    return "\n".join(parts)


def wal_mtime():
    """Nanosecond mtime of the pywal colors.json (0 if missing)."""
    try:
        return os.stat(cfg.PYWAL_PATH).st_mtime_ns
    except OSError:
        return 0


def bar_config_mtime():
    """Nanosecond mtime of the bar config (0 if missing)."""
    try:
        return os.stat(cfg.BAR_CONFIG_FILE).st_mtime_ns
    except OSError:
        return 0


def themes_dir_mtime():
    """Nanosecond mtime of the bar themes dir (0 if missing)."""
    try:
        return os.stat(find_themes_dir()).st_mtime_ns
    except OSError:
        return 0


_provider = None
_anim_provider = None


def apply_css(css):
    """Load CSS into a single persistent provider and refresh all widgets."""
    global _provider
    screen = Gdk.Screen.get_default()
    if _provider is None:
        _provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            screen, _provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    _provider.load_from_data(css.encode("utf-8"))
    Gtk.StyleContext.reset_widgets(screen)


def panel_border_base():
    """The menu's current panel border color, as a hex (for hue rotation).

    Used as the base for the border animation's hue rotation. Falls back to
    the accent (hex) when no explicit border color is set.
    """
    palette = resolve_palette()
    return palette.get("border_color") or palette.get("accent", "#7aa2f7")


def apply_border_color(color: str):
    """Override just the menu panel's border-color (for the border animation).

    A dedicated provider loaded after the base one wins the cascade for
    ``.menu`` border-color, so re-theming the animated border each tick does
    not rebuild the whole stylesheet.
    """
    global _anim_provider
    screen = Gdk.Screen.get_default()
    if _anim_provider is None:
        _anim_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            screen, _anim_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
    _anim_provider.load_from_data(
        f".menu {{ border-color: {color}; }}".encode("utf-8")
    )
