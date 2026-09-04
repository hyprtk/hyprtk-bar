"""The bar: a horizontal taskbar with left/center/right module sections.

Layout (inside the transparent layer-shell surface):

    [ left spacer ][ pill (left | centered | right sections) ]

The pill carries the background/rounded corners and is composed of three
sections (left/center/right) populated from the config's ``layout``.
"""
from __future__ import annotations

import logging

import gi
gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk  # noqa: E402

from . import config as config_module  # noqa: E402
from .clock import Clock  # noqa: E402
from .config import DEFAULT_LAYOUT  # noqa: E402
from .layout import SECTION_ORDER, SectionBox  # noqa: E402
from .notifications import NotificationCenterButton  # noqa: E402
from .quicksettings import QuickSettingsButton  # noqa: E402
from .sysmon import SysMon  # noqa: E402
from .tasklist import TaskList  # noqa: E402
from .tray import Tray, TrayController  # noqa: E402
from .widgets import HoverButton  # noqa: E402
from .window import Window  # noqa: E402
from .workspaces import Workspaces  # noqa: E402

log = logging.getLogger("hyprtk_bar.bar")


class StartButton(HoverButton):
    def __init__(self, cfg: dict, ipc):
        super().__init__("task-button start", vertical=True, spacing=2)
        center = cfg.get("center") or {}
        self._ipc = ipc
        self._command = center.get("start_command", "hyprtk-menu")
        icon = Gtk.Image.new_from_icon_name(
            center.get("start_icon", "go-home-symbolic"), Gtk.IconSize.INVALID
        )
        icon.set_pixel_size(22)
        self.box.pack_start(icon, True, True, 0)
        # Keep the start icon clear of the bar's left edge, with the same
        # breathing room as the spacing between the other modules.
        self.set_margin_start(6)

    def _on_button_press(self, _widget, event):
        if event.button == 1:
            try:
                GLib.spawn_command_line_async(self._command)
            except GLib.Error as exc:
                log.warning("Failed to launch start menu %r: %s", self._command, exc)
        return True


class Bar(Gtk.Box):
    def __init__(self, cfg: dict, ipc, is_primary: bool = True, notif_ctrl=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self._cfg = cfg
        self._ipc = ipc
        self._is_primary = is_primary
        self._notif_ctrl = notif_ctrl
        self._theme_cb = None
        self._height_cb = None
        self._position_cb = None
        self._widgets: dict[str, Gtk.Widget] = {}
        self._sections: dict[str, SectionBox] = {}
        self._tray_ctrl: TrayController | None = None
        self._settings_win = None
        self._width = cfg.get("width", "100%")
        self._align = cfg.get("align", "center")
        self._last_width = -1
        self._width_retries = 0
        self._pending_total: int | None = None
        self._width_idle: int | None = None

        self._spacer = Gtk.Box()
        self._spacer.set_size_request(cfg.get("margin", 6), -1)
        self.pack_start(self._spacer, False, False, 0)

        self.pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pill.get_style_context().add_class("taskbar")
        self.pill.set_hexpand(True)
        self.pill.set_halign(Gtk.Align.FILL)
        self.pack_start(self.pill, True, True, 0)

        for section_id in SECTION_ORDER:
            section = SectionBox(section_id, self)
            self._sections[section_id] = section
            expand = section_id in ("left", "right")
            section.set_hexpand(expand)
            if section_id == "right":
                # Hug the right edge; the empty space stays between the center
                # cluster and the right cluster (Win11 style).
                section.box.set_hexpand(False)
                section.box.set_halign(Gtk.Align.END)
            else:
                section.box.set_hexpand(expand)
            self.pill.pack_start(section, expand, True, 0)

        self.connect("size-allocate", self._on_bar_size_allocate)
        self._apply_width()

        self._build_layout(cfg.get("layout") or DEFAULT_LAYOUT)

    # ── width & alignment ────────────────────────────────────────

    def _on_bar_size_allocate(self, _widget, allocation, *_args) -> None:
        # Defer geometry changes out of the size-allocate pass (applying them
        # inline is overridden by the pass that already computed sizes).
        self._pending_total = allocation.width
        if self._width_idle is None:
            self._width_idle = GLib.idle_add(self._apply_width_idle)

    def _apply_width_idle(self) -> bool:
        self._width_idle = None
        if self._pending_total is not None:
            self._apply_width(self._pending_total)
        return GLib.SOURCE_REMOVE

    def _width_px(self, total: int) -> int:
        width = self._width
        if isinstance(width, str) and width.strip().endswith("%"):
            try:
                frac = float(width.strip().rstrip("%")) / 100.0
            except ValueError:
                return 0
            return int(total * max(0.0, min(1.0, frac)))
        try:
            return int(width)
        except (TypeError, ValueError):
            return 0

    def _apply_width(self, total: int | None = None) -> None:
        """Constrain the pill to the configured width (px or %), aligned on the bar.

        GTK3 note: a non-FILL halign disables expansion entirely, so the pill
        only gets the configured align when its width is constrained; at full
        width it must use halign FILL to span the monitor. Because this GTK
        build does not reliably re-allocate a resized child, the geometry is
        re-applied until the pill's actual width matches the target (converges).
        """
        if total is None:
            total = self.get_allocated_width()
        px = self._width_px(total)

        if px == self._last_width and self._pill_width_matches(px, total):
            return
        if px != self._last_width:
            self._width_retries = 0
        self._last_width = px

        if 0 < px < total:
            self.pill.set_hexpand(False)
            self.pill.set_halign(
                {
                    "left": Gtk.Align.START,
                    "center": Gtk.Align.CENTER,
                    "right": Gtk.Align.END,
                }[self._align]
            )
            self.pill.set_size_request(px, -1)
        else:
            self.pill.set_hexpand(True)
            self.pill.set_halign(Gtk.Align.FILL)
            self.pill.set_size_request(-1, -1)
        # Invalidate from the toplevel down so the new width/alignment is
        # actually re-allocated (subtree-only invalidation is unreliable here).
        # Cap the retries so a pathological window can never spin the CPU.
        if self._width_retries < 25:
            self._width_retries += 1
            self.queue_resize()
            toplevel = self.get_toplevel()
            if toplevel is not None and toplevel is not self:
                toplevel.queue_resize()

    def _pill_width_matches(self, px: int, total: int) -> bool:
        if not (0 < px < total):
            return True  # full width: nothing to verify
        return abs(self.pill.get_allocation().width - px) <= 2

    # ── layout ──────────────────────────────────────────────────

    def _build_layout(self, layout: dict) -> None:
        """Empty all sections and repack the module widgets per ``layout``."""
        for section_id in SECTION_ORDER:
            box = self._sections[section_id].box
            for child in list(box.get_children()):
                box.remove(child)
        for section_id in SECTION_ORDER:
            for mid in layout.get(section_id, []):
                widget = self._ensure_module(mid)
                if widget is not None:
                    widget.set_valign(Gtk.Align.CENTER)
                    self._sections[section_id].box.pack_start(widget, False, False, 0)

    def _ensure_module(self, mid: str) -> Gtk.Widget | None:
        if mid in self._widgets:
            return self._widgets[mid]
        widget = self._build_widget(mid)
        if widget is None:
            return None
        self._widgets[mid] = widget
        return widget

    def _build_widget(self, mid: str) -> Gtk.Widget | None:
        cfg, ipc = self._cfg, self._ipc
        if mid == "start_button":
            return StartButton(cfg, ipc)
        if mid == "workspaces":
            return Workspaces(cfg, ipc)
        if mid == "tasklist":
            return TaskList(cfg, ipc)
        if mid == "window":
            return Window(cfg, ipc)
        if mid == "sysmon":
            return SysMon(cfg, ipc)
        if mid == "clock":
            return Clock(cfg, ipc)
        if mid == "notifications":
            if self._notif_ctrl is None:
                return None
            return NotificationCenterButton(cfg, self._notif_ctrl)
        if mid == "tray":
            if not self._is_primary:
                # Only the primary monitor hosts the SNI tray: a second watcher
                # would fight over the org.kde.StatusNotifierWatcher name.
                return None
            tray = Tray(cfg)
            if self._tray_ctrl is None:
                self._tray_ctrl = TrayController(cfg, tray)
            else:  # rebind a fresh widget and re-add any live items
                self._tray_ctrl._tray = tray
                for key, item in list(self._tray_ctrl._items.items()):
                    tray.set_item(key, item)
            return tray
        if mid == "quicksettings":
            return QuickSettingsButton(cfg)
        log.warning("unknown module id %r", mid)
        return None

    def rebuild_layout(self) -> None:
        self._build_layout(self._cfg.get("layout") or DEFAULT_LAYOUT)

    def apply_palette_layout(self, palette: dict) -> None:
        """Apply theme-derived layout (module spacing) to the bar sections."""
        spacing = palette.get("spacing")
        if spacing is None:
            return
        s = max(0, int(round(spacing)))
        for section in self._sections.values():
            section.box.set_spacing(s)

    # ── bar menu ────────────────────────────────────────────────

    def show_bar_menu(self, event) -> None:
        from .bar_menu import build_bar_menu
        menu = build_bar_menu(self._cfg, self._menu_actions())
        menu.show_all()
        menu.popup_at_pointer(event)

    def open_settings(self) -> None:
        from .bar_settings import BarSettings
        if self._settings_win is None or not self._settings_win.get_visible():
            self._settings_win = BarSettings(self._cfg, self._menu_actions())
            toplevel = self.get_toplevel()
            if toplevel is not None and toplevel is not self:
                self._settings_win.set_transient_for(toplevel)
        self._settings_win.present()

    def _menu_actions(self) -> dict:
        cfg = self._cfg

        def _theme():
            if self._theme_cb is not None:
                self._theme_cb()

        def set_source(source: str) -> None:
            cfg.setdefault("theme", {})["source"] = source
            config_module.save(cfg)
            _theme()

        def set_waybar_theme(name: str) -> None:
            cfg.setdefault("theme", {})["waybar_theme"] = name
            config_module.save(cfg)
            _theme()

        def reset_layout() -> None:
            cfg["layout"] = {
                "left": list(DEFAULT_LAYOUT["left"]),
                "center": list(DEFAULT_LAYOUT["center"]),
                "right": list(DEFAULT_LAYOUT["right"]),
            }
            config_module.save(cfg)
            self.rebuild_layout()

        def reload_config() -> None:
            self._cfg = config_module.load()
            self.rebuild_layout()
            _theme()

        def set_width(value: str) -> None:
            self._width = str(value)
            cfg["width"] = self._width
            config_module.save(cfg)
            self._apply_width()

        def set_align(value: str) -> None:
            if value not in ("left", "center", "right"):
                return
            self._align = value
            cfg["align"] = value
            config_module.save(cfg)
            self._last_width = -1  # force _apply_width to re-apply halign
            self._apply_width()

        def set_height(value) -> None:
            try:
                height = max(20, int(str(value).strip()))
            except (TypeError, ValueError):
                height = 42
            cfg["height"] = height
            config_module.save(cfg)
            _theme()  # re-theme: CSS min-height
            if self._height_cb is not None:
                self._height_cb()

        def set_position(value) -> None:
            if value not in ("top", "bottom"):
                return
            cfg["position"] = value
            config_module.save(cfg)
            tray = self._widgets.get("tray")
            if tray is not None:
                tray.set_bar_edge(value)
            if self._position_cb is not None:
                self._position_cb()

        def set_opacity(value) -> None:
            try:
                opacity = max(0.0, min(1.0, float(str(value).strip())))
            except (TypeError, ValueError):
                opacity = 0.95
            cfg["opacity"] = opacity
            config_module.save(cfg)
            _theme()  # re-theme: CSS background alpha

        def apply_layout(layout: dict) -> None:
            cfg["layout"] = {
                "left": list(layout.get("left", [])),
                "center": list(layout.get("center", [])),
                "right": list(layout.get("right", [])),
            }
            config_module.save(cfg)
            self.rebuild_layout()

        def open_settings() -> None:
            self.open_settings()

        return {
            "set_source": set_source,
            "set_waybar_theme": set_waybar_theme,
            "reset_layout": reset_layout,
            "reload_config": reload_config,
            "set_width": set_width,
            "set_align": set_align,
            "set_height": set_height,
            "set_position": set_position,
            "set_opacity": set_opacity,
            "apply_layout": apply_layout,
            "open_settings": open_settings,
        }

    # ── theming callback (set by the app window) ────────────────

    def set_theme_callback(self, callback) -> None:
        self._theme_cb = callback

    def set_height_callback(self, callback) -> None:
        self._height_cb = callback

    def set_position_callback(self, callback) -> None:
        self._position_cb = callback

    # ── data ────────────────────────────────────────────────────

    def start(self) -> None:
        if self._tray_ctrl is not None:
            self._tray_ctrl.start()

    def update(self, clients: list, workspaces: list, active_id: int, focus_address: str | None, active_title: str | None = None, active_class: str | None = None) -> None:
        tasklist = self._widgets.get("tasklist")
        if tasklist is not None:
            tasklist.update(clients, focus_address, active_id)
        workspaces_widget = self._widgets.get("workspaces")
        if workspaces_widget is not None:
            workspaces_widget.update(workspaces, active_id)
        window_widget = self._widgets.get("window")
        if window_widget is not None:
            window_widget.update(active_title, active_class)

    def shutdown(self) -> None:
        tasklist = self._widgets.get("tasklist")
        if tasklist is not None:
            tasklist.shutdown()
        clock = self._widgets.get("clock")
        if clock is not None and clock._popup is not None:
            clock._popup.hide_popup()
        qs = self._widgets.get("quicksettings")
        if qs is not None:
            qs.shutdown()
        if self._tray_ctrl is not None:
            self._tray_ctrl.shutdown()