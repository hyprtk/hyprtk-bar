"""The bar: a Win11-style horizontal layout with edge widgets.

Layout (inside the transparent layer-shell surface):

    [ left spacer ][ pill (left | centered task list | right) ][ show-desktop strip ]

The pill carries the background/rounded corners; the strip hugs the screen's
right edge, Windows-11 style, and toggles "show desktop".
"""
from __future__ import annotations

import logging

import gi
gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk  # noqa: E402

from .clock import Clock  # noqa: E402
from .quicksettings import QuickSettingsButton  # noqa: E402
from .sysmon import SysMon  # noqa: E402
from .tasklist import TaskList  # noqa: E402
from .tray import Tray, TrayController  # noqa: E402
from .widgets import HoverButton  # noqa: E402
from .workspaces import Workspaces  # noqa: E402

log = logging.getLogger("hyprtk_bar.bar")


class StartButton(HoverButton):
    def __init__(self, cfg: dict, ipc):
        super().__init__("task-button start", vertical=True, spacing=2)
        center = cfg.get("center") or {}
        self._ipc = ipc
        self._command = center.get("start_command", "hyprtk-menu")
        icon = Gtk.Image.new_from_icon_name(
            center.get("start_icon", "view-grid-symbolic"), Gtk.IconSize.INVALID
        )
        icon.set_pixel_size(22)
        self.box.pack_start(icon, True, True, 0)

    def _on_button_press(self, _widget, event):
        if event.button == 1:
            try:
                GLib.spawn_command_line_async(self._command)
            except GLib.Error as exc:
                log.warning("Failed to launch start menu %r: %s", self._command, exc)
        return True


class ShowDesktopStrip(HoverButton):
    """Win11 'show desktop' sliver: hides/restores all windows on the active workspace."""

    def __init__(self, cfg: dict, ipc):
        super().__init__("show-desktop", vertical=False, spacing=0)
        self._ipc = ipc
        self._hidden: list[tuple[str, int]] = []

    def _on_button_press(self, _widget, event):
        if event.button == 1:
            self.toggle()
        return True

    def toggle(self) -> None:
        if self._hidden:
            for addr, ws in self._hidden:
                self._ipc.move_window(ws, addr)
            self._hidden = []
            return
        active = self._ipc.query("activeworkspace") or {}
        a_id = active.get("id")
        if not isinstance(a_id, int) or a_id <= 0:
            return
        clients = self._ipc.query("clients") or []
        for c in clients:
            if not c.get("mapped"):
                continue
            ws = c.get("workspace")
            c_id = ws.get("id") if isinstance(ws, dict) else ws
            if c_id == a_id:
                addr = c.get("address")
                if not addr:
                    continue
                self._ipc.move_window("special:show-desktop", addr)
                self._hidden.append((addr, a_id))


class Bar(Gtk.Box):
    def __init__(self, cfg: dict, ipc):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self._cfg = cfg
        self._ipc = ipc

        self._spacer = Gtk.Box()
        self._spacer.set_size_request(cfg.get("margin", 6), -1)
        self.pack_start(self._spacer, False, False, 0)

        self.pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pill.get_style_context().add_class("taskbar")
        self.pill.set_hexpand(True)
        self.pack_start(self.pill, True, True, 0)

        # Center: start button + workspace chips (task view) + task buttons.
        self._tasklist = TaskList(cfg, ipc)
        center = cfg.get("center") or {}
        self._center_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        if center.get("start_button"):
            self._start = StartButton(cfg, ipc)
            self._center_box.pack_start(self._start, False, False, 0)
        ws_cfg = cfg.get("workspaces") or {}
        if ws_cfg.get("enabled"):
            self._workspaces = Workspaces(cfg, ipc)
            self._center_box.pack_start(self._workspaces, False, False, 0)
        else:
            self._workspaces = None
        if self._workspaces is not None:
            divider = Gtk.Box()
            divider.get_style_context().add_class("divider")
            divider.set_valign(Gtk.Align.CENTER)
            self._center_box.pack_start(divider, False, False, 0)
        self._center_box.pack_start(self._tasklist, False, False, 0)

        center_holder = Gtk.Box()
        center_holder.set_hexpand(True)
        center_holder.pack_start(self._center_box, True, True, 0)
        self.pill.pack_start(center_holder, True, True, 0)

        # Right: quick settings, system tray then clock (qs rightmost).
        qs_cfg = cfg.get("quicksettings") or {}
        self._qs = None
        if qs_cfg.get("enabled"):
            self._qs = QuickSettingsButton(cfg)
            self.pill.pack_end(self._qs, False, False, 0)
        tray_cfg = cfg.get("tray") or {}
        self._tray = None
        self._tray_ctrl = None
        if tray_cfg.get("enabled"):
            self._tray = Tray(cfg)
            self._tray_ctrl = TrayController(cfg, self._tray)
            self.pill.pack_end(self._tray, False, False, 0)
        clock_cfg = cfg.get("clock") or {}
        if clock_cfg.get("enabled"):
            self._clock = Clock(cfg, ipc)
            self.pill.pack_end(self._clock, False, False, 0)
        else:
            self._clock = None
        sysmon_cfg = cfg.get("sysmon") or {}
        self._sysmon = None
        if sysmon_cfg.get("enabled"):
            self._sysmon = SysMon(cfg, ipc)
            self.pill.pack_end(self._sysmon, False, False, 0)

        # Far right edge: show-desktop strip.
        if cfg.get("show_desktop"):
            self.strip = ShowDesktopStrip(cfg, ipc)
            self.pack_end(self.strip, False, False, 0)
        else:
            self._strip = None

    # ── data ──────────────────────────────────────────────────────

    def start(self) -> None:
        if self._tray_ctrl is not None:
            self._tray_ctrl.start()

    def update(self, clients: list, workspaces: list, active_id: int, focus_address: str | None) -> None:
        self._tasklist.update(clients, focus_address, active_id)
        if self._workspaces is not None:
            self._workspaces.update(workspaces, active_id)

    def shutdown(self) -> None:
        self._tasklist.shutdown()
        if self._clock is not None and self._clock._popup is not None:
            self._clock._popup.hide_popup()
        if self._qs is not None:
            self._qs.shutdown()
        if self._tray_ctrl is not None:
            self._tray_ctrl.shutdown()