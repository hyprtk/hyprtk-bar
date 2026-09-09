"""System theming dialogue for hyprtk-bar.

Opened by the wallpaper quick link (the wallpaper glyph inside the quicklinks
module): a layer-shell panel with a sidebar of theming pages — Wallpaper /
Pywal / Rofi / Bar themes / Matuwall / Swaylock / Icons / SDDM & GRUB. This is
theme-gui's functionality ported into the bar (GTK4/Adwaita -> GTK3/layer-shell)
so the bar can theme the system itself, matching the rest of the desktop through
the shared palette.

The dialogue is a ``Popup`` (layer-shell) like the system monitor, but keeps
``ON_DEMAND`` keyboard focus so its text entries are usable. All colours come
from the bar's resolved palette (pywal / imported theme / manual).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import subprocess
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell  # noqa: E402

from .popup import Popup  # noqa: E402
from .theme_import import import_theme, list_themes  # noqa: E402
from .widgets import Glyph, HoverButton  # noqa: E402

log = logging.getLogger("hyprtk_bar.themer")

# ── paths (mirror theme-gui's paths.py) ────────────────────────────────────
HOME = Path.home()
HYPRTK = HOME / "hyprtk"
WAL_CACHE = HOME / ".cache" / "wal"
BAR_CONFIG = HOME / ".config" / "hyprtk-bar" / "config.json"
ROFI_CONFIG = HOME / ".config" / "rofi"
ROFI_VARIANTS = ROFI_CONFIG / "variants"
ROFI_VARIANT_LINK = ROFI_CONFIG / "variant.rasi"
SWAYLOCK_CONFIG = HOME / ".config" / "swaylock" / "config"
MATUWALL_CONFIG = HOME / ".config" / "matuwall" / "config.json"
WALLPAPER_COLORS_SH = HYPRTK / "hypr" / "scripts" / "wallpaper-colors.sh"
CHANGE_ICONS_SH = HYPRTK / "configs" / "papirus-icons" / "scripts" / "change-icons.sh"
SYNC_ROFI_SH = HYPRTK / "configs" / "rofi" / "scripts" / "sync-rofi-theme.sh"
SDDM_UPDATE_SH = HYPRTK / "configs" / "sddm" / "update.sh"
ICON_THEME_DIR = HOME / ".local" / "share" / "icons" / "Papirus-Dark" / "48x48" / "places"
PAPIRUS_FOLDERS = HOME / ".local" / "bin" / "papirus-folders"
PAPIRUS_FOLDERS_SH = HOME / ".local" / "share" / "icons" / "papirus-folders.sh"
ICON_CACHE_THEME_DIRS = [
    HOME / ".local" / "share" / "icons" / "Papirus-Dark",
    HOME / ".local" / "share" / "icons" / "Papirus",
    HOME / ".local" / "share" / "icons" / "Papirus-Light",
]
THUMB_DIR = HOME / ".cache" / "theme-gui" / "thumbnails"
INDEX_FILE = HOME / ".cache" / "theme-gui" / "wallpaper-index.json"
WALLPAPER_DIRS = [
    HOME / "Pictures" / "Wallpapers",
    HOME / "Pictures",
    HYPRTK / "assets" / "Wallpapers",
]
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

# ── layout ────────────────────────────────────────────────────────────────
PAGES = [
    ("wallpaper", "\uf03e", "Wallpaper"),   # fa-picture-o
    ("pywal", "\uf043", "Pywal"),           # fa-tint
    ("rofi", "\uf009", "Rofi"),             # fa-th-large
    ("bar", "\uf1fc", "Bar Themes"),        # fa-paint-brush
    ("matuwall", "\uf1c5", "Matuwall"),     # fa-file-image-o
    ("swaylock", "\uf023", "Swaylock"),     # fa-lock
    ("icons", "\uf02d", "Icons"),           # fa-bookmark-o
    ("sddm", "\uf005", "SDDM & GRUB"),      # fa-star
]
_PAGE_TITLES = {key: label for key, _glyph, label in PAGES}

DIALOG_WIDTH = 940
DIALOG_HEIGHT = 640
_THUMB_SIZE = (360, 240)
_SDDM_PREVIEW = (620, 220)
_BATCH_SIZE = 20
POST_ACTION_DELAY_MS = 2500

# ── color helpers ─────────────────────────────────────────────────────────


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = (hex_color or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) >= 6:
        try:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            pass
    return 0, 0, 0


def _hex_to_rgba(hex_color: str, alpha: float = 1.0) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgba({r},{g},{b},{alpha:.2f})"


def _rgba_to_hex(red: float, green: float, blue: float, alpha: float = 1.0) -> str:
    r, g, b = (int(round(v * 255)) for v in (red, green, blue))
    a = int(round(alpha * 255))
    if a < 255:
        return f"#{r:02x}{g:02x}{b:02x}{a:02x}"
    return f"#{r:02x}{g:02x}{b:02x}"


def _contrast_fg(hex_bg: str) -> str:
    r, g, b = _hex_to_rgb(hex_bg)

    def _linear(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)
    return "#000000" if luminance > 0.179 else "#ffffff"


def _is_valid_hex(value: str) -> bool:
    if not isinstance(value, str):
        return False
    h = value.strip().lstrip("#")
    return len(h) in (6, 8) and all(c in "0123456789abcdefABCDEF" for c in h)


def _parse_wal_colors() -> dict[str, str]:
    """Parse ~/.cache/wal/colors.sh into {color0..15, background, foreground}."""
    result: dict[str, str] = {}
    sh = WAL_CACHE / "colors.sh"
    src = sh if sh.exists() else WAL_CACHE / "colors"
    if not src.exists():
        return result
    for line in src.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip("'\"")
        if _is_valid_hex(val):
            result[key.strip()] = val
    return result


def _read_swaylock_config() -> dict[str, str]:
    result: dict[str, str] = {}
    if not SWAYLOCK_CONFIG.exists():
        return result
    for line in SWAYLOCK_CONFIG.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip()
    return result


def _write_swaylock_config(data: dict[str, str]):
    _atomic_write(SWAYLOCK_CONFIG, "\n".join(f"{k}={v}" for k, v in data.items()) + "\n")


def _atomic_write(path: Path, content: str):
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── thumbnail cache (reuses theme-gui's cache) ────────────────────────────


def _thumb_path(src: Path) -> Path:
    h = hashlib.md5(str(src).encode(), usedforsecurity=False).hexdigest()[:12]
    return THUMB_DIR / f"{h}.png"


def _generate_thumbnail(src: Path, dest: Path):
    pb = _cover_pixbuf(str(src), _THUMB_SIZE[0], _THUMB_SIZE[1])
    if pb is not None:
        pb.savev(str(dest), "png", [], [])


def _thumb_size_ok(tp: Path) -> bool:
    """True if the cached thumbnail is the current size (cover-cropped)."""
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(str(tp))
        return (
            pb.get_width() == _THUMB_SIZE[0] and pb.get_height() == _THUMB_SIZE[1]
        )
    except GLib.Error:
        return False


def _cover_pixbuf(src: str, width: int, height: int):
    """Load *src* and scale+crop it to cover ``(width, height)``.

    Returns a pixbuf cropped from the centre (Gtk.Image cannot cover-fit, so
    the preview thumbnail is cropped like a photo instead of letterboxed).
    """
    try:
        buf = GdkPixbuf.Pixbuf.new_from_file(src)
    except GLib.Error:
        return None
    src_w, src_h = buf.get_width(), buf.get_height()
    if src_w <= 0 or src_h <= 0:
        return None
    scale = max(width / src_w, height / src_h)
    new_w = max(width, int(round(src_w * scale)))
    new_h = max(height, int(round(src_h * scale)))
    scaled = buf.scale_simple(new_w, new_h, GdkPixbuf.InterpType.BILINEAR)
    x = (new_w - width) // 2
    y = (new_h - height) // 2
    return GdkPixbuf.Pixbuf.new_subpixbuf(scaled, x, y, width, height)


def _fit_pixbuf(src: str, max_w: int, max_h: int):
    """Load *src* and scale it down to fit within ``(max_w, max_h)``.

    Preserves the aspect ratio and never upscales a small image (``contain``
    fit). Returns None if the file cannot be decoded.
    """
    try:
        buf = GdkPixbuf.Pixbuf.new_from_file(src)
    except GLib.Error:
        return None
    src_w, src_h = buf.get_width(), buf.get_height()
    if src_w <= 0 or src_h <= 0:
        return None
    scale = min(max_w / src_w, max_h / src_h, 1.0)
    if scale >= 1.0:
        return buf
    return buf.scale_simple(
        max(1, int(round(src_w * scale))),
        max(1, int(round(src_h * scale))),
        GdkPixbuf.InterpType.BILINEAR,
    )


def scan_wallpapers(wallpaper_dir: Path) -> list[Path]:
    """Sorted image files (top level only) under *wallpaper_dir*."""
    if not wallpaper_dir.is_dir():
        return []
    return sorted(
        p for p in wallpaper_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS
    )


def _thumb_needs_rebuild(img: Path, tp: Path, force: bool) -> bool:
    """True when the cached thumbnail for *img* is missing or stale."""
    if force or not tp.exists():
        return True
    try:
        if tp.stat().st_mtime < img.stat().st_mtime:
            return True
    except OSError:
        return True
    return not _thumb_size_ok(tp)


def cache_steps(wallpaper_dir: Path, force: bool = False):
    """Generate preview thumbnails for *wallpaper_dir*, yielding (done, total).

    Handles one image per step so a large directory never blocks the UI — callers
    drive it with ``GLib.idle_add`` and update a progress bar between steps.
    Thumbnails are written individually, so an interrupted run simply resumes on
    the next run; the index file is only written once every image is handled.
    """
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    images = scan_wallpapers(wallpaper_dir)
    total = len(images)
    for done, img in enumerate(images, 1):
        tp = _thumb_path(img)
        if _thumb_needs_rebuild(img, tp, force):
            try:
                _generate_thumbnail(img, tp)
            except Exception as exc:
                log.warning("thumb fail %s: %s", img.name, exc)
        yield done, total
    index = [
        {"path": str(img), "thumb": str(_thumb_path(img)), "name": img.name}
        for img in images
    ]
    _atomic_write(INDEX_FILE, json.dumps(index, indent=1))


def load_index() -> list[dict]:
    if not INDEX_FILE.exists():
        return []
    try:
        return json.loads(INDEX_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def index_matches_dir(index: list[dict], wallpaper_dir: Path) -> bool:
    """True when *index* was built for *wallpaper_dir* (not another folder)."""
    for entry in index[:8]:
        if Path(entry.get("path", "")).parent == wallpaper_dir:
            return True
    return False


def is_valid(wallpaper_dir: Path) -> bool:
    if not INDEX_FILE.exists():
        return False
    idx = load_index()
    if not idx:
        return False
    cached_dirs = {Path(e["path"]).parent for e in idx}
    return wallpaper_dir in cached_dirs


# ── shared widgets ────────────────────────────────────────────────────────


def _remove_all_children(widget):
    for child in list(widget.get_children()):
        widget.remove(child)
        child.destroy()


def _set_label_css(widget: Gtk.Widget, css: str):
    provider = Gtk.CssProvider()
    provider.load_from_data(css.encode())
    widget.get_style_context().add_provider(
        provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def _radio_group(labels: list[tuple[str, str]]) -> dict[str, Gtk.RadioButton]:
    """Build a Gtk.RadioButton group from ``(key, label)`` pairs.

    Mirrors bar_settings._radio_group: buttons are created standalone and
    joined with ``join_group`` (new_with_label(group=...) is unreliable here).
    """
    buttons: dict[str, Gtk.RadioButton] = {}
    first: Gtk.RadioButton | None = None
    for key, label in labels:
        btn = Gtk.RadioButton(group=None, label=label)
        if first is not None:
            btn.join_group(first)
        else:
            first = btn
        buttons[key] = btn
    return buttons


class ColorButton(Gtk.Button):
    """A swatch button that opens a GTK3 colour chooser dialog."""

    def __init__(self, hex_color: str = "#ffffff", **kwargs):
        super().__init__(**kwargs)
        self._color = hex_color
        self._callback = None
        self._provider = Gtk.CssProvider()
        self._apply_color(hex_color)
        self.get_style_context().add_provider(
            self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
        )
        self.set_size_request(40, 40)
        self.connect("clicked", self._on_clicked)

    def _apply_color(self, hex_color: str):
        h = hex_color.lstrip("#")
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        r, g, b = _hex_to_rgb(hex_color)
        css = (
            f"button {{ background: rgba({r},{g},{b},{a:.2f}); "
            f"border-radius: 10px; min-width: 32px; min-height: 32px; padding: 0; }}"
        )
        self._provider.load_from_data(css.encode())
        self.queue_draw()

    def get_color(self) -> str:
        return self._color

    def set_color(self, hex_color: str):
        self._color = hex_color
        self._apply_color(hex_color)

    def connect_color_changed(self, callback):
        self._callback = callback

    def _on_clicked(self, *_args):
        parent = self.get_toplevel()
        dialog = Gtk.ColorChooserDialog(
            title="Pick a Colour",
            transient_for=parent if isinstance(parent, Gtk.Window) else None,
        )
        dialog.set_use_alpha(True)
        rgba = Gdk.RGBA()
        rgba.parse(self._color)
        dialog.set_rgba(rgba)
        dialog.connect("response", self._on_response)
        dialog.show()

    def _on_response(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            rgba = dialog.get_rgba()
            hex_str = _rgba_to_hex(rgba.red, rgba.green, rgba.blue, rgba.alpha)
            self.set_color(hex_str)
            if self._callback:
                self._callback(hex_str)
        dialog.destroy()


def _add_entry_row(parent: Gtk.Box, label: str) -> Gtk.Entry:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    lbl = Gtk.Label(label=label, xalign=1)
    lbl.set_size_request(140, -1)
    entry = Gtk.Entry()
    entry.set_hexpand(True)
    row.pack_start(lbl, False, False, 0)
    row.pack_start(entry, True, True, 0)
    parent.pack_start(row, False, False, 0)
    return entry


def _add_switch_row(parent: Gtk.Box, label: str) -> Gtk.Switch:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    lbl = Gtk.Label(label=label, xalign=1)
    lbl.set_size_request(140, -1)
    switch = Gtk.Switch()
    row.pack_start(lbl, False, False, 0)
    row.pack_start(switch, False, False, 0)
    parent.pack_start(row, False, False, 0)
    return switch


def _add_section_title(parent: Gtk.Box, text: str):
    label = Gtk.Label(label=text, xalign=0)
    label.get_style_context().add_class("mc-page-title")
    label.set_margin_top(6)
    parent.pack_start(label, False, False, 0)


def _page_scroller(box: Gtk.Box) -> Gtk.ScrolledWindow:
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroller.set_vexpand(True)
    box.set_margin_top(4)
    box.set_margin_bottom(4)
    box.set_margin_start(4)
    box.set_margin_end(4)
    scroller.add(box)
    return scroller


# ── the theming dialogue ──────────────────────────────────────────────────


class ThemerDialog(Popup):
    """Layer-shell theming panel: sidebar + stack of theming pages."""

    def __init__(self, cfg: dict, restart_cb=None, theme_cb=None):
        super().__init__(cfg, cfg.get("position", "bottom"))
        self._cfg = cfg
        self._restart_cb = restart_cb
        self._theme_cb = theme_cb
        self._status = None
        self._closed = False
        self._cache_running = False
        self._cache_gen = None
        self._cache_step_id = None
        self._progress = None
        self._vadj = None
        self._flow = None
        self._all_images = []
        self._thumb_map = {}
        self._loaded_count = 0
        self._fill_id = None
        self.connect("destroy", self._on_themer_destroy)
        self._status_id = None
        self._side_buttons: dict[str, HoverButton] = {}
        self._active = ""

        # This dialogue has text entries — grab keyboard focus on demand so
        # entries/switches/color-choosers are usable (Popup defaults to NONE).
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        self.set_accept_focus(True)
        self.connect("key-press-event", self._on_key)

        self._fixed_size = (DIALOG_WIDTH, DIALOG_HEIGHT)
        self.set_size_request(DIALOG_WIDTH, DIALOG_HEIGHT)
        self.content.set_size_request(DIALOG_WIDTH, DIALOG_HEIGHT)

        # ── header ────────────────────────────────────────────────
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Theme Manager", xalign=0)
        title.get_style_context().add_class("mc-title")
        header.pack_start(title, True, True, 0)
        close = Gtk.Button(label="\u00d7")
        close.get_style_context().add_class("mc-close")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.connect("clicked", lambda *_: self.hide_popup())
        header.pack_start(close, False, False, 0)
        self.content.pack_start(header, False, False, 0)

        # ── body: sidebar + stack ─────────────────────────────────
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sidebar.get_style_context().add_class("mc-sidebar")
        sidebar.set_size_request(132, -1)
        self._sidebar = sidebar

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(120)

        for key, glyph, label in PAGES:
            sidebar.pack_start(self._build_side_button(key, glyph, label),
                               False, False, 0)
            self._stack.add_named(self._build_page(key), key)

        body.pack_start(sidebar, False, False, 0)
        body.pack_start(self._stack, True, True, 0)
        self.content.pack_start(body, True, True, 0)

        # ── status line (toast stand-in) ──────────────────────────
        self._status = Gtk.Label(label="", xalign=0)
        self._status.get_style_context().add_class("mc-unavailable")
        self.content.pack_start(self._status, False, False, 0)

        self._apply_theme_fg_class(self.content)
        self._set_active(PAGES[0][0])
        self.content.show_all()

    # ── chrome ────────────────────────────────────────────────────

    def _on_key(self, _window, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_popup()
            return True
        return False

    def _toast(self, message: str, timeout: int = 3) -> None:
        if self._status is None:
            return
        self._status.set_text(message)
        if self._status_id is not None:
            GLib.source_remove(self._status_id)
        self._status_id = GLib.timeout_add_seconds(timeout, self._clear_status)

    def _clear_status(self) -> bool:
        self._status_id = None
        self._status.set_text("")
        return GLib.SOURCE_REMOVE

    def _on_themer_destroy(self, *_args) -> None:
        """Stop any in-flight cache build when the dialogue is destroyed."""
        self._closed = True
        if self._cache_step_id is not None:
            GLib.source_remove(self._cache_step_id)
            self._cache_step_id = None
        self._cache_running = False
        self._cache_gen = None

    def _apply_theme_fg_class(self, widget) -> None:
        """Theme standard GTK widgets like the settings dialogue does."""
        from .theme import resolve_palette

        palette = resolve_palette(self._cfg)
        fg = palette.get("foreground", "#14141e")
        bg = palette.get("background", "#ffffff")

        def _hex(color: str) -> str:
            m = re.search(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", color)
            if m:
                return "#%02x%02x%02x" % (
                    int(m.group(1)), int(m.group(2)), int(m.group(3))
                )
            return color

        def _rgba(hex_color: str) -> Gdk.RGBA:
            h = hex_color.lstrip("#")
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return Gdk.RGBA(r / 255, g / 255, b / 255, 1.0)

        fg_rgba = _rgba(_hex(fg))
        states = (
            Gtk.StateFlags.NORMAL,
            Gtk.StateFlags.ACTIVE,
            Gtk.StateFlags.SELECTED,
            Gtk.StateFlags.INSENSITIVE,
            Gtk.StateFlags.FOCUSED,
            Gtk.StateFlags.BACKDROP,
            Gtk.StateFlags.SELECTED | Gtk.StateFlags.FOCUSED,
        )

        def _apply(w):
            ctx = w.get_style_context()
            if isinstance(w, Gtk.Button):
                if w.get_relief() != Gtk.ReliefStyle.NONE:
                    w.set_relief(Gtk.ReliefStyle.NONE)
                if not ctx.has_class("settings-apply"):
                    ctx.add_class("settings-btn")
            elif isinstance(w, Gtk.Label):
                ctx.add_class("settings-label")
            elif isinstance(w, Gtk.CheckButton):
                ctx.add_class("settings-check")
            elif isinstance(w, Gtk.RadioButton):
                ctx.add_class("settings-radio")
            elif isinstance(w, (Gtk.SpinButton, Gtk.Entry)):
                ctx.add_class("settings-input")
                for state in states:
                    try:
                        w.override_color(state, fg_rgba)
                        w.override_background_color(state, _rgba(_hex(bg)))
                    except Exception:
                        pass
            if isinstance(w, Gtk.Container):
                for child in w.get_children():
                    _apply(child)

        _apply(widget)

    def _build_side_button(self, key: str, glyph: str, label: str) -> HoverButton:
        btn = HoverButton("mc-sidebar-button", vertical=False, spacing=8)
        btn.set_size_request(-1, 30)
        icon = Glyph(glyph, "mc-icon")
        icon.set_pixel_size(14)
        btn.box.pack_start(icon, False, False, 0)
        lbl = Gtk.Label(label=label, xalign=0)
        lbl.get_style_context().add_class("mc-sidebar-label")
        btn.box.pack_start(lbl, True, True, 0)
        btn.connect("button-press-event",
                    lambda _w, _e, k=key: self._on_side(k) or False)
        self._side_buttons[key] = btn
        return btn

    def _on_side(self, key: str) -> None:
        if key != self._active:
            self._set_active(key)

    def _set_active(self, key: str) -> None:
        self._active = key
        for k, btn in self._side_buttons.items():
            box = btn.box
            if k == key:
                box.get_style_context().add_class("active")
            else:
                box.get_style_context().remove_class("active")
        self._stack.set_visible_child_name(key)
        if key == "pywal":
            self._refresh_pywal()
        elif key == "sddm":
            self._refresh_sddm_preview()

    # ── pages ─────────────────────────────────────────────────────

    def _build_page(self, key: str) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_hexpand(True)
        scroller = _page_scroller(box)
        builder = getattr(self, f"_build_{key}_page", None)
        if builder is not None:
            builder(box, scroller)
        return scroller

    # ── wallpaper ─────────────────────────────────────────────────

    def _build_wallpaper_page(self, box: Gtk.Box, scroller: Gtk.ScrolledWindow) -> None:
        self._wall_dir = Path(str(self._cfg.get("themer", {}).get(
            "wallpaper_dir", str(WALLPAPER_DIRS[0]))))
        self._preview_w, self._preview_h = _THUMB_SIZE

        # selected / current wallpaper preview (a cropped thumbnail, not the
        # full-resolution image).
        preview_wrap = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        preview_wrap.set_halign(Gtk.Align.CENTER)
        self._current_img = Gtk.Image()
        self._current_img.set_size_request(self._preview_w, self._preview_h)
        self._current_img.get_style_context().add_class("wallpaper-preview")
        preview_wrap.pack_start(self._current_img, False, False, 0)
        box.pack_start(preview_wrap, False, False, 0)

        _add_section_title(box, "Wallpaper Directory")
        dir_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._dir_label = Gtk.Label(label=str(self._wall_dir), xalign=0)
        self._dir_label.set_ellipsize(3)
        self._dir_label.set_tooltip_text(str(self._wall_dir))
        dir_row.pack_start(self._dir_label, True, True, 0)
        choose_btn = Gtk.Button(label="Choose")
        choose_btn.connect("clicked", self._on_choose_dir)
        dir_row.pack_start(choose_btn, False, False, 0)
        box.pack_start(dir_row, False, False, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        apply_btn = Gtk.Button(label="Apply Wallpaper")
        apply_btn.get_style_context().add_class("settings-apply")
        apply_btn.connect("clicked", self._apply_selected)
        btn_row.pack_start(apply_btn, False, False, 0)
        random_btn = Gtk.Button(label="Random")
        random_btn.connect("clicked", self._apply_random)
        btn_row.pack_start(random_btn, False, False, 0)
        build_btn = Gtk.Button(label="Build Cache")
        build_btn.connect("clicked", self._on_build_cache)
        btn_row.pack_start(build_btn, False, False, 0)
        box.pack_start(btn_row, False, False, 0)

        # Cache-build progress (automatic on open + manual "Build Cache").
        self._progress = Gtk.ProgressBar()
        self._progress.set_show_text(True)
        self._progress.set_no_show_all(True)
        box.pack_start(self._progress, False, False, 0)

        # 2-column thumbnail grid under the preview.
        self._flow = Gtk.FlowBox()
        self._flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flow.set_column_spacing(6)
        self._flow.set_row_spacing(6)
        self._flow.set_max_children_per_line(2)
        self._flow.set_min_children_per_line(2)
        self._flow.set_vexpand(True)
        box.pack_start(self._flow, True, True, 0)
        self._vadj = scroller.get_vadjustment()
        scroller.connect("edge-reached", self._on_flow_edge)
        if self._vadj is not None:
            self._vadj.connect("value-changed", self._on_vadj_changed)

        self._all_images: list[Path] = []
        self._thumb_map: dict[str, str] = {}
        self._loaded_count = 0
        self._selected: Path | None = None
        self._fill_id = None
        self._load_current()
        self._load_thumbnails()

    def _on_flow_edge(self, _scroll, pos):
        if pos == Gtk.PositionType.BOTTOM:
            self._fill_batches()

    def _on_vadj_changed(self, _adj):
        self._fill_batches()

    def _fill_batches(self) -> None:
        """Append batches until content extends ~2 viewports below the scroll.

        ``edge-reached`` alone is unreliable on this GTK3/Wayland build, so the
        scrollbar adjustment drives loading too: whenever the viewport sits near
        the bottom, one batch is added and another pass is queued for after the
        flow reflows, so the buffer check stays accurate between adds.
        """
        if self._fill_id is not None or self._cache_running:
            return
        if not self._all_images or self._loaded_count >= len(self._all_images):
            return
        v = self._vadj
        if v is None:
            return
        page = v.get_page_size()
        upper = v.get_upper()
        if page <= 0 or upper <= 0:  # not laid out yet — keep just the first batch
            return
        page = max(page, 1)
        if v.get_value() + page < upper - page * 2:
            return
        self._load_batch()
        self._fill_id = GLib.idle_add(self._fill_idle)

    def _fill_idle(self) -> bool:
        self._fill_id = None
        self._fill_batches()
        return GLib.SOURCE_REMOVE

    def _set_preview(self, path: str):
        pb = _cover_pixbuf(path, self._preview_w, self._preview_h)
        if pb is not None:
            self._current_img.set_from_pixbuf(pb)

    def _load_current(self):
        wal_file = WAL_CACHE / "wal"
        if wal_file.exists():
            wp = wal_file.read_text().strip()
            if wp and os.path.isfile(wp):
                self._set_preview(wp)
                return
        fallback = HYPRTK / "assets" / "Wallpapers" / "default.png"
        if fallback.exists():
            self._set_preview(str(fallback))

    def _load_thumbnails(self):
        self._stop_cache_build()
        _remove_all_children(self._flow)
        self._loaded_count = 0
        self._all_images = []
        self._thumb_map = {}
        if not self._wall_dir.is_dir():
            return
        index = load_index()
        if index_matches_dir(index, self._wall_dir) and self._index_thumbs_ok(index):
            self._set_index(index)
        else:
            # Build (or rebuild) the cache — including when the index belongs to
            # a different folder, or holds thumbnails at an older size.
            self._start_cache_build(force=False)

    @staticmethod
    def _index_thumbs_ok(index: list[dict]) -> bool:
        if not index:
            return False
        for e in index:
            tp = Path(e.get("thumb", ""))
            if not tp.exists():
                continue
            return _thumb_size_ok(tp)
        return False

    def _on_build_cache(self, _btn):
        if not self._cache_running:
            self._start_cache_build(force=True)

    def _start_cache_build(self, force: bool) -> None:
        if self._cache_running or not self._wall_dir.is_dir():
            return
        _remove_all_children(self._flow)
        self._loaded_count = 0
        self._all_images = []
        self._thumb_map = {}
        self._cache_gen = cache_steps(self._wall_dir, force)
        self._cache_running = True
        self._progress.set_no_show_all(False)
        self._progress.set_visible(True)
        self._progress.set_fraction(0.0)
        self._progress.set_text("Building preview cache...")
        self._cache_step_id = GLib.idle_add(self._step_cache_build)

    def _step_cache_build(self) -> bool:
        if self._closed or not self._cache_running or self._cache_gen is None:
            self._cache_running = False
            self._cache_gen = None
            return GLib.SOURCE_REMOVE
        try:
            done, total = next(self._cache_gen)
        except StopIteration:
            self._finish_cache_build()
            return GLib.SOURCE_REMOVE
        if total:
            self._progress.set_fraction(done / total)
            self._progress.set_text(f"Building preview cache... {done}/{total}")
        self._cache_step_id = GLib.idle_add(self._step_cache_build)
        return GLib.SOURCE_REMOVE

    def _finish_cache_build(self) -> None:
        self._cache_running = False
        self._cache_gen = None
        self._cache_step_id = None
        self._progress.set_visible(False)
        self._progress.set_no_show_all(True)
        # cache_steps wrote the index — now show every wallpaper from it.
        self._set_index(load_index())
        self._toast("Preview cache built")

    def _stop_cache_build(self) -> None:
        self._cache_running = False
        self._cache_gen = None
        if self._cache_step_id is not None:
            GLib.source_remove(self._cache_step_id)
            self._cache_step_id = None
        if self._progress is not None:
            self._progress.set_visible(False)
            self._progress.set_no_show_all(True)

    def _set_index(self, index: list[dict]):
        self._all_images = [Path(e["path"]) for e in index]
        self._thumb_map = {e["path"]: e["thumb"] for e in index}
        self._load_batch()
        self._fill_batches()

    def _load_batch(self):
        start = self._loaded_count
        end = min(start + _BATCH_SIZE, len(self._all_images))
        for img_path in self._all_images[start:end]:
            if not img_path.is_file():  # image deleted since the index was built
                continue
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.get_style_context().add_class("wallpaper-thumb")
            btn.set_size_request(self._preview_w, self._preview_h)
            img = Gtk.Image()
            thumb = self._thumb_map.get(str(img_path))
            if thumb and os.path.isfile(thumb):
                img.set_from_file(thumb)
            else:
                img.set_from_file(str(img_path))
            btn.add(img)
            btn.connect("clicked", self._on_thumb_click, img_path)
            self._flow.add(btn)
            # Children added after the page was shown stay hidden until shown —
            # without this only the first batch ever appeared.
            btn.show_all()
        self._loaded_count = end

    def _on_thumb_click(self, btn, path: Path):
        self._selected = path
        self._set_preview(str(path))

    def _apply_random(self, btn):
        if not self._all_images:
            return
        self._selected = random.choice(self._all_images)
        self._set_preview(str(self._selected))
        self._apply_selected(btn)

    def _on_choose_dir(self, btn):
        parent = self.get_toplevel()
        dialog = Gtk.FileChooserDialog(
            title="Select Wallpaper Directory",
            transient_for=parent if isinstance(parent, Gtk.Window) else None,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.ACCEPT)
        dialog.set_current_folder(str(self._wall_dir))
        dialog.connect("response", self._on_dir_chosen)
        dialog.show()

    def _on_dir_chosen(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            folder = Path(dialog.get_filename())
            if folder.is_dir():
                self._wall_dir = folder
                self._dir_label.set_text(str(folder))
                self._dir_label.set_tooltip_text(str(folder))
                self._cfg.setdefault("themer", {})["wallpaper_dir"] = str(folder)
                from . import config as config_module
                config_module.save(self._cfg)
                self._load_thumbnails()
        dialog.destroy()

    def _apply_selected(self, btn):
        if self._selected is None:
            self._toast("Select a wallpaper first")
            return
        script = WALLPAPER_COLORS_SH
        if not script.is_file():
            self._toast("Wallpaper script not found")
            return
        try:
            subprocess.Popen(["bash", str(script), str(self._selected)],
                             start_new_session=True)
            self._toast(f"Applied: {self._selected.name}")
        except (OSError, subprocess.SubprocessError):
            self._toast("Failed to run wallpaper script")
            return
        GLib.timeout_add(POST_ACTION_DELAY_MS, self._refresh_wallpaper)

    def _refresh_wallpaper(self):
        self._load_current()
        return GLib.SOURCE_REMOVE

    # ── pywal ─────────────────────────────────────────────────────

    def _build_pywal_page(self, box: Gtk.Box, scroller: Gtk.ScrolledWindow | None = None) -> None:
        _add_section_title(box, "Current Pywal Palette")
        self._pywal_grid = Gtk.Grid()
        self._pywal_grid.set_column_spacing(6)
        self._pywal_grid.set_row_spacing(6)
        box.pack_start(self._pywal_grid, False, False, 0)

        self._pywal_detail = Gtk.Label(label="Click a color to inspect", xalign=0)
        box.pack_start(self._pywal_detail, False, False, 0)

        _add_section_title(box, "Colorscheme Files")
        self._scheme_list = Gtk.ListBox()
        self._scheme_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._scheme_list.connect("row-activated", self._on_scheme_click)
        box.pack_start(self._scheme_list, False, False, 0)

        _add_section_title(box, "Re-run")
        rerun_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._wal_dir_label = Gtk.Label(label=str(WALLPAPER_DIRS[0]), xalign=0)
        self._wal_dir_label.set_ellipsize(3)
        rerun_box.pack_start(self._wal_dir_label, True, True, 0)
        dir_btn = Gtk.Button(label="Dir")
        dir_btn.connect("clicked", self._on_choose_wal_dir)
        rerun_box.pack_start(dir_btn, False, False, 0)
        rerun_btn = Gtk.Button(label="Re-run wal")
        rerun_btn.get_style_context().add_class("settings-apply")
        rerun_btn.connect("clicked", self._rerun_wal)
        rerun_box.pack_start(rerun_btn, False, False, 0)
        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", lambda b: self._refresh_pywal())
        rerun_box.pack_start(refresh_btn, False, False, 0)
        box.pack_start(rerun_box, False, False, 0)

        self._wal_dir = WALLPAPER_DIRS[0]
        self._refresh_pywal()

    def _refresh_pywal(self):
        colors = _parse_wal_colors()
        if colors:
            self._render_color_grid(colors)
        _remove_all_children(self._scheme_list)
        schemes_dir = WAL_CACHE / "schemes"
        if schemes_dir.exists():
            for f in sorted(schemes_dir.iterdir())[:30]:
                row = self._make_list_row(f.name)
                row._scheme_path = f
                self._scheme_list.add(row)

    def _render_color_grid(self, colors: dict[str, str]):
        _remove_all_children(self._pywal_grid)
        names = ["black", "red", "green", "yellow", "blue", "magenta", "cyan",
                 "white", "bright-black", "bright-red", "bright-green",
                 "bright-yellow", "bright-blue", "bright-magenta",
                 "bright-cyan", "bright-white"]
        for i in range(16):
            key = f"color{i}"
            hex_val = colors.get(key, "#000000")
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_size_request(48, 48)
            btn.set_tooltip_text(f"{names[i]}\n{hex_val}")
            _set_label_css(
                btn,
                f"button {{ background: {hex_val}; border-radius: 22px; "
                f"min-width: 44px; min-height: 44px; }}",
            )
            btn.connect("clicked", lambda b, n=i, k=key: self._on_color_click(n, k))
            self._pywal_grid.attach(btn, i % 8, i // 8, 1, 1)
        # Children added after the page was shown stay hidden until shown —
        # without this a refresh while the dialog is open blanks the palette.
        self._pywal_grid.show_all()

    def _on_color_click(self, index: int, key: str):
        colors = _parse_wal_colors()
        val = colors.get(key, "N/A")
        names = ["black", "red", "green", "yellow", "blue", "magenta", "cyan",
                 "white", "bright-black", "bright-red", "bright-green",
                 "bright-yellow", "bright-blue", "bright-magenta",
                 "bright-cyan", "bright-white"]
        self._pywal_detail.set_text(f"{names[index]} ({key}): {val}")

    def _on_scheme_click(self, _listbox, row):
        try:
            subprocess.Popen(["wal", "--theme", str(row._scheme_path)],
                             start_new_session=True)
            self._toast(f"Applied scheme: {row._scheme_path.name}")
            GLib.timeout_add(POST_ACTION_DELAY_MS, self._refresh_pywal_idle)
        except FileNotFoundError:
            self._toast("wal command not found")

    def _refresh_pywal_idle(self):
        self._refresh_pywal()
        return GLib.SOURCE_REMOVE

    def _on_choose_wal_dir(self, btn):
        parent = self.get_toplevel()
        dialog = Gtk.FileChooserDialog(
            title="Select Wallpaper Directory for wal",
            transient_for=parent if isinstance(parent, Gtk.Window) else None,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.ACCEPT)
        dialog.set_current_folder(str(self._wal_dir))
        dialog.connect("response", self._on_wal_dir_chosen)
        dialog.show()

    def _on_wal_dir_chosen(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            folder = Path(dialog.get_filename())
            if folder.is_dir():
                self._wal_dir = folder
                self._wal_dir_label.set_text(str(folder))
        dialog.destroy()

    def _rerun_wal(self, btn):
        try:
            subprocess.Popen(["wal", "-i", str(self._wal_dir)],
                             start_new_session=True)
            self._toast("Re-running wal")
            GLib.timeout_add(POST_ACTION_DELAY_MS, self._refresh_pywal_idle)
        except FileNotFoundError:
            self._toast("wal command not found")

    # ── rofi ──────────────────────────────────────────────────────

    def _build_rofi_page(self, box: Gtk.Box, scroller: Gtk.ScrolledWindow | None = None) -> None:
        self._rofi_active = Gtk.Label(label="Active variant: ...", xalign=0)
        self._rofi_active.get_style_context().add_class("mc-page-title")
        box.pack_start(self._rofi_active, False, False, 0)

        self._variant_list = Gtk.ListBox()
        self._variant_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._variant_list.connect("row-activated", self._on_variant_click)
        box.pack_start(self._variant_list, True, True, 0)

        regen_btn = Gtk.Button(label="Regenerate from Pywal")
        regen_btn.connect("clicked", self._on_rofi_regenerate)
        box.pack_start(regen_btn, False, False, 0)

        self._refresh_rofi()

    def _refresh_rofi(self):
        link = ROFI_VARIANT_LINK
        if link.is_symlink():
            name = Path(os.readlink(str(link))).stem
            self._rofi_active.set_text(f"Active variant: {name}")
        else:
            self._rofi_active.set_text("Active variant: (none)")

        _remove_all_children(self._variant_list)
        if not ROFI_VARIANTS.exists():
            return
        for f in sorted(ROFI_VARIANTS.glob("*.rasi")):
            suffix = None
            if link.is_symlink() and os.readlink(str(link)) == str(f):
                suffix = self._active_badge()
            row = self._make_list_row(f.stem, suffix)
            row._variant_path = f
            self._variant_list.add(row)

    def _on_variant_click(self, _listbox, row):
        variant_path = row._variant_path
        ROFI_VARIANT_LINK.unlink(missing_ok=True)
        os.symlink(str(variant_path), str(ROFI_VARIANT_LINK))
        self._run_script(SYNC_ROFI_SH, "rofi sync")
        self._refresh_rofi()
        self._toast(f"Rofi variant: {variant_path.stem}")

    def _on_rofi_regenerate(self, btn):
        self._run_script(SYNC_ROFI_SH, "rofi sync")
        self._refresh_rofi()
        self._toast("Regenerated rofi variant from pywal")

    def _run_script(self, script_path: Path, label: str):
        if not script_path.is_file():
            self._toast(f"{label} script not found")
            return
        try:
            subprocess.Popen(["bash", str(script_path)], start_new_session=True)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("%s failed: %s", label, exc)
            self._toast(f"Failed to run {label}")

    # ── bar themes ────────────────────────────────────────────────

    def _build_bar_page(self, box: Gtk.Box, scroller: Gtk.ScrolledWindow | None = None) -> None:
        self._bar_ready = False

        self._bar_active = Gtk.Label(label="Active theme: ...", xalign=0)
        self._bar_active.get_style_context().add_class("mc-page-title")
        box.pack_start(self._bar_active, False, False, 0)

        _add_section_title(box, "Source")
        self._bar_source_buttons = _radio_group([
            ("pywal", "Pywal (dynamic)"),
            ("imported", "Imported theme"),
            ("manual", "Manual (config)"),
        ])
        source_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for btn in self._bar_source_buttons.values():
            btn.connect("toggled", self._on_bar_source_toggled)
            source_box.pack_start(btn, False, False, 0)
        box.pack_start(source_box, False, False, 0)

        _add_section_title(box, "Imported theme")
        self._bar_theme_buttons: dict[str, Gtk.CheckButton] = {}
        themes_scroller = Gtk.ScrolledWindow()
        themes_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        themes_scroller.set_min_content_height(120)
        themes_scroller.set_vexpand(True)
        self._bar_themes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        themes_scroller.add(self._bar_themes_box)
        box.pack_start(themes_scroller, True, True, 0)

        import_btn = Gtk.Button(label="Import theme…")
        import_btn.connect("clicked", self._on_bar_import)
        box.pack_start(import_btn, False, False, 0)

        restart_btn = Gtk.Button(label="Restart Bar")
        restart_btn.connect("clicked", self._on_restart_bar)
        box.pack_start(restart_btn, False, False, 0)

        self._refresh_bar_themes()
        self._bar_ready = True

    def _refresh_bar_themes(self):
        theme = self._cfg.get("theme") or {}
        source = theme.get("source", "pywal")
        if source not in self._bar_source_buttons:
            source = "pywal"
        name = theme.get("theme_name") or ""

        for key, btn in self._bar_source_buttons.items():
            btn.handler_block_by_func(self._on_bar_source_toggled)
            btn.set_active(key == source)
            btn.handler_unblock_by_func(self._on_bar_source_toggled)

        for child in self._bar_themes_box.get_children():
            self._bar_themes_box.remove(child)
            child.destroy()
        self._bar_theme_buttons = {}
        themes = list_themes()
        if not themes:
            lbl = Gtk.Label(label="No themes imported yet — use Import…", xalign=0)
            lbl.set_opacity(0.7)
            self._bar_themes_box.pack_start(lbl, False, False, 0)
        else:
            for tname in themes:
                btn = Gtk.CheckButton(label=tname)
                btn.set_active(source == "imported" and Path(name).name == tname)
                btn.connect("toggled", self._on_bar_theme_toggled, tname)
                self._bar_theme_buttons[tname] = btn
                self._bar_themes_box.pack_start(btn, False, False, 0)
        self._bar_themes_box.show_all()
        self._update_bar_theme_state()

    def _update_bar_theme_state(self):
        source = self._active_bar_source()
        for btn in self._bar_theme_buttons.values():
            btn.set_sensitive(source == "imported")
        name = self._selected_bar_theme()
        if source == "imported" and name:
            self._bar_active.set_text(f"Active theme: {name}")
        elif source == "pywal":
            self._bar_active.set_text("Active theme: pywal (dynamic)")
        elif source == "manual":
            self._bar_active.set_text("Active theme: manual (config)")
        else:
            self._bar_active.set_text("Active theme: none")

    def _active_bar_source(self) -> str:
        for key, btn in self._bar_source_buttons.items():
            if btn.get_active():
                return key
        return "pywal"

    def _selected_bar_theme(self) -> str:
        for name, btn in self._bar_theme_buttons.items():
            if btn.get_active():
                return name
        return ""

    def _on_bar_source_toggled(self, btn, *_args):
        if not btn.get_active():
            return
        self._update_bar_theme_state()
        if self._bar_ready:
            self._apply_bar_theme(self._active_bar_source(), self._selected_bar_theme())

    def _on_bar_theme_toggled(self, btn: Gtk.CheckButton, name: str):
        if not btn.get_active():
            return
        for other in self._bar_theme_buttons.values():
            if other is not btn:
                other.handler_block_by_func(self._on_bar_theme_toggled)
                other.set_active(False)
                other.handler_unblock_by_func(self._on_bar_theme_toggled)
        self._update_bar_theme_state()
        if self._bar_ready:
            self._apply_bar_theme("imported", name)

    def _apply_bar_theme(self, source: str, theme_name: str):
        msg = f"Bar theme: {source}"
        if source == "imported" and theme_name:
            msg += f" / {theme_name}"
        if self._theme_cb is not None:
            # Live apply — the bar re-themes without closing/reopening.
            self._theme_cb(
                source, theme_name if (source == "imported" and theme_name) else ""
            )
            self._toast(msg)
            return
        # Fallback (no live callback): write the config and restart the bar.
        try:
            cfg = json.loads(BAR_CONFIG.read_text())
        except (OSError, json.JSONDecodeError):
            cfg = {}
        cfg.setdefault("theme", {})
        cfg["theme"]["source"] = source
        if source == "imported" and theme_name:
            cfg["theme"]["theme_name"] = theme_name
        try:
            BAR_CONFIG.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(BAR_CONFIG, json.dumps(cfg, indent=2) + "\n")
        except OSError as exc:
            log.warning("Failed to write bar config: %s", exc)
            self._toast("Failed to write bar config")
            return
        self._toast(msg)
        self._restart_bar()

    def _on_bar_import(self, *_args):
        parent = self.get_toplevel()
        chooser = Gtk.FileChooserNative.new(
            "Import theme folder",
            parent if isinstance(parent, Gtk.Window) else None,
            Gtk.FileChooserAction.SELECT_FOLDER,
            "Import",
            "Cancel",
        )
        chooser.set_current_folder(str(Path.home()))

        def on_response(dialog: Gtk.FileChooserNative, response) -> None:
            if response == Gtk.ResponseType.ACCEPT:
                folder = dialog.get_file()
                if folder is not None:
                    name = import_theme(folder.get_path())
                    if name:
                        self._bar_ready = True
                        for key, btn in self._bar_source_buttons.items():
                            btn.handler_block_by_func(self._on_bar_source_toggled)
                            btn.set_active(key == "imported")
                            btn.handler_unblock_by_func(self._on_bar_source_toggled)
                        self._refresh_bar_themes()
                        self._update_bar_theme_state()
                        self._apply_bar_theme("imported", name)
                    else:
                        self._toast("Not a valid theme folder")
            dialog.destroy()

        chooser.connect("response", on_response)
        chooser.show()

    def _on_restart_bar(self, btn=None):
        self._restart_bar()

    def _restart_bar(self):
        if self._restart_cb is not None:
            self._restart_cb()
        else:
            self._toast("Bar restart unavailable")

    # ── matuwall ──────────────────────────────────────────────────

    def _build_matuwall_page(self, box: Gtk.Box, scroller: Gtk.ScrolledWindow | None = None) -> None:
        self._mw_config: dict = {}
        _add_section_title(box, "Matuwall Configuration")
        self._mw_entries: dict[str, Gtk.Entry] = {}
        self._mw_switches: dict[str, Gtk.Switch] = {}
        for key, label in (
            ("wallpaper_dir", "Wallpaper Directory"),
            ("thumbnail_size", "Thumbnail Size"),
            ("batch_size", "Batch Size"),
        ):
            self._mw_entries[key] = _add_entry_row(box, label)
        self._mw_switches["mouse_enabled"] = _add_switch_row(box, "Mouse Enabled")
        self._mw_switches["keep_ui_alive"] = _add_switch_row(box, "Keep UI Alive")

        _add_section_title(box, "Wall Mode")
        self._mw_switches["wall_mode_only"] = _add_switch_row(box, "Wall Mode Only")
        self._mw_entries["wall_awww_flags"] = _add_entry_row(box, "Awww Transition Flags")

        _add_section_title(box, "Panel Mode")
        self._mw_switches["panel_mode"] = _add_switch_row(box, "Panel Mode")
        self._mw_entries["panel_edge"] = _add_entry_row(box, "Panel Edge")
        self._mw_entries["panel_exclusive_zone"] = _add_entry_row(box, "Exclusive Zone")

        save_btn = Gtk.Button(label="Save Configuration")
        save_btn.get_style_context().add_class("settings-apply")
        save_btn.connect("clicked", self._save_matuwall)
        box.pack_start(save_btn, False, False, 0)

        self._load_matuwall()

    def _load_matuwall(self):
        if MATUWALL_CONFIG.exists():
            try:
                cfg = json.loads(MATUWALL_CONFIG.read_text())
            except (json.JSONDecodeError, OSError):
                cfg = {}
        else:
            cfg = {}
        self._mw_config = cfg
        for section in cfg.values():
            if not isinstance(section, dict):
                continue
            for key, val in section.items():
                if key in self._mw_entries:
                    self._mw_entries[key].set_text(str(val))
                if key in self._mw_switches:
                    self._mw_switches[key].set_active(bool(val))

    def _save_matuwall(self, btn=None):
        cfg = self._mw_config
        for key, entry in self._mw_entries.items():
            val = entry.get_text()
            for section in cfg.values():
                if isinstance(section, dict) and key in section:
                    orig = section[key]
                    if isinstance(orig, int):
                        try:
                            section[key] = int(val)
                        except ValueError:
                            pass
                    elif isinstance(orig, bool):
                        pass
                    else:
                        section[key] = val
        for key, switch in self._mw_switches.items():
            for section in cfg.values():
                if isinstance(section, dict) and key in section:
                    section[key] = switch.get_active()
        try:
            _atomic_write(MATUWALL_CONFIG, json.dumps(cfg, indent=2))
            self._toast("Matuwall config saved")
        except OSError as exc:
            self._toast(f"Save failed: {exc}")

    # ── swaylock ──────────────────────────────────────────────────

    def _build_swaylock_page(self, box: Gtk.Box, scroller: Gtk.ScrolledWindow | None = None) -> None:
        _add_section_title(box, "Pywal Mode")
        desc = Gtk.Label(
            label="Copy pywal-generated colors to swaylock config. This syncs "
                  "the lock screen with your current wallpaper palette.",
            xalign=0, wrap=True,
        )
        box.pack_start(desc, False, False, 0)
        apply_wal_btn = Gtk.Button(label="Apply Pywal Colors")
        apply_wal_btn.get_style_context().add_class("settings-apply")
        apply_wal_btn.connect("clicked", self._apply_swaylock_pywal)
        box.pack_start(apply_wal_btn, False, False, 0)

        _add_section_title(box, "Manual Color Editor")
        load_btn = Gtk.Button(label="Load Current Pywal Colors")
        load_btn.connect("clicked", self._load_swaylock_pywal)
        box.pack_start(load_btn, False, False, 0)

        manual_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self._preview = SwaylockPreview()
        manual_row.pack_start(self._preview, False, False, 0)

        self._color_buttons: dict[str, ColorButton] = {}
        fields = [
            ("ring-color", "Ring (idle)"),
            ("ring-clear-color", "Ring (clear)"),
            ("ring-wrong-color", "Ring (wrong)"),
            ("ring-ver-color", "Ring (verifying)"),
            ("ring-caps-lock-color", "Ring (caps lock)"),
            ("inside-color", "Inside (idle)"),
            ("inside-clear-color", "Inside (clear)"),
            ("inside-wrong-color", "Inside (wrong)"),
            ("inside-ver-color", "Inside (verifying)"),
            ("key-hl-color", "Key highlight"),
            ("text-color", "Text"),
            ("bs-hl-color", "Backspace highlight"),
        ]
        mid = len(fields) // 2
        for group in (fields[:mid], fields[mid:]):
            grid = Gtk.Grid()
            grid.set_column_spacing(10)
            grid.set_row_spacing(6)
            for i, (key, label) in enumerate(group):
                lbl = Gtk.Label(label=label, xalign=0)
                lbl.set_size_request(130, -1)
                grid.attach(lbl, 0, i, 1, 1)
                cb = ColorButton()
                cb.connect_color_changed(lambda c, k=key: self._on_swaylock_color(k, c))
                self._color_buttons[key] = cb
                grid.attach(cb, 1, i, 1, 1)
            manual_row.pack_start(grid, False, False, 0)

        box.pack_start(manual_row, False, False, 0)

        save_btn = Gtk.Button(label="Save Manual Config")
        save_btn.connect("clicked", self._save_swaylock_manual)
        box.pack_start(save_btn, False, False, 0)

        _add_section_title(box, "Indicator Settings")
        self._sl_radius = _add_entry_row(box, "Indicator Radius")
        self._sl_thickness = _add_entry_row(box, "Indicator Thickness")
        self._sl_fade = _add_entry_row(box, "Fade-in (seconds)")
        self._sl_effect = _add_entry_row(box, "Effect (e.g. effect-pixelate=5)")
        save_settings_btn = Gtk.Button(label="Save Settings")
        save_settings_btn.connect("clicked", self._save_swaylock_settings)
        box.pack_start(save_settings_btn, False, False, 0)

        self._load_swaylock()

    def _load_swaylock(self):
        config = _read_swaylock_config()
        wal_colors = _read_wal_hex()
        if len(wal_colors) >= 8:
            wal_map = {
                "ring-color": wal_colors[6],
                "ring-clear-color": wal_colors[4],
                "ring-wrong-color": wal_colors[1],
                "ring-ver-color": wal_colors[5],
                "ring-caps-lock-color": wal_colors[5],
                "inside-color": wal_colors[0],
                "inside-clear-color": wal_colors[4],
                "inside-wrong-color": wal_colors[1],
                "inside-ver-color": wal_colors[5],
                "key-hl-color": wal_colors[6],
                "text-color": wal_colors[7],
                "bs-hl-color": wal_colors[1],
            }
            config.update(wal_map)
        preview_colors = {}
        for key, cb in self._color_buttons.items():
            val = config.get(key, "#ffffff")
            if not val.startswith("#"):
                val = f"#{val}"
            cb.set_color(val)
            preview_colors[key] = val
        self._preview.update_colors(preview_colors)

        self._sl_radius.set_text(config.get("indicator-radius", "200"))
        self._sl_thickness.set_text(config.get("indicator-thickness", "20"))
        self._sl_fade.set_text(config.get("fade-in", "1"))
        try:
            r = int(config.get("indicator-radius", "200"))
        except ValueError:
            r = 200
        try:
            t = int(config.get("indicator-thickness", "20"))
        except ValueError:
            t = 20
        self._preview.set_dimensions(r, t)
        for key in config:
            if key.startswith("effect-"):
                self._sl_effect.set_text(f"{key}={config[key]}")
                break

    def _on_swaylock_color(self, key: str, hex_val: str):
        self._preview.update_colors({key: hex_val})

    def _load_swaylock_pywal(self, btn):
        wal_colors = _read_wal_hex()
        if len(wal_colors) < 8:
            self._toast("Pywal colors file incomplete")
            return
        wal_map = {
            "ring-color": wal_colors[6],
            "ring-clear-color": wal_colors[4],
            "ring-wrong-color": wal_colors[1],
            "ring-ver-color": wal_colors[5],
            "ring-caps-lock-color": wal_colors[5],
            "inside-color": wal_colors[0],
            "inside-clear-color": wal_colors[4],
            "inside-wrong-color": wal_colors[1],
            "inside-ver-color": wal_colors[5],
            "key-hl-color": wal_colors[6],
            "text-color": wal_colors[7],
            "bs-hl-color": wal_colors[1],
        }
        preview_colors = {}
        for key, cb in self._color_buttons.items():
            val = wal_map.get(key, "#ffffff")
            cb.set_color(f"#{val}")
            preview_colors[key] = f"#{val}"
        self._preview.update_colors(preview_colors)
        self._toast("Loaded pywal colors")

    def _apply_swaylock_pywal(self, btn):
        wal_colors = _read_wal_hex()
        if len(wal_colors) < 8:
            self._toast("Pywal colors file incomplete")
            return
        color_mapping = [
            ("ring-color", 6, False), ("ring-clear-color", 4, False),
            ("ring-wrong-color", 1, False), ("ring-ver-color", 5, False),
            ("ring-caps-lock-color", 5, False),
            ("inside-color", 0, True), ("inside-clear-color", 4, True),
            ("inside-wrong-color", 1, True), ("inside-ver-color", 5, True),
            ("inside-caps-lock-color", 5, True),
            ("key-hl-color", 6, True),
            ("text-color", 7, False), ("text-clear-color", 4, False),
            ("text-ver-color", 5, False), ("text-wrong-color", 1, False),
            ("bs-hl-color", 1, False),
            ("line-color", 6, True), ("line-clear-color", 4, True),
            ("line-wrong-color", 1, True), ("line-ver-color", 5, True),
            ("line-caps-lock-color", 5, True),
            ("caps-lock-key-hl-color", 5, True),
            ("caps-lock-bs-hl-color", 5, True),
            ("text-caps-lock-color", 5, False),
        ]
        replacements = {}
        for key, idx, keep_alpha in color_mapping:
            new_color = wal_colors[idx]
            replacements[key] = f"{new_color}44" if keep_alpha else new_color

        template = WAL_CACHE / "colors-swaylock.conf"
        if not template.exists():
            self._toast("No swaylock template found")
            return
        new_lines = []
        for line in template.read_text().splitlines():
            stripped = line.strip()
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in replacements:
                    new_lines.append(f"{key}={replacements[key]}")
                    continue
            new_lines.append(line)
        SWAYLOCK_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(SWAYLOCK_CONFIG, "\n".join(new_lines) + "\n")
        self._load_swaylock()
        self._toast("Swaylock colors applied and saved")

    def _save_swaylock_manual(self, btn):
        config = _read_swaylock_config()
        for key, cb in self._color_buttons.items():
            config[key] = cb.get_color().lstrip("#")
        _write_swaylock_config(config)
        self._toast("Swaylock colors saved")

    def _save_swaylock_settings(self, btn):
        config = _read_swaylock_config()
        config["indicator-radius"] = self._sl_radius.get_text()
        config["indicator-thickness"] = self._sl_thickness.get_text()
        config["fade-in"] = self._sl_fade.get_text()
        for key in list(config.keys()):
            if key.startswith("effect-"):
                del config[key]
        effect = self._sl_effect.get_text().strip()
        if "=" in effect:
            k, _, v = effect.partition("=")
            config[k] = v
        _write_swaylock_config(config)
        self._toast("Swaylock settings saved")

    # ── icons ─────────────────────────────────────────────────────

    def _build_icons_page(self, box: Gtk.Box, scroller: Gtk.ScrolledWindow | None = None) -> None:
        _add_section_title(box, "Current Folder Icons")
        self._icon_preview_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                         spacing=8)
        self._icon_preview_box.set_halign(Gtk.Align.START)
        box.pack_start(self._icon_preview_box, False, False, 0)
        self._icon_color_label = Gtk.Label(label="", xalign=0)
        box.pack_start(self._icon_color_label, False, False, 0)

        _add_section_title(box, "Pywal Auto-Color")
        desc = Gtk.Label(
            label="Automatically match papirus folder color to pywal color4. "
                  "Uses Euclidean distance to find the closest preset.",
            xalign=0, wrap=True,
        )
        box.pack_start(desc, False, False, 0)
        auto_btn = Gtk.Button(label="Apply Pywal Color Match")
        auto_btn.get_style_context().add_class("settings-apply")
        auto_btn.connect("clicked", self._apply_icon_auto)
        box.pack_start(auto_btn, False, False, 0)

        _add_section_title(box, "Manual Folder Color")
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        self._icon_presets = []
        for i, (display_name, papirus_color) in enumerate(_COLOR_PRESETS):
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_tooltip_text(papirus_color)
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            icon_pb = _fit_pixbuf(
                str(ICON_THEME_DIR / f"folder-{papirus_color}.svg"), 20, 20
            )
            if icon_pb is not None:
                img = Gtk.Image.new_from_pixbuf(icon_pb)
                content.pack_start(img, False, False, 0)
            lbl = Gtk.Label(label=display_name, xalign=0)
            content.pack_start(lbl, False, False, 0)
            btn.add(content)
            btn.connect("clicked", lambda b, c=papirus_color: self._apply_icon_preset(c))
            grid.attach(btn, i % 4, i // 4, 1, 1)
            self._icon_presets.append(btn)
        box.pack_start(grid, False, False, 0)

        _add_section_title(box, "Custom Hex")
        custom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._icon_custom = Gtk.Entry()
        self._icon_custom.set_text("#2196F3")
        custom_row.pack_start(self._icon_custom, True, True, 0)
        apply_custom_btn = Gtk.Button(label="Apply")
        apply_custom_btn.connect("clicked", self._apply_icon_custom)
        custom_row.pack_start(apply_custom_btn, False, False, 0)
        box.pack_start(custom_row, False, False, 0)

        self._refresh_icons()

    def _refresh_icons(self):
        color = _detect_icon_color()
        self._icon_color_label.set_text(f"Current color: {color or 'unknown'}")
        _remove_all_children(self._icon_preview_box)
        if not ICON_THEME_DIR.exists():
            lbl = Gtk.Label(label="(icon theme not found)")
            self._icon_preview_box.pack_start(lbl, False, False, 0)
            return
        for icon_template, label_text in _PREVIEW_ICONS:
            icon_path = ICON_THEME_DIR / icon_template.replace("{color}", color)
            if not icon_path.exists():
                icon_path = ICON_THEME_DIR / icon_template.replace(f"-{color}", "")
            if not icon_path.exists():
                continue
            item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            item.set_halign(Gtk.Align.CENTER)
            img = Gtk.Image.new_from_file(str(icon_path))
            img.set_pixel_size(40)
            item.pack_start(img, False, False, 0)
            lbl = Gtk.Label(label=label_text)
            item.pack_start(lbl, False, False, 0)
            self._icon_preview_box.pack_start(item, False, False, 0)

    def _apply_icon_auto(self, btn):
        if not CHANGE_ICONS_SH.is_file():
            self._toast("change-icons.sh not found")
            return
        try:
            subprocess.Popen(["bash", str(CHANGE_ICONS_SH)], start_new_session=True)
            GLib.timeout_add(POST_ACTION_DELAY_MS, self._post_icon_change)
            self._toast("Applying pywal folder color match")
        except FileNotFoundError:
            self._toast("Failed to run icon script")

    def _apply_icon_preset(self, color_name: str):
        if _run_papirus_folders("-C", color_name, "-t", "Papirus-Dark"):
            GLib.timeout_add(POST_ACTION_DELAY_MS, self._post_icon_change)
            self._toast(f"Folder color: {color_name}")
        else:
            self._toast("papirus-folders not found")

    def _apply_icon_custom(self, btn):
        hex_val = self._icon_custom.get_text().strip()
        if not hex_val.startswith("#"):
            hex_val = f"#{hex_val}"
        if len(hex_val) != 7:
            self._toast("Invalid hex color (use #RRGGBB)")
            return
        if _run_papirus_folders("-C", hex_val.lstrip("#"), "--theme", "Papirus-Dark"):
            GLib.timeout_add(POST_ACTION_DELAY_MS, self._post_icon_change)
            self._toast(f"Folder color: {hex_val}")
        else:
            self._toast("papirus-folders not found")

    def _post_icon_change(self):
        self._update_icon_cache()
        self._refresh_icons()
        return GLib.SOURCE_REMOVE

    def _update_icon_cache(self):
        def _do():
            for theme_dir in ICON_CACHE_THEME_DIRS:
                if theme_dir.exists():
                    try:
                        subprocess.run(
                            ["gtk-update-icon-cache", "-qf", str(theme_dir)],
                            capture_output=True, timeout=30,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            return GLib.SOURCE_REMOVE
        GLib.idle_add(_do)

    # ── sddm ──────────────────────────────────────────────────────

    def _build_sddm_page(self, box: Gtk.Box, scroller: Gtk.ScrolledWindow | None = None) -> None:
        info = Gtk.Label(
            label="Update the login screen (SDDM) and bootloader (GRUB) with "
                  "your current wallpaper.",
            xalign=0, wrap=True,
        )
        box.pack_start(info, False, False, 0)

        self._sddm_wallpaper_path = HOME / ".cache" / "current-wallpaper.png"
        self._sddm_preview_img = Gtk.Image()
        self._sddm_preview_img.set_halign(Gtk.Align.CENTER)
        box.pack_start(self._sddm_preview_img, False, False, 0)
        self._refresh_sddm_preview()

        update_btn = Gtk.Button(label="Update SDDM & GRUB Wallpaper")
        update_btn.get_style_context().add_class("settings-apply")
        update_btn.connect("clicked", self._on_sddm_update)
        box.pack_start(update_btn, False, False, 0)

        self._sddm_status = Gtk.Label(label="", xalign=0)
        box.pack_start(self._sddm_status, False, False, 0)

    def _refresh_sddm_preview(self) -> None:
        """Sync current-wallpaper.png with the live wallpaper and re-render.

        The preview (and the SDDM/GRUB update) reads ~/.cache/current-wallpaper.png,
        which is only refreshed by the wal scripts — when the wallpaper changed
        through another path it can be stale. Derive the source from pywal's
        cache (~/.cache/wal/wal) and re-render the thumbnail.
        """
        import shutil

        current = WAL_CACHE / "wal"
        if current.exists():
            src = current.read_text().strip()
            if src and os.path.isfile(src):
                try:
                    shutil.copy2(src, self._sddm_wallpaper_path)
                except OSError:
                    pass
        if not self._sddm_wallpaper_path.exists():
            self._sddm_preview_img.set_from_pixbuf(None)
            return
        pb = _fit_pixbuf(
            str(self._sddm_wallpaper_path),
            _SDDM_PREVIEW[0], _SDDM_PREVIEW[1],
        )
        if pb is not None:
            self._sddm_preview_img.set_from_pixbuf(pb)
            self._sddm_preview_img.set_size_request(pb.get_width(), pb.get_height())

    def _on_sddm_update(self, btn):
        if not SDDM_UPDATE_SH.is_file():
            self._toast("update.sh not found")
            return
        # Ensure the file reflects the current wallpaper before copying it.
        self._refresh_sddm_preview()
        if not self._sddm_wallpaper_path.exists():
            self._toast("No current wallpaper found")
            return
        self._sddm_status.set_text("Updating SDDM & GRUB...")
        btn.set_sensitive(False)

        def _run():
            try:
                proc = subprocess.run(
                    ["pkexec", "env", f"HOME={HOME}", "bash", str(SDDM_UPDATE_SH), "-y"],
                    capture_output=True, text=True, timeout=120,
                )
                ok = proc.returncode == 0
                err = proc.stderr[:200] if not ok else ""
            except subprocess.TimeoutExpired:
                ok, err = False, "update timed out"
            except Exception as exc:
                log.warning("SDDM/GRUB update failed: %s", exc)
                ok, err = False, str(exc)
            GLib.idle_add(self._sddm_done, btn, ok, err)

        # Run off the GTK thread — pkexec shows a polkit dialog and update.sh can
        # take a while; blocking here would freeze the whole bar.
        threading.Thread(target=_run, daemon=True).start()

    def _sddm_done(self, btn, ok: bool, err: str):
        if ok:
            self._sddm_status.set_text("Done! Reboot to test.")
            self._toast("SDDM & GRUB updated")
        else:
            self._sddm_status.set_text(f"Error: {err}")
            self._toast("Update failed")
        btn.set_sensitive(True)

    # ── helpers ───────────────────────────────────────────────────

    def _make_list_row(self, title: str, suffix: Gtk.Widget | None = None) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("settings-row")
        row.set_activatable(True)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label=title, xalign=0)
        label.set_ellipsize(3)
        box.pack_start(label, True, True, 0)
        if suffix is not None:
            box.pack_start(suffix, False, False, 0)
        row.add(box)
        return row

    def _active_badge(self) -> Gtk.Label:
        badge = Gtk.Label(label="Active")
        badge.get_style_context().add_class("settings-value")
        return badge

    def hide_popup(self) -> None:
        if self._status_id is not None:
            GLib.source_remove(self._status_id)
            self._status_id = None
        super().hide_popup()


class SwaylockPreview(Gtk.DrawingArea):
    """Live preview of the swaylock indicator wheel using Cairo."""

    def __init__(self):
        super().__init__()
        self.set_size_request(200, 200)
        self.set_vexpand(False)
        self.set_halign(Gtk.Align.CENTER)
        self._colors = {
            "ring-color": "#ffffff",
            "inside-color": "#000000",
            "key-hl-color": "#22d3ee",
            "text-color": "#ffffff",
            "bs-hl-color": "#ff0000",
        }
        self._indicator_radius = 100
        self._indicator_thickness = 18
        self.connect("draw", self._draw)

    def update_colors(self, colors: dict[str, str]):
        self._colors.update(colors)
        self.queue_draw()

    def set_dimensions(self, radius: int, thickness: int):
        self._indicator_radius = radius
        self._indicator_thickness = thickness
        self.queue_draw()

    def _draw(self, _area, cr):
        import cairo

        width, height = self.get_allocated_width(), self.get_allocated_height()
        cx, cy = width / 2, height / 2
        radius = min(self._indicator_radius, min(width, height) / 2 - 8)

        r, g, b = _hex_to_rgb(self._colors.get("ring-color", "#ffffff"))
        cr.set_source_rgb(r / 255, g / 255, b / 255)
        cr.arc(cx, cy, radius, 0, 2 * 3.14159)
        cr.set_line_width(self._indicator_thickness * 0.9)
        cr.stroke()

        r, g, b = _hex_to_rgb(self._colors.get("inside-color", "#000000"))
        cr.set_source_rgb(r / 255, g / 255, b / 255)
        cr.arc(cx, cy, radius * 0.72, 0, 2 * 3.14159)
        cr.fill()

        dot_r = radius * 0.08
        r, g, b = _hex_to_rgb(self._colors.get("key-hl-color", "#22d3ee"))
        cr.set_source_rgb(r / 255, g / 255, b / 255)
        cr.arc(cx, cy - radius * 0.91, dot_r, 0, 2 * 3.14159)
        cr.fill()

        r, g, b = _hex_to_rgb(self._colors.get("bs-hl-color", "#ff0000"))
        cr.set_source_rgb(r / 255, g / 255, b / 255)
        cr.arc(cx, cy + radius * 0.91, dot_r, 0, 2 * 3.14159)
        cr.fill()

        r, g, b = _hex_to_rgb(self._colors.get("text-color", "#ffffff"))
        cr.set_source_rgb(r / 255, g / 255, b / 255)
        cr.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(radius * 0.35)
        ext = cr.text_extents("Password")
        cr.move_to(cx - ext.width / 2, cy + ext.height / 3)
        cr.show_text("Password")


# ── icon helpers (ported from theme-gui) ──────────────────────────────────

_PREVIEW_ICONS = [
    ("folder-{color}-desktop.svg", "Desktop"),
    ("folder-{color}-documents.svg", "Documents"),
    ("folder-{color}-downloads.svg", "Downloads"),
    ("folder-{color}-music.svg", "Music"),
    ("folder-{color}-pictures.svg", "Pictures"),
    ("folder-{color}-projects.svg", "Projects"),
    ("folder-{color}-videos.svg", "Videos"),
]

_COLOR_PRESETS = [
    ("hyprtk-adwaita", "adwaita"), ("hyprtk-black", "black"),
    ("hyprtk-blue", "blue"), ("hyprtk-bluegrey", "bluegrey"),
    ("hyprtk-breeze", "breeze"), ("hyprtk-brown", "brown"),
    ("hyprtk-carmine", "carmine"), ("hyprtk-cyan", "cyan"),
    ("hyprtk-darkcyan", "darkcyan"), ("hyprtk-deeporange", "deeporange"),
    ("hyprtk-green", "green"), ("hyprtk-grey", "grey"),
    ("hyprtk-indigo", "indigo"), ("hyprtk-magenta", "magenta"),
    ("hyprtk-nordic", "nordic"), ("hyprtk-orange", "orange"),
    ("hyprtk-palebrown", "palebrown"), ("hyprtk-paleorange", "paleorange"),
    ("hyprtk-pink", "pink"), ("hyprtk-red", "red"),
    ("hyprtk-teal", "teal"), ("hyprtk-violet", "violet"),
    ("hyprtk-white", "white"), ("hyprtk-yaru", "yaru"),
    ("hyprtk-yellow", "yellow"),
]


def _detect_icon_color() -> str:
    if not ICON_THEME_DIR.exists():
        return ""
    folder_svg = ICON_THEME_DIR / "folder.svg"
    if folder_svg.is_symlink():
        target = os.readlink(str(folder_svg))
        return Path(target).stem.replace("folder-", "")
    for _display_name, papirus_color in _COLOR_PRESETS:
        if (ICON_THEME_DIR / f"folder-{papirus_color}-pictures.svg").exists():
            return papirus_color
    return ""


def _run_papirus_folders(*args: str) -> bool:
    try:
        if PAPIRUS_FOLDERS_SH.is_file():
            subprocess.Popen(["bash", str(PAPIRUS_FOLDERS_SH), *args],
                             start_new_session=True)
        elif PAPIRUS_FOLDERS.is_file():
            subprocess.Popen([str(PAPIRUS_FOLDERS), *args],
                             start_new_session=True)
        else:
            return False
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("papirus-folders failed: %s", exc)
        return False


def _read_wal_hex() -> list[str]:
    """Return the 16 pywal colors (no '#') from ~/.cache/wal/colors."""
    src = WAL_CACHE / "colors"
    if not src.exists():
        return []
    result = []
    for line in src.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") and len(line) == 7:
            result.append(line[1:].upper())
    return result