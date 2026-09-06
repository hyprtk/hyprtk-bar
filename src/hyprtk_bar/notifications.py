"""Notification daemon + center for hyprtk-bar.

The primary bar owns the ``org.freedesktop.Notifications`` bus name and renders
desktop notifications as Win11-style toasts above the bar; the bell button in
the bar opens a notification center that lists the history with action buttons.
No other notification daemon (mako/swaync/xfce4-notifyd) may hold the bus name for this
to receive notifications.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

from dbus_next import Variant  # noqa: E402
from dbus_next.constants import NameFlag, RequestNameReply  # noqa: E402
from dbus_next.glib import MessageBus  # noqa: E402
from dbus_next.service import ServiceInterface, method, signal  # noqa: E402

from .config import icon_size_for  # noqa: E402
from .popup import Popup, bind_hover_tooltip  # noqa: E402
from .popup import Popup  # noqa: E402
from .widgets import Glyph, HoverButton  # noqa: E402

log = logging.getLogger("hyprtk_bar.notifications")

NAME = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"

CLOSED_EXPIRED = 1
CLOSED_DISMISSED = 2
CLOSED_REQUEST = 3

GENERIC_ICON = "dialog-information-symbolic"


def _hint(hints: dict, key: str, default=None):
    value = hints.get(key, default)
    if isinstance(value, Variant):
        value = value.value
    return value


class Notification:
    def __init__(
        self,
        nid: int,
        app_name: str,
        app_icon: str,
        summary: str,
        body: str,
        actions: list,
        hints: dict,
        expire_timeout: int,
        default_timeout: int,
    ):
        self.id = nid
        self.app_name = app_name or ""
        self.app_icon = app_icon or ""
        self.summary = summary or ""
        self.body = body or ""
        raw_actions = list(actions or [])
        # The actions array is flat: [key1, label1, key2, label2, ...].
        self.actions = [
            list(raw_actions[i:i + 2])
            for i in range(0, len(raw_actions) - 1, 2)
        ]
        self.hints = hints or {}
        try:
            self.urgency = int(_hint(self.hints, "urgency", 1))
        except (TypeError, ValueError):
            self.urgency = 1
        self.created = time.time()
        self.persistent = expire_timeout == 0 or self.urgency >= 2 or bool(self.actions)
        if expire_timeout and expire_timeout > 0:
            self.timeout_ms = expire_timeout
        else:
            self.timeout_ms = default_timeout
        self.read = False

    def elapsed_seconds(self) -> int:
        return int(time.time() - self.created)


class NotificationStore:
    def __init__(self, max_items: int):
        self._max = max(1, max_items)
        self._items: list[Notification] = []  # oldest first
        self._by_id: dict[int, Notification] = {}
        self._next_id = 1

    def list(self) -> list[Notification]:
        return list(self._items)

    def get(self, nid: int) -> Notification | None:
        return self._by_id.get(nid)

    def next_id(self) -> int:
        nid = self._next_id
        self._next_id += 1
        return nid

    def add(self, notif: Notification) -> None:
        self._items.append(notif)
        self._by_id[notif.id] = notif
        while len(self._items) > self._max:
            self.remove(self._items[0].id)

    def remove(self, nid: int) -> Notification | None:
        notif = self._by_id.pop(nid, None)
        if notif is not None:
            self._items.remove(notif)
        return notif

    def clear(self) -> None:
        self._items.clear()
        self._by_id.clear()

    def unread_count(self) -> int:
        return sum(1 for n in self._items if not n.read)

    def mark_all_read(self) -> None:
        for n in self._items:
            n.read = True


class NotificationService(ServiceInterface):
    def __init__(self, ctrl: "NotificationController"):
        super().__init__("org.freedesktop.Notifications")
        self._ctrl = ctrl

    @method()
    def GetCapabilities(self) -> "as":
        return [
            "actions",
            "body",
            "body-hyperlinks",
            "icon-static",
            "persistence",
            "urgency",
        ]

    @method()
    def GetServerInformation(self) -> "ssss":
        # The daemon spec declares four separate `s` out args (not one struct).
        # libnotify's strict GDBus type check only accepts the `ssss` shape.
        return ["hyprtk-bar", "hyprtk", "1.0", "1.2"]

    @method()
    def Notify(
        self,
        app_name: "s",
        replaces_id: "u",
        app_icon: "s",
        summary: "s",
        body: "s",
        actions: "as",
        hints: "a{sv}",
        expire_timeout: "i",
    ) -> "u":
        return self._ctrl.notify(
            app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout
        )

    @method()
    def CloseNotification(self, id: "u"):
        self._ctrl.close(id, CLOSED_REQUEST)

    @signal()
    def NotificationClosed(self, id: "u", reason: "u") -> "uu":
        return [id, reason]

    @signal()
    def ActionInvoked(self, id: "u", action_key: "s") -> "us":
        return [id, action_key]


class NotificationController:
    """Owns the notifications bus name, the store, toasts and the center UI."""

    def __init__(self, cfg: dict, monitor=None, bar_win=None):
        self._cfg = cfg
        self._monitor = monitor
        self._bar_win = bar_win
        self._notif_cfg = cfg.get("notifications") or {}
        self._store = NotificationStore(self._notif_cfg.get("max_stored", 50))
        self._default_timeout = self._notif_cfg.get("default_timeout", 5000)
        self._bus: MessageBus | None = None
        self._service: NotificationService | None = None
        self._am_server = False
        self._listeners: list = []  # cb(kind, nid) on the main loop
        self._toast: "Toast | None" = None

    # ── lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        try:
            self._bus = MessageBus()
            self._bus.connect_sync()
        except Exception as exc:
            log.warning("could not connect to session bus: %s", exc)
            self._bus = None
            return
        # The bar is the intended daemon. If another notification daemon
        # (mako/swaync/xfce4-notifyd) was D-Bus auto-activated while the
        # name was briefly free (e.g. during a bar restart), it would keep the
        # name forever and the built-in center would go inactive. Kill the known
        # competitors before requesting the name so the bar always owns it.
        self._kill_competing_daemons()
        self._service = NotificationService(self)
        self._bus.export(PATH, self._service)
        self._bus.request_name(NAME, NameFlag.DO_NOT_QUEUE, self._on_name_reply)

    @staticmethod
    def _kill_competing_daemons() -> None:
        for binary in ("mako", "swaync", "xfce4-notifyd"):
            path = shutil.which(binary)
            if path:
                try:
                    subprocess.run(
                        ["pkill", "-x", binary], capture_output=True, check=False
                    )
                except Exception as exc:
                    log.warning("could not stop competing daemon %s: %s", binary, exc)

    def shutdown(self) -> None:
        self._dismiss_toast()
        if self._bus is not None:
            try:
                self._bus.disconnect()
            except Exception:
                pass
            self._bus = None

    def _on_name_reply(self, reply, err) -> None:
        if err is not None:
            log.warning("could not request %s: %s", NAME, err)
        elif reply == RequestNameReply.PRIMARY_OWNER:
            self._am_server = True
            log.info("owns %s (notification daemon active)", NAME)
        else:
            self._am_server = False
            log.warning(
                "another process owns %s — killing it and retrying",
                NAME,
            )
            # The name is held by a competing daemon that slipped in (D-Bus
            # auto-activation during a restart). Stop it and take the name.
            self._kill_competing_daemons()
            if self._bus is not None:
                GLib.timeout_add(
                    150,
                    lambda: (
                        self._bus.request_name(
                            NAME, NameFlag.DO_NOT_QUEUE, self._on_name_reply
                        ),
                        GLib.SOURCE_REMOVE,
                    )[1],
                )

    # ── UI wiring ─────────────────────────────────────────────────

    def add_listener(self, cb) -> None:
        self._listeners.append(cb)

    def _notify_listeners(self, kind: str, nid: int = 0) -> None:
        for cb in list(self._listeners):
            try:
                cb(kind, nid)
            except Exception:
                log.exception("notification listener failed")

    def _changed(self, kind: str, nid: int = 0) -> None:
        GLib.idle_add(self._notify_listeners, kind, nid)

    # ── the org.freedesktop.Notifications API ─────────────────────

    def notify(
        self,
        app_name: str,
        replaces_id: int,
        app_icon: str,
        summary: str,
        body: str,
        actions: list,
        hints: dict,
        expire_timeout: int,
    ) -> int:
        nid = int(replaces_id or 0)
        existing = self._store.get(nid)
        if nid and existing is not None:
            notif = Notification(
                nid, app_name, app_icon, summary, body, actions, hints,
                expire_timeout, self._default_timeout,
            )
            existing.__dict__.update(notif.__dict__)
            notif = existing
        else:
            nid = self._store.next_id()
            notif = Notification(
                nid, app_name, app_icon, summary, body, actions, hints,
                expire_timeout, self._default_timeout,
            )
            self._store.add(notif)
        self.show_toast(notif)
        self._changed("add", nid)
        return nid

    def close(self, nid: int, reason: int = CLOSED_DISMISSED) -> None:
        """Dismiss a notification's toast; the history entry stays in the store.

        The center is a history panel, so a toast expiring or being closed is
        just a popup dismissal — the notification remains readable in the center
        until the user removes it (per-row dismiss or "Clear all"). The toast
        was shown, so the entry is marked read and the unread badge clears.
        """
        if self._toast is not None and self._toast._notif.id == nid:
            self._dismiss_toast()
        notif = self._store.get(nid)
        if notif is not None:
            if not notif.read:
                notif.read = True
            self._emit_closed(nid, reason)
            self._changed("close", nid)

    def remove(self, nid: int) -> None:
        """Remove a notification from history (the center's per-row dismiss)."""
        if self._store.remove(nid) is not None:
            self._emit_closed(nid, CLOSED_DISMISSED)
            self._changed("close", nid)
        if self._toast is not None and self._toast._notif.id == nid:
            self._dismiss_toast()

    def clear_all(self) -> None:
        for notif in self._store.list():
            self._emit_closed(notif.id, CLOSED_DISMISSED)
        self._store.clear()
        self._dismiss_toast()
        self._changed("clear")

    def dismiss(self, nid: int) -> None:
        self.close(nid, CLOSED_DISMISSED)

    def invoke_action(self, nid: int, key: str) -> None:
        if self._store.get(nid) is None:
            return
        if self._service is not None:
            self._service.ActionInvoked(nid, key)
        self.close(nid, CLOSED_DISMISSED)

    def mark_read(self) -> None:
        if self._store.unread_count() > 0:
            self._store.mark_all_read()
            self._changed("read")

    # ── signals back to clients ───────────────────────────────────

    def _emit_closed(self, nid: int, reason: int) -> None:
        if self._service is not None:
            try:
                self._service.NotificationClosed(nid, reason)
            except Exception:
                log.exception("could not emit NotificationClosed")

    # ── toasts ────────────────────────────────────────────────────

    def show_toast(self, notif: Notification) -> None:
        self._dismiss_toast()
        self._toast = Toast(self._cfg, self, notif, self._monitor, self._bar_win)
        self._toast.show()

    def _dismiss_toast(self) -> None:
        if self._toast is not None:
            toast, self._toast = self._toast, None
            try:
                toast.hide_popup()
                toast.destroy()
            except Exception:
                pass


class NotificationCenterButton(HoverButton):
    """Bar button (bell) with an unread badge; opens the notification center."""

    def __init__(self, cfg: dict, ctrl: NotificationController):
        super().__init__("notif-button", vertical=True, spacing=0)
        self._cfg = cfg
        self._ctrl = ctrl
        self._popup = NotificationCenter(cfg, ctrl)

        font_cfg = cfg.get("font") or {}
        self._icon = Glyph("\uf0f3", "accent-icon")
        self._icon.set_pixel_size(
            icon_size_for(font_cfg.get("size", 16), font_cfg.get("icon_size", 0))
        )

        # Unread indicator: a numbered dot overlaid on the icon's bottom-left
        # corner (mirrors the tasklist running dot) so the bar never resizes.
        self._overlay = Gtk.Overlay()
        self._overlay.add(self._icon)
        self._badge = Gtk.Label(label="")
        self._badge.get_style_context().add_class("notif-dot")
        self._badge.set_no_show_all(True)
        self._badge.set_halign(Gtk.Align.START)
        self._badge.set_valign(Gtk.Align.END)
        self._badge.set_margin_start(2)
        self._badge.set_margin_bottom(2)
        self._badge.hide()
        self._overlay.add_overlay(self._badge)
        self.box.pack_start(self._overlay, True, True, 0)

        ctrl.add_listener(self._on_change)
        self._refresh_badge()
        bind_hover_tooltip(
            self,
            cfg,
            lambda: f"Notifications ({self._ctrl._store.unread_count()} unread)",
        )

    def apply_font(self, font_size, icon_size=0) -> None:
        self._icon.set_pixel_size(icon_size_for(font_size, icon_size))

    def _on_change(self, kind: str, _nid: int) -> None:
        if kind not in ("add", "close", "clear", "read"):
            return
        self._refresh_badge()
        popup = self._popup
        try:
            if popup is not None and popup.get_visible():
                popup.refresh()
        except Exception:
            pass

    def _refresh_badge(self) -> None:
        count = self._ctrl._store.unread_count()
        if count > 0:
            self._badge.set_text(str(count))
            self._badge.show()
        else:
            self._badge.hide()

    def _toggle(self) -> None:
        # Click-opened, interactive panel: it does NOT auto-hide on mouse-leave
        # (a spurious layer-shell crossing closes it before the pointer reaches
        # it). It stays open until the bell is clicked again.
        if self._popup.get_visible():
            self._popup.hide_popup()
        else:
            self._popup.refresh()
            self._popup.show_above(self)
            self._ctrl.mark_read()

    def shutdown(self) -> None:
        self._popup.hide_popup()
        self._popup.destroy()

    def _on_button_press(self, _widget, event):
        if event.button == 1:
            self._toggle()
        return True


class NotificationCenter(Popup):
    """The notification history panel (Win11-style)."""

    WIDTH = 380
    MIN_HEIGHT = 320
    MAX_HEIGHT = 460

    def __init__(self, cfg: dict, ctrl: NotificationController):
        super().__init__(cfg, cfg.get("position", "bottom"))
        self._ctrl = ctrl

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Notifications", xalign=0)
        title.get_style_context().add_class("notif-title")
        header.pack_start(title, True, True, 0)
        clear_btn = Gtk.Button(label="Clear all")
        clear_btn.get_style_context().add_class("notif-clear")
        clear_btn.connect("clicked", lambda *_a: self._ctrl.clear_all())
        header.pack_start(clear_btn, False, False, 0)
        self.content.pack_start(header, False, False, 0)

        self._list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_max_content_height(self.MAX_HEIGHT)
        scroller.add(self._list_box)
        self.content.pack_start(scroller, True, True, 0)

        self.set_size_request(self.WIDTH, self.MIN_HEIGHT)

    def refresh(self) -> None:
        for child in self._list_box.get_children():
            self._list_box.remove(child)
        try:
            items = self._ctrl._store.list()
            if not items:
                empty = Gtk.Label(label="No notifications", xalign=0)
                empty.set_opacity(0.6)
                empty.set_margin_top(12)
                empty.set_margin_bottom(12)
                self._list_box.pack_start(empty, False, False, 0)
            else:
                for notif in reversed(items):  # newest first
                    self._list_box.pack_start(
                        self._make_row(notif), False, False, 0
                    )
        except Exception as exc:
            # A malformed notification must never take down the bar.
            log.warning("could not build notification center list: %s", exc)
        self._list_box.show_all()

    def _make_row(self, notif: Notification) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.get_style_context().add_class("notif-row")

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        icon = Gtk.Image.new_from_icon_name(
            self._icon_name(notif.app_icon), Gtk.IconSize.INVALID
        )
        icon.set_pixel_size(16)
        head.pack_start(icon, False, False, 0)
        app = Gtk.Label(label=notif.app_name or "Notification", xalign=0)
        app.get_style_context().add_class("notif-app")
        head.pack_start(app, True, True, 0)
        when = Gtk.Label(label=self._time_str(notif), xalign=1)
        when.get_style_context().add_class("notif-time")
        head.pack_start(when, False, False, 0)
        row.pack_start(head, False, False, 0)

        summary = Gtk.Label(label=notif.summary, xalign=0, wrap=True)
        summary.get_style_context().add_class("notif-summary")
        row.pack_start(summary, False, False, 0)

        if notif.body:
            body = Gtk.Label(label=notif.body, xalign=0, wrap=True)
            body.get_style_context().add_class("notif-body")
            body.set_max_width_chars(self.WIDTH // 7)
            row.pack_start(body, False, False, 0)

        if notif.actions:
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            actions.set_halign(Gtk.Align.END)
            for key, label in notif.actions:
                btn = Gtk.Button(label=label)
                btn.get_style_context().add_class("notif-action")
                btn.connect("clicked", lambda *_a, k=key: self._ctrl.invoke_action(notif.id, k))
                actions.pack_start(btn, False, False, 0)
            row.pack_start(actions, False, False, 0)

        dismiss = Gtk.Button.new_from_icon_name(
            "window-close-symbolic", Gtk.IconSize.MENU
        )
        dismiss.set_relief(Gtk.ReliefStyle.NONE)
        dismiss.connect("clicked", lambda *_a: self._ctrl.remove(notif.id))
        head.pack_start(dismiss, False, False, 0)
        return row

    @staticmethod
    def _icon_name(app_icon: str) -> str:
        theme = Gtk.IconTheme.get_default()
        if app_icon and theme.has_icon(app_icon):
            return app_icon
        return GENERIC_ICON

    @staticmethod
    def _time_str(notif: Notification) -> str:
        import datetime
        dt = datetime.datetime.fromtimestamp(notif.created)
        now = datetime.datetime.now()
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        return dt.strftime("%d %b %H:%M")


class Toast(Popup):
    """A single floating toast above the bar, right-aligned (Win11-style)."""

    WIDTH = 340

    def __init__(self, cfg: dict, ctrl: NotificationController, notif: Notification, monitor, bar_win=None):
        super().__init__(cfg, cfg.get("position", "bottom"))
        self._ctrl = ctrl
        self._notif = notif
        self._monitor = monitor
        self._bar_win = bar_win if bar_win is not None else getattr(ctrl, "_bar_win", None)
        self._timer = None
        self._build()
        self.set_on_enter(self._cancel_hide)
        self.set_on_leave(self._schedule_hide)

    def _build(self) -> None:
        notif = self._notif

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        icon = Gtk.Image.new_from_icon_name(
            self._icon_name(notif.app_icon), Gtk.IconSize.INVALID
        )
        icon.set_pixel_size(18)
        head.pack_start(icon, False, False, 0)
        app = Gtk.Label(label=notif.app_name or "Notification", xalign=0)
        app.get_style_context().add_class("notif-app")
        head.pack_start(app, True, True, 0)
        close = Gtk.Button.new_from_icon_name(
            "window-close-symbolic", Gtk.IconSize.MENU
        )
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.connect("clicked", lambda *_a: self._ctrl.dismiss(notif.id))
        head.pack_start(close, False, False, 0)
        self.content.pack_start(head, False, False, 0)

        summary = Gtk.Label(label=notif.summary, xalign=0, wrap=True)
        summary.get_style_context().add_class("notif-summary")
        self.content.pack_start(summary, False, False, 0)

        if notif.body:
            body = Gtk.Label(label=notif.body, xalign=0, wrap=True)
            body.get_style_context().add_class("notif-body")
            body.set_max_width_chars(self.WIDTH // 7)
            self.content.pack_start(body, False, False, 0)

        if notif.actions:
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            actions.set_halign(Gtk.Align.END)
            for key, label in notif.actions:
                btn = Gtk.Button(label=label)
                btn.get_style_context().add_class("notif-action")
                btn.connect("clicked", lambda *_a, k=key: self._ctrl.invoke_action(notif.id, k))
                actions.pack_start(btn, False, False, 0)
            self.content.pack_start(actions, False, False, 0)

        self.content.connect("button-press-event", self._on_content_press)
        self.set_size_request(self.WIDTH, -1)

    def _icon_name(self, app_icon: str) -> str:
        theme = Gtk.IconTheme.get_default()
        if app_icon and theme.has_icon(app_icon):
            return app_icon
        return GENERIC_ICON

    def show(self) -> None:
        self.content.show_all()
        nat = self.content.get_preferred_size().natural_size
        w = max(nat.width, 1)
        h = max(nat.height, 1)
        self.set_size_request(w, h)

        # Center the toast on the screen — it floats mid-screen, not off the
        # bar's edge, regardless of the bar's top/bottom position.
        margin = 6
        if self._monitor is not None:
            geo = self._monitor.get_geometry()
            screen_w, screen_h = geo.width, geo.height
        else:
            screen = Gdk.Screen.get_default()
            screen_w, screen_h = screen.get_width(), screen.get_height()
        x = max(margin, (screen_w - w) // 2)
        y = max(margin, (screen_h - h) // 2)

        # Anchor top-left and position with margins so the toast is centered.
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, y)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, x)

        self.show_all()

        if not self._notif.persistent and self._notif.timeout_ms > 0:
            self._timer = GLib.timeout_add(self._notif.timeout_ms, self._expire)

    def _expire(self) -> bool:
        self._timer = None
        self._ctrl.close(self._notif.id, CLOSED_EXPIRED)
        return GLib.SOURCE_REMOVE

    def _cancel_hide(self) -> None:
        self._cancel_timer()

    def _schedule_hide(self) -> None:
        self._cancel_timer()
        if self._timer is None and not self._notif.persistent:
            self._timer = GLib.timeout_add(
                max(self._notif.timeout_ms, 1000), self._expire
            )

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _on_content_press(self, *_args) -> bool:
        self._ctrl.dismiss(self._notif.id)
        return True