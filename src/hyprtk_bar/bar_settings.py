"""Bar settings window: bar width/height/align and per-module layout control.

A frameless floating window (dragged by its header; Hyprland floats+centers it
via a windowrule on the title "hyprtk-bar settings"). Edits the bar's
``layout`` — each module can be shown/hidden, assigned to the left/center/right
section, and reordered within its section — plus bar width, height, alignment
and theme. Apply writes the config and rebuilds/re-themes the bar live.
"""
from __future__ import annotations

from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, Gtk  # noqa: E402

from .config import DEFAULT_LAYOUT, MODULE_IDS, MODULE_LABELS  # noqa: E402
from .waybar_theme import import_theme, list_themes  # noqa: E402

SECTION_ORDER = ("left", "center", "right")
SECTION_LABELS = {"left": "Left", "center": "Center", "right": "Right"}
THEME_SOURCES = (
    ("pywal", "Pywal (dynamic)"),
    ("waybar", "Imported theme"),
    ("manual", "Manual (config)"),
)


def _radio_group(labels: list[tuple[str, str]]) -> dict[str, Gtk.RadioButton]:
    """Build a Gtk.RadioButton group from ``(key, label)`` pairs.

    Gtk.RadioButton.new_with_label(group, ...) crashes in this build and the
    ``group=`` kwarg rejects a sequence, so buttons are created standalone
    (``group=None``) and joined with ``join_group``.
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


class BarSettings(Gtk.Window):
    def __init__(self, cfg: dict, actions: dict):
        super().__init__(title="hyprtk-bar settings")
        self._cfg = cfg
        self._actions = actions
        self._hidden: set[str] = set()
        self._rows: dict[str, dict] = {}
        self._layout = cfg.get("layout") or {}

        visible = {
            mid
            for section in SECTION_ORDER
            for mid in (self._layout.get(section) or [])
        }
        self._order: dict[str, list[str]] = {
            s: list(self._layout.get(s, []) or []) for s in SECTION_ORDER
        }
        for mid in MODULE_IDS:
            if mid not in visible:
                self._hidden.add(mid)
                for s in SECTION_ORDER:
                    if mid in DEFAULT_LAYOUT[s]:
                        self._order[s].append(mid)
                        break

        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_default_size(640, 780)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("key-press-event", self._on_key)
        self._build()
        self.show_all()

    # ── ui ───────────────────────────────────────────────────────

    def _style_header(self, header: Gtk.EventBox) -> None:
        """Scope a little CSS so the drag header reads as a title bar."""
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b"""
.settings-title { font-weight: bold; font-size: 14px; }
.settings-header { background-color: alpha(currentColor, 0.06);
                   border-bottom: 1px solid alpha(currentColor, 0.12);
                   border-radius: 8px 8px 0 0;
                   padding: 8px 10px; }
"""
        )
        style = header.get_style_context()
        style.add_class("settings-header")
        style.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _on_header_press(self, _widget, event) -> bool:
        """Drag the frameless window by its header."""
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            self.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root), event.time
            )
            return True
        return False

    def _on_key(self, _window, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _build(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        self.add(root)

        # Draggable header (frameless window).
        header = Gtk.EventBox()
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_title = Gtk.Label(label="hyprtk-bar settings", xalign=0)
        header_title.get_style_context().add_class("settings-title")
        header_box.pack_start(header_title, True, True, 0)
        header.add(header_box)
        header.connect("button-press-event", self._on_header_press)
        self._style_header(header)
        root.pack_start(header, False, False, 0)

        # ── Bar section ──────────────────────────────────────────
        # Inline controls only: GtkComboBox popups mis-position on this
        # GTK3/Wayland build, so no dropdowns here.
        bar_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        title = Gtk.Label(label="Bar", xalign=0)
        title.get_style_context().add_class("settings-heading")
        bar_group.pack_start(title, False, False, 0)

        height_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        height_label = Gtk.Label(label="Height:", xalign=1)
        height_label.set_size_request(70, -1)
        self._height = Gtk.SpinButton.new_with_range(20, 120, 2)
        self._height.set_value(int(self._cfg.get("height", 42)))
        self._height.set_hexpand(True)
        height_row.pack_start(height_label, False, False, 0)
        height_row.pack_start(self._height, True, True, 0)

        width_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        width_label = Gtk.Label(label="Width:", xalign=1)
        width_label.set_size_request(70, -1)
        self._width = Gtk.Entry()
        self._width.set_text(str(self._cfg.get("width", "100%")))
        self._width.set_placeholder_text("e.g. 75% or 600")
        self._width.set_hexpand(True)
        width_hint = Gtk.Label(label="% or px", xalign=0)
        width_hint.set_opacity(0.7)
        width_row.pack_start(width_label, False, False, 0)
        width_row.pack_start(self._width, True, True, 0)
        width_row.pack_start(width_hint, False, False, 0)

        align_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        align_label = Gtk.Label(label="Align:", xalign=1)
        align_label.set_size_request(70, -1)
        self._align_buttons = _radio_group(
            [(s, SECTION_LABELS[s]) for s in SECTION_ORDER]
        )
        align_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for btn in self._align_buttons.values():
            align_box.pack_start(btn, False, False, 0)
        self._align_buttons[self._cfg.get("align", "center")].set_active(True)
        align_box.set_hexpand(True)
        align_row.pack_start(align_label, False, False, 0)
        align_row.pack_start(align_box, True, True, 0)

        position_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        position_label = Gtk.Label(label="Position:", xalign=1)
        position_label.set_size_request(70, -1)
        self._position_buttons = _radio_group(
            [("bottom", "Bottom"), ("top", "Top")]
        )
        position_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for btn in self._position_buttons.values():
            position_box.pack_start(btn, False, False, 0)
        self._position_buttons[self._cfg.get("position", "bottom")].set_active(True)
        position_box.set_hexpand(True)
        position_row.pack_start(position_label, False, False, 0)
        position_row.pack_start(position_box, True, True, 0)

        opacity_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        opacity_label = Gtk.Label(label="Opacity:", xalign=1)
        opacity_label.set_size_request(70, -1)
        self._opacity = Gtk.Entry()
        self._opacity.set_text(str(int(round(self._cfg.get("opacity", 0.95) * 100))))
        self._opacity.set_width_chars(4)
        self._opacity.set_input_purpose(Gtk.InputPurpose.NUMBER)
        opacity_hint = Gtk.Label(label="% (0–100)", xalign=0)
        opacity_hint.set_opacity(0.7)
        opacity_row.pack_start(opacity_label, False, False, 0)
        opacity_row.pack_start(self._opacity, True, True, 0)
        opacity_row.pack_start(opacity_hint, False, False, 0)

        bar_group.pack_start(height_row, False, False, 0)
        bar_group.pack_start(width_row, False, False, 0)
        bar_group.pack_start(align_row, False, False, 0)
        bar_group.pack_start(position_row, False, False, 0)
        bar_group.pack_start(opacity_row, False, False, 0)
        root.pack_start(bar_group, False, False, 0)

        # ── Theme section ────────────────────────────────────────
        theme_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        theme_title = Gtk.Label(label="Theme", xalign=0)
        theme_title.get_style_context().add_class("settings-heading")
        theme_group.pack_start(theme_title, False, False, 0)

        theme = self._cfg.get("theme") or {}
        source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        source_label = Gtk.Label(label="Source:", xalign=1)
        source_label.set_size_request(70, -1)
        self._source_buttons = _radio_group(list(THEME_SOURCES))
        source_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for btn in self._source_buttons.values():
            btn.connect("toggled", self._on_source_toggled)
            source_box.pack_start(btn, False, False, 0)
        source_key = theme.get("source", "pywal")
        self._source_buttons[source_key if source_key in self._source_buttons else "pywal"].set_active(True)
        source_box.set_hexpand(True)
        source_row.pack_start(source_label, False, False, 0)
        source_row.pack_start(source_box, True, True, 0)

        theme_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        theme_label = Gtk.Label(label="Imported theme:", xalign=1)
        theme_label.set_size_request(70, -1)
        self._themes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        themes_scroller = Gtk.ScrolledWindow()
        themes_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        themes_scroller.set_min_content_height(96)
        themes_scroller.add(self._themes_box)
        themes_scroller.set_hexpand(True)
        import_btn = Gtk.Button(label="Import…")
        import_btn.connect("clicked", self._on_import)
        theme_row.pack_start(theme_label, False, False, 0)
        theme_row.pack_start(themes_scroller, True, True, 0)
        theme_row.pack_start(import_btn, False, False, 0)

        theme_group.pack_start(source_row, False, False, 0)
        theme_group.pack_start(theme_row, False, False, 0)
        root.pack_start(theme_group, False, False, 0)
        self._refresh_themes(select=theme.get("waybar_theme") or None)
        self._update_source_state()

        # ── Font section ──────────────────────────────────────────
        font_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        font_title = Gtk.Label(label="Font", xalign=0)
        font_title.get_style_context().add_class("settings-heading")
        font_group.pack_start(font_title, False, False, 0)

        font_cfg = self._cfg.get("font") or {}
        family_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        family_label = Gtk.Label(label="Family:", xalign=1)
        family_label.set_size_request(70, -1)
        self._font_family = Gtk.Entry()
        self._font_family.set_text(str(font_cfg.get("family", "") or ""))
        self._font_family.set_placeholder_text("blank = system font")
        self._font_family.set_hexpand(True)
        family_row.pack_start(family_label, False, False, 0)
        family_row.pack_start(self._font_family, True, True, 0)

        size_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        size_label = Gtk.Label(label="Size:", xalign=1)
        size_label.set_size_request(70, -1)
        self._font_size = Gtk.SpinButton.new_with_range(8, 40, 1)
        self._font_size.set_value(int(font_cfg.get("size", 16)))
        size_hint = Gtk.Label(label="px (icons scale to match)", xalign=0)
        size_hint.set_opacity(0.7)
        size_row.pack_start(size_label, False, False, 0)
        size_row.pack_start(self._font_size, True, True, 0)
        size_row.pack_start(size_hint, False, False, 0)

        font_group.pack_start(family_row, False, False, 0)
        font_group.pack_start(size_row, False, False, 0)
        root.pack_start(font_group, False, False, 0)

        # ── Modules section ──────────────────────────────────────
        mod_title = Gtk.Label(
            label="Modules — position (left/center/right) and order within the bar.",
            xalign=0,
            wrap=True,
        )
        mod_title.get_style_context().add_class("settings-heading")
        root.pack_start(mod_title, False, False, 0)

        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for mid in MODULE_IDS:
            list_box.pack_start(self._make_row(mid), False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.add(list_box)
        root.pack_start(scroller, True, True, 0)

        # ── buttons ──────────────────────────────────────────────
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_halign(Gtk.Align.END)
        reset_btn = Gtk.Button(label="Reset layout")
        reset_btn.connect("clicked", self._on_reset)
        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda *_a: self.close())
        apply_btn = Gtk.Button(label="Apply")
        apply_btn.get_style_context().add_class("suggested-action")
        apply_btn.connect("clicked", self._on_apply)
        buttons.pack_start(reset_btn, False, False, 0)
        buttons.pack_start(close_btn, False, False, 0)
        buttons.pack_start(apply_btn, False, False, 0)
        root.pack_start(buttons, False, False, 0)

    def _make_row(self, mid: str) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        check = Gtk.CheckButton(label=MODULE_LABELS.get(mid, mid))
        check.set_active(mid not in self._hidden)
        check.connect("toggled", self._on_show, mid)
        check.set_hexpand(True)
        row.pack_start(check, True, True, 0)

        position = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        buttons = _radio_group([(s, SECTION_LABELS[s]) for s in SECTION_ORDER])
        for s, btn in buttons.items():
            btn.connect("toggled", self._on_position, mid, s)
            position.pack_start(btn, False, False, 0)
        row.pack_start(position, False, False, 0)

        up = Gtk.Button.new_from_icon_name("go-up-symbolic", Gtk.IconSize.BUTTON)
        down = Gtk.Button.new_from_icon_name("go-down-symbolic", Gtk.IconSize.BUTTON)
        up.connect("clicked", self._on_move, mid, -1)
        down.connect("clicked", self._on_move, mid, 1)
        row.pack_start(up, False, False, 0)
        row.pack_start(down, False, False, 0)

        self._rows[mid] = {
            "check": check,
            "position": buttons,
            "up": up,
            "down": down,
        }
        self._update_row_state(mid)
        return row

    def _update_row_state(self, mid: str) -> None:
        state = self._rows[mid]
        shown = mid not in self._hidden
        section = self._section_of(mid)
        for sec, btn in state["position"].items():
            btn.handler_block_by_func(self._on_position)
            btn.set_active(sec == section)
            btn.handler_unblock_by_func(self._on_position)
            btn.set_sensitive(shown)
        state["check"].set_active(shown)
        order = self._order.get(section, [])
        index = order.index(mid) if mid in order else -1
        state["up"].set_sensitive(shown and index > 0)
        state["down"].set_sensitive(shown and 0 <= index < len(order) - 1)

    # ── handlers ─────────────────────────────────────────────────

    def _section_of(self, mid: str) -> str:
        for s in SECTION_ORDER:
            if mid in self._order.get(s, []):
                return s
        return "center"

    def _on_show(self, check: Gtk.CheckButton, mid: str) -> None:
        if check.get_active():
            self._hidden.discard(mid)
        else:
            self._hidden.add(mid)
        self._update_row_state(mid)

    def _on_position(self, btn: Gtk.ToggleButton, mid: str, section: str) -> None:
        if not btn.get_active():
            return
        for s in SECTION_ORDER:
            if mid in self._order.get(s, []):
                self._order[s].remove(mid)
        self._order.setdefault(section, []).append(mid)
        self._update_row_state(mid)

    def _on_move(self, _button, mid: str, delta: int) -> None:
        section = self._section_of(mid)
        order = self._order.get(section, [])
        if mid not in order:
            return
        index = order.index(mid)
        target = index + delta
        if 0 <= target < len(order):
            order[index], order[target] = order[target], order[index]
        self._update_row_state(mid)

    def _on_apply(self, *_args) -> None:
        # theme
        source = self._active_source()
        self._actions["set_source"](source)
        if source == "waybar":
            self._actions["set_waybar_theme"](self._get_imported_theme())

        # layout
        layout = {
            s: [mid for mid in self._order.get(s, []) if mid not in self._hidden]
            for s in SECTION_ORDER
        }
        self._actions["apply_layout"](layout)

        # width / align / height / position / opacity
        width = self._width.get_text().strip() or "100%"
        self._actions["set_width"](width)
        self._actions["set_align"](self._active_align())
        height = str(int(self._height.get_value()))
        self._actions["set_height"](height)
        self._actions["set_position"](self._active_position())
        self._actions["set_opacity"](str(self._active_opacity()))
        self._actions["set_font"](self._font_family.get_text().strip())
        self._actions["set_font_size"](str(int(self._font_size.get_value())))

    def _on_reset(self, *_args) -> None:
        self._actions["reset_layout"]()
        self._order = {
            s: list(DEFAULT_LAYOUT[s]) for s in SECTION_ORDER
        }
        self._hidden = {
            mid for mid in MODULE_IDS
            if mid not in {m for s in self._order.values() for m in s}
        }
        for mid in MODULE_IDS:
            if mid in self._rows:
                self._update_row_state(mid)

    # ── read current widget state ───────────────────────────────

    def _active_source(self) -> str:
        for key, btn in self._source_buttons.items():
            if btn.get_active():
                return key
        return "pywal"

    def _active_align(self) -> str:
        for s, btn in self._align_buttons.items():
            if btn.get_active():
                return s
        return "center"

    def _active_position(self) -> str:
        for key, btn in self._position_buttons.items():
            if btn.get_active():
                return key
        return "bottom"

    def _active_opacity(self) -> float:
        text = self._opacity.get_text().strip().rstrip("%")
        try:
            return max(0.0, min(1.0, float(text) / 100.0))
        except (TypeError, ValueError):
            return 0.95

    def _get_imported_theme(self) -> str:
        for name, btn in self._theme_buttons.items():
            if btn.get_active():
                return name
        return ""

    def _update_source_state(self) -> None:
        source = self._active_source()
        for btn in self._theme_buttons.values():
            btn.set_sensitive(source == "waybar")

    def _on_source_toggled(self, btn, *_args) -> None:
        if btn.get_active():
            self._update_source_state()

    def _on_theme_toggled(self, btn: Gtk.CheckButton, name: str) -> None:
        if not btn.get_active():
            return
        for other in self._theme_buttons.values():
            if other is not btn:
                other.handler_block_by_func(self._on_theme_toggled)
                other.set_active(False)
                other.handler_unblock_by_func(self._on_theme_toggled)

    def _refresh_themes(self, select: str | None = None) -> None:
        for child in self._themes_box.get_children():
            self._themes_box.remove(child)
        self._theme_buttons = {}
        self._themes = list_themes()
        if not self._themes:
            label = Gtk.Label(label="No themes imported yet — use Import…", xalign=0)
            label.set_opacity(0.7)
            self._themes_box.pack_start(label, False, False, 0)
        else:
            for name in self._themes:
                btn = Gtk.CheckButton(label=name)
                btn.set_active(name == select)
                btn.connect("toggled", self._on_theme_toggled, name)
                self._theme_buttons[name] = btn
                self._themes_box.pack_start(btn, False, False, 0)
        self._themes_box.show_all()
        self._update_source_state()

    def _on_import(self, *_args) -> None:
        chooser = Gtk.FileChooserNative.new(
            "Import theme folder",
            self,
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
                        self._refresh_themes(select=name)
                        for key, btn in self._source_buttons.items():
                            btn.set_active(key == "waybar")
                        self._update_source_state()
                        self._actions["set_source"]("waybar")
                        self._actions["set_waybar_theme"](name)
            dialog.destroy()

        chooser.connect("response", on_response)
        chooser.show()