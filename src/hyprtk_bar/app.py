"""Layer-shell window hosting the taskbar, plus Hyprland event wiring."""
from __future__ import annotations

import cairo
import logging

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell  # noqa: E402

from .bar import Bar  # noqa: E402
from .config import PYWAL_PATH  # noqa: E402
from .ipc import HyprIPC  # noqa: E402
from .notifications import NotificationController  # noqa: E402
from .theme import build_css, resolve_palette  # noqa: E402
from .waybar_theme import find_themes_dir  # noqa: E402

log = logging.getLogger("hyprtk_bar.app")

# Socket events that should trigger a taskbar refresh.
REFRESH_EVENTS = (
    "openwindow",
    "closewindow",
    "movewindow",
    "workspace",
    "workspacev2",
    "activewindow",
    "activewindowv2",
    "fullscreen",
    "changefloatingmode",
    "focusedmon",
    "moveworkspace",
    "windowtitlev2",
    "windowclassv2",
    "urgent",
    "monitoraddedv2",
    "monitorremovedv2",
    "openlayer",
    "closelayer",
)


def select_monitors(cfg: dict) -> list[Gdk.Monitor]:
    """Return the Gdk monitors the bar should be shown on.

    ``monitors`` selects the target set:
    - ``"primary"`` (default): only the primary monitor.
    - ``"all"``: every monitor.
    - a list of connector/model names (e.g. ``["DP-1", "HDMI-A-1"]``).
    """
    display = Gdk.Display.get_default()
    if display is None:
        return []
    monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
    mode = cfg.get("monitors", "primary")
    if mode == "all":
        return list(monitors)
    if isinstance(mode, list) and mode:
        names = set(mode)
        # Gdk Wayland monitors expose no connector name; map Hyprland connector
        # names onto Gdk monitors by geometry so both names and models match.
        hypr_names = _hypr_monitors_by_geometry()
        matched = []
        for m in monitors:
            _connector, model, geo = _monitor_identifiers(m)
            name = hypr_names.get(geo) or ""
            if name in names or model in names:
                matched.append(m)
        return matched
    primary = [m for m in monitors if m.is_primary()]
    return primary or monitors[:1]


def _hypr_monitors_by_geometry() -> dict:
    """Map ``(x, y, w, h)`` -> Hyprland monitor connector name."""
    import json
    import subprocess

    try:
        out = subprocess.run(
            ["hyprctl", "-j", "monitors"], capture_output=True, text=True, timeout=5
        )
        data = json.loads(out.stdout)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return {}
    result = {}
    for mon in data:
        g = mon.get("geometry") or {}
        key = (
            g.get("x") if g.get("x") is not None else mon.get("x"),
            g.get("y") if g.get("y") is not None else mon.get("y"),
            g.get("width") if g.get("width") is not None else mon.get("width"),
            g.get("height") if g.get("height") is not None else mon.get("height"),
        )
        result[key] = mon.get("name")
    return result


def _monitor_identifiers(monitor: Gdk.Monitor) -> tuple[str, str, tuple]:
    """(connector, model, geometry) for a Gdk monitor.

    Under Wayland ``get_connector()`` is unavailable (X11-only), so the model
    name (e.g. "C49J89x") and the geometry are the reliable identifiers.
    """
    getter = getattr(monitor, "get_connector", None)
    connector = getter() if getter is not None else ""
    try:
        model = monitor.get_model() or ""
    except Exception:
        model = ""
    geo = monitor.get_geometry()
    return connector, model, (geo.x, geo.y, geo.width, geo.height)


class BarWindow(Gtk.Window):
    """A transparent, full-width layer-shell surface pinned to an edge."""

    def __init__(
        self,
        cfg: dict,
        monitor: Gdk.Monitor | None = None,
        ipc: HyprIPC | None = None,
        is_primary: bool = True,
        start_ipc: bool = False,
        notif_ctrl: NotificationController | None = None,
    ):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._cfg = cfg
        self.monitor = monitor
        self.is_primary = is_primary
        self._refresh_id: int | None = None
        self._wal_monitor: Gio.FileMonitor | None = None
        self._theme_dir_monitor: Gio.FileMonitor | None = None
        self._wal_debounce: int | None = None

        self.set_title("hyprtk-bar")
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_app_paintable(True)
        self.set_accept_focus(False)

        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self._ipc = ipc if ipc is not None else HyprIPC()
        self._notif_ctrl = notif_ctrl
        if (
            self._notif_ctrl is None
            and is_primary
            and (cfg.get("notifications") or {}).get("enabled", True)
        ):
            self._notif_ctrl = NotificationController(cfg, monitor=monitor, bar_win=self)
            self._notif_ctrl.start()
        self._bar = Bar(cfg, self._ipc, is_primary=is_primary, notif_ctrl=self._notif_ctrl)
        self._bar.set_theme_callback(self._apply_theme)
        self._bar.set_height_callback(self._on_bar_height)
        self._bar.set_position_callback(self._on_bar_position)
        self.add(self._bar)
        self._bar.connect("size-allocate", self._on_size_allocate)

        self._provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), self._provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        self._apply_theme()

        self._init_layer_shell()

        self._wire_ipc()
        if start_ipc:
            self._ipc.start()
        self._bar.start()

        self._setup_theme_monitors()

    # ── theming ───────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        palette = resolve_palette(self._cfg)
        css = build_css(palette, self._cfg)
        self._provider.load_from_data(css.encode())
        self._bar.apply_palette_layout(palette)
        self._bar.apply_font(palette.get("font_size"))
        # Force a redraw + re-layout so module text re-renders at the new font
        # size immediately (not only on the next pointer event).
        self._bar.queue_resize()
        self._bar.queue_draw()

    def _setup_theme_monitors(self) -> None:
        """Watch the sources a live re-theme depends on.

        - pywal colors (``~/.cache/wal`` — colors.json + the generated
          ``colors-waybar*.css`` that waybar themes @import),
        - the hyprtk waybar theme switcher file (``~/.cache/.themestyle.sh``),
        - the waybar themes directory itself.
        """
        try:
            self._wal_monitor = Gio.File.new_for_path(
                str(PYWAL_PATH.parent)
            ).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        except GLib.Error as exc:
            log.warning("Could not monitor pywal cache: %s", exc)
        else:
            self._wal_monitor.connect("changed", self._on_theme_source_changed)

        base = find_themes_dir()
        try:
            self._theme_dir_monitor = Gio.File.new_for_path(
                str(base)
            ).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        except GLib.Error as exc:
            log.warning("Could not monitor themes dir: %s", exc)
        else:
            self._theme_dir_monitor.connect("changed", self._on_theme_source_changed)

    def _on_theme_source_changed(self, _monitor, *_args) -> None:
        if self._wal_debounce is not None:
            GLib.source_remove(self._wal_debounce)
        self._wal_debounce = GLib.timeout_add(350, self._reload_theme)

    def _reload_theme(self) -> bool:
        self._wal_debounce = None
        self._apply_theme()
        return GLib.SOURCE_REMOVE

    def _on_bar_height(self) -> None:
        """Resize the layer surface when the bar height is changed in settings."""
        total_height = self._cfg["height"] + 2 * self._cfg["margin"]
        GtkLayerShell.set_exclusive_zone(self, total_height)
        self.set_size_request(-1, total_height)

    def _on_bar_position(self) -> None:
        """Re-anchor the layer surface when the bar moves top/bottom in settings."""
        edge = (
            GtkLayerShell.Edge.TOP
            if self._cfg["position"] == "top"
            else GtkLayerShell.Edge.BOTTOM
        )
        other = (
            GtkLayerShell.Edge.BOTTOM
            if edge == GtkLayerShell.Edge.TOP
            else GtkLayerShell.Edge.TOP
        )
        GtkLayerShell.set_anchor(self, other, False)
        GtkLayerShell.set_anchor(self, edge, True)
        total_height = self._cfg["height"] + 2 * self._cfg["margin"]
        GtkLayerShell.set_exclusive_zone(self, total_height)
        self.set_size_request(-1, total_height)
        # Move any open popups (calendar, previews, quick settings, notification
        # center) and the toast to the new bar edge.
        position = self._cfg["position"]
        for widget in self._bar._widgets.values():
            for attr in ("_popup", "_preview"):
                popup = getattr(widget, attr, None)
                if popup is not None:
                    popup.set_bar_edge(position)
                    popup.reposition()
        if self._notif_ctrl is not None and self._notif_ctrl._toast is not None:
            self._notif_ctrl._toast.set_bar_edge(position)
            self._notif_ctrl._toast.reposition()

    # ── layer shell ───────────────────────────────────────────────

    def _init_layer_shell(self) -> None:
        total_height = self._cfg["height"] + 2 * self._cfg["margin"]
        GtkLayerShell.init_for_window(self)
        if self.monitor is not None:
            GtkLayerShell.set_monitor(self, self.monitor)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_namespace(self, "hyprtk-bar")
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        if self._cfg["position"] == "top":
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        else:
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_exclusive_zone(self, total_height)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        self.set_size_request(-1, total_height)

    # ── input shape: only the pill is clickable ─────────────────────

    def _on_size_allocate(self, *_args) -> None:
        self._apply_input_shape()

    def _apply_input_shape(self) -> None:
        wnd = self.get_window()
        if wnd is None:
            return
        margin = self._cfg["margin"]
        region = cairo.Region()

        def add(widget, inset_x: int, inset_y: int) -> None:
            alloc = widget.get_allocation()
            rect = cairo.RectangleInt(
                alloc.x + inset_x,
                alloc.y + inset_y,
                max(alloc.width - 2 * inset_x, 0),
                max(alloc.height - 2 * inset_y, 0),
            )
            region.union(rect)

        for child in self._bar.get_children():
            if child is self._bar.pill:
                # The pill's CSS margin insets it on all sides.
                add(child, margin, margin)
        wnd.input_shape_combine_region(region, 0, 0)

    # ── IPC ───────────────────────────────────────────────────────

    def _wire_ipc(self) -> None:
        self._ipc.on_connect(self._on_connected)
        for event in REFRESH_EVENTS:
            self._ipc.on(event, self._on_ipc_event)

    def _on_connected(self) -> None:
        GLib.idle_add(self._refresh)

    def _on_ipc_event(self, _data) -> None:
        GLib.idle_add(self._schedule_refresh)

    def _schedule_refresh(self) -> bool:
        if self._refresh_id is not None:
            GLib.source_remove(self._refresh_id)
        self._refresh_id = GLib.timeout_add(120, self._refresh)
        return GLib.SOURCE_REMOVE

    def _refresh(self) -> bool:
        self._refresh_id = None
        clients = self._ipc.query("clients")
        if clients is None:
            return GLib.SOURCE_REMOVE
        workspaces = self._ipc.query("workspaces") or []
        active = self._ipc.query("activeworkspace") or {}
        focus = self._ipc.query("activewindow") or {}
        global_id = active.get("id") if isinstance(active.get("id"), int) else 1
        a_id = self._active_workspace_on_this_monitor(global_id)
        self._bar.update(
            clients, workspaces, a_id,
            focus.get("address"), focus.get("title"), focus.get("class"),
        )
        return GLib.SOURCE_REMOVE

    def _active_workspace_on_this_monitor(self, fallback: int) -> int:
        """The active workspace on THIS bar's monitor (each monitor has its own).

        Gdk Wayland monitors expose no connector name, so the monitor is matched
        against `hyprctl monitors` by model name or geometry; falls back to the
        global active workspace when it can't be identified (e.g. a special: one).
        """
        if self.monitor is None:
            return fallback
        connector, model, geo = _monitor_identifiers(self.monitor)
        monitors = self._ipc.query("monitors") or []
        for m in monitors:
            if not self._monitor_matches(m, connector, model, geo):
                continue
            aw = m.get("activeWorkspace") or {}
            if isinstance(aw.get("id"), int):
                return aw["id"]
            break
        return fallback

    @staticmethod
    def _monitor_matches(m: dict, connector: str, model: str, geo: tuple) -> bool:
        if connector and m.get("name") == connector:
            return True
        if model and (m.get("model") or "") == model:
            return True
        g = m.get("geometry") or {}
        return (
            isinstance(g, dict)
            and g.get("x") == geo[0]
            and g.get("y") == geo[1]
            and g.get("width") == geo[2]
            and g.get("height") == geo[3]
        )

    # ── shutdown ──────────────────────────────────────────────────

    def shutdown(self) -> None:
        for monitor in (self._wal_monitor, self._theme_dir_monitor):
            if monitor is not None:
                monitor.cancel()
        if self._wal_debounce is not None:
            GLib.source_remove(self._wal_debounce)
        if self._refresh_id is not None:
            GLib.source_remove(self._refresh_id)
        self._bar.shutdown()
        if self._notif_ctrl is not None:
            self._notif_ctrl.shutdown()
        self._ipc.stop()