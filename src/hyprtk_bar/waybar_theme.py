"""Waybar theme import + resolution into a hyprtk-bar palette.

Themes are imported (folder with ``style.css``, usually plus ``colors.css``)
into the bar's own themes directory: ``~/.config/hyprtk-bar/themes/``. The bar
does NOT scan the system waybar directory.

``@import`` and ``@define-color`` are resolved (including pywal CSS files such
as ``~/.cache/wal/colors-waybar*.css``), so an imported theme that pulls in
pywal colors re-themes live whenever the wallpaper changes.

The palette is derived from the theme's CSS:
  background/foreground -> ``window#waybar`` (solidified)
  accent                -> a real accent color (define-colors / wal color)
  hover                 -> ``#workspaces button:hover`` (alpha preserved)
  font                  -> ``font-family`` from the ``*`` rule
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

log = logging.getLogger("hyprtk_bar.waybar_theme")

BAR_THEMES_DIR = Path.home() / ".config" / "hyprtk-bar" / "themes"

_COLOR_TOKEN = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|alpha\([^)]*\)"
)
_IMPORT_RE = re.compile(
    r"@import\s+(?:url\(\s*)?[\"']?([^\"');]+)[\"']?\s*\)?\s*;"
)
_DEFINE_RE = re.compile(r"@define-color\s+([\w-]+)\s+([^;]+);")
_BLOCK_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def find_themes_dir() -> Path:
    """Return the bar's own themes directory (created on demand)."""
    BAR_THEMES_DIR.mkdir(parents=True, exist_ok=True)
    return BAR_THEMES_DIR


def list_themes() -> list[str]:
    """Return sorted imported theme names (folders with a style.css)."""
    base = find_themes_dir()
    return sorted(
        d.name for d in base.iterdir()
        if d.is_dir() and (d / "style.css").is_file()
    )


def import_theme(path) -> str | None:
    """Import a waybar theme folder (or a single style.css) into the bar.

    ``@import`` paths that point outside the theme (e.g. pywal's
    ``~/.cache/wal`` CSS) are rewritten to absolute paths, because moving the
    theme breaks the relative depth. Returns the theme name on success.
    """
    path = Path(path)
    base = find_themes_dir()
    if path.is_dir():
        name = path.name
        dest = base / name
        dest.mkdir(parents=True, exist_ok=True)
        for fname in ("style.css", "colors.css", "config"):
            src = path / fname
            if src.is_file():
                try:
                    shutil.copy2(src, dest / fname)
                except OSError as exc:
                    log.warning("could not copy %s: %s", src, exc)
        _absolutize_theme_files(dest, path)
    elif path.is_file() and path.suffix.lower() == ".css":
        name = path.stem
        dest = base / name
        dest.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, dest / "style.css")
        except OSError as exc:
            log.warning("could not copy %s: %s", path, exc)
            return None
        _absolutize_theme_files(dest, path.parent)
    else:
        log.warning("not a waybar theme: %s", path)
        return None
    return name if (dest / "style.css").is_file() else None


def _absolutize_theme_files(dest: Path, origin_dir: Path) -> None:
    """Rewrite @import paths in copied CSS so files outside the theme resolve."""
    for fname in ("style.css", "colors.css"):
        target_file = dest / fname
        if not target_file.is_file():
            continue
        try:
            text = target_file.read_text(errors="replace")
        except OSError:
            continue
        rewritten = _absolutize_imports(text, origin_dir)
        if rewritten != text:
            try:
                target_file.write_text(rewritten)
            except OSError as exc:
                log.warning("could not rewrite imports in %s: %s", target_file, exc)


def _absolutize_imports(css: str, origin_dir: Path) -> str:
    """Return ``css`` with out-of-theme @import paths made absolute (~/...)."""
    home = Path.home()

    def repl(match) -> str:
        imp = match.group(1).strip()
        if imp.startswith("~") or imp.startswith("/"):
            return match.group(0)
        target = (origin_dir / imp).resolve()
        if not target.is_file():
            return match.group(0)
        try:
            target.relative_to(origin_dir)  # copied alongside: keep relative
            return match.group(0)
        except ValueError:
            pass
        try:
            newpath = f"~/{target.relative_to(home)}"
        except ValueError:
            newpath = str(target)
        return match.group(0).replace(match.group(1), newpath, 1)

    return _IMPORT_RE.sub(repl, css)


# ── CSS reading ─────────────────────────────────────────────────

def _resolve_import(origin: Path, imp: str) -> Path | None:
    if imp.startswith("~"):
        target = Path(imp).expanduser()
    elif imp.startswith("/"):
        target = Path(imp)
    else:
        target = (origin.parent / imp).resolve()
    if target.is_file():
        return target
    return None


def _read_with_imports(path: Path, _seen: set | None = None) -> str:
    _seen = _seen or set()
    if path in _seen:
        return ""
    _seen.add(path)
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    parts, pos = [], 0
    for match in _IMPORT_RE.finditer(text):
        parts.append(text[pos:match.start()])
        target = _resolve_import(path, match.group(1).strip())
        if target is not None:
            parts.append(_read_with_imports(target, _seen))
        pos = match.end()
    parts.append(text[pos:])
    return "".join(parts)


def _read_theme_css(theme_dir: Path) -> str:
    css = _read_with_imports(theme_dir / "style.css")
    colors_css = theme_dir / "colors.css"
    if colors_css.is_file():
        css += "\n" + _read_with_imports(colors_css)
    return css


def _parse_define_colors(css: str) -> dict[str, str]:
    colors = dict(_DEFINE_RE.findall(css))
    for _ in range(5):  # resolve @define-color foo @bar chains
        changed = False
        for name, value in list(colors.items()):
            m = re.fullmatch(r"@([\w-]+)", value.strip())
            if m and m.group(1) in colors:
                colors[name] = colors[m.group(1)]
                changed = True
        if not changed:
            break
    return colors


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _css_blocks(css: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for match in _BLOCK_RE.finditer(_strip_comments(css)):
        selector = " ".join(match.group(1).split())
        body = match.group(2).strip()
        if body and selector:
            blocks.setdefault(selector, body)
    return blocks


# ── color resolution ────────────────────────────────────────────

def _resolve_value(value: str, colors: dict[str, str]) -> str | None:
    """Turn a CSS color value (possibly @name / alpha() / hex) into a usable color."""
    value = value.strip()
    if not value:
        return None
    if value.lower() in ("transparent", "none"):
        return None
    if value.lower() in ("white", "black"):
        return {"white": "#ffffff", "black": "#000000"}[value.lower()]
    if value.startswith("#") or value.startswith("rgb"):
        return value
    m = re.fullmatch(r"alpha\(\s*([^,]+)\s*,\s*([\d.]+)\s*\)", value, re.I)
    if m:
        base = _resolve_value(m.group(1), colors)
        rgba = _to_rgba_tuple(base)
        if rgba:
            r, g, b = rgba
            return f"rgba({r}, {g}, {b}, {float(m.group(2)):.2f})"
    m = re.fullmatch(r"@([\w-]+)", value)
    if m and m.group(1) in colors:
        return _resolve_value(colors[m.group(1)], colors)
    return None


def _to_rgba_tuple(color: str | None) -> tuple[int, int, int] | None:
    if not color:
        return None
    color = color.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", color)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        try:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            return None
    m = re.search(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", color)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


def _solid(color: str) -> str:
    """Return an opaque version of a color (strip its alpha)."""
    color = color.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", color)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        return f"#{h[0:6]}"
    m = re.search(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", color)
    if m:
        return f"rgba({int(m.group(1))}, {int(m.group(2))}, {int(m.group(3))}, 1.00)"
    return color


def _prop(body: str, name: str) -> str | None:
    m = re.search(rf"\b{name}\s*:\s*([^;]+);", body)
    return m.group(1).strip() if m else None


def _background_color(body: str, colors: dict[str, str]) -> str | None:
    value = _prop(body, "background") or _prop(body, "background-color")
    if not value:
        return None
    if "gradient" in value.lower():
        tokens = [t for t in _COLOR_TOKEN.findall(value)]
        if tokens:
            # gradients end in the darkest stop: take the last resolvable token
            for token in reversed(tokens):
                resolved = _resolve_value(token, colors)
                if resolved:
                    return resolved
    return _resolve_value(value, colors)


def _text_color(body: str, colors: dict[str, str]) -> str | None:
    return _resolve_value(_prop(body, "color") or "", colors)


def _font_family(blocks: dict[str, str]) -> str | None:
    for selector in ("*", "window#waybar"):
        body = blocks.get(selector)
        value = _prop(body, "font-family") if body else None
        if value:
            first = value.split(",")[0].strip().strip('"').strip("'")
            if first:
                return first
    return None


# ── palette extraction ──────────────────────────────────────────

def parse_palette(theme_name: str) -> dict | None:
    """Parse an imported theme into a hyprtk-bar palette dict, or None."""
    theme_dir = find_themes_dir() / theme_name
    if not (theme_dir / "style.css").is_file():
        return None
    css = _read_theme_css(theme_dir)
    colors = _parse_define_colors(css)
    blocks = _css_blocks(css)

    def pick(kind: str, selector: str) -> str | None:
        body = blocks.get(selector)
        if body:
            if kind == "background":
                return _background_color(body, colors)
            return _text_color(body, colors)
        return None

    background = _solid(
        pick("background", "window#waybar")
        or colors.get("background")
        or colors.get("color0")
        or "#1a1b26"
    )
    foreground = _solid(
        pick("color", "window#waybar")
        or colors.get("foreground")
        or colors.get("color7")
        or "#c0caf5"
    )
    accent = _solid(
        colors.get("accent")
        or colors.get("color5")
        or colors.get("color4")
        or colors.get("mauve")
        or colors.get("sky")
        or pick("background", "#workspaces button.active")
        or foreground
    )
    hover = (
        pick("background", "#workspaces button:hover")
        or "rgba(255, 255, 255, 0.08)"
    )
    font = _font_family(blocks)

    palette = {
        "background": background,
        "foreground": foreground,
        "accent": accent,
        "hover": hover,
        "running": accent,
    }
    if font:
        palette["font"] = font
    return palette