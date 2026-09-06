"""Mission Center-style system monitor dialog for hyprtk-bar.

Opened by left-clicking the sysmon module: a layer-shell panel floated above the
bar with a sidebar of resource pages (CPU / Memory / Disks / Network / GPU /
Apps) and live cairo graphs + readouts. All colours come from the bar's palette
(pywal / imported waybar theme / manual) so the panel always matches the bar.
"""
from __future__ import annotations

import logging
import threading

import gi
gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk  # noqa: E402

from . import monitor_data  # noqa: E402
from .config import PYWAL_PATH, load_pywal_colors  # noqa: E402
from .graphs import HistoryGraph, core_colors  # noqa: E402
from .popup import Popup  # noqa: E402
from .theme import resolve_palette  # noqa: E402
from .widgets import Glyph, HoverButton  # noqa: E402

log = logging.getLogger("hyprtk_bar.monitor")

PAGES = [
    ("cpu", "\uf2db", "CPU"),          # fa-microchip
    ("memory", "\uf1c0", "Memory"),    # fa-database
    ("disks", "\uf0a0", "Disks"),      # fa-hdd-o
    ("network", "\uf1eb", "Network"),  # fa-wifi
    ("gpu", "\uf03d", "GPU"),          # fa-video-camera
    ("apps", "\uf0ae", "Apps"),        # fa-tasks
]

# Per-page graph colours come from the pywal palette (matching the waybar-era
# colour assignments) and fall back to the bar accent when pywal is absent.
_PAGE_PYWAL_KEYS = {
    "cpu": "color5",
    "memory": "color4",
    "disks": "color3",
    "network": "color2",
    "gpu": "color6",
}

_PAGE_TITLES = {key: label for key, _glyph, label in PAGES}

POLL_SECONDS = 1
DIALOG_WIDTH = 940
DIALOG_HEIGHT = 640
APP_ROWS = 15


class GraphCard(Gtk.Box):
    """A titled history graph with a live value readout."""

    def __init__(self, cfg: dict, title: str, color_key: str,
                 height: int = 56, scale: float | None = 100.0,
                 multi: bool = False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.color_key = color_key
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label = Gtk.Label(label=title, xalign=0)
        label.get_style_context().add_class("mc-graph-title")
        head.pack_start(label, True, True, 0)
        self.value = Gtk.Label(label="--", xalign=1)
        self.value.get_style_context().add_class("mc-graph-value")
        head.pack_start(self.value, False, False, 0)
        self.pack_start(head, False, False, 0)
        data_points = (cfg.get("sysmon") or {}).get("data_points", 60)
        self.graph = HistoryGraph(
            color="#7aa2f7",
            height=height,
            max_points=data_points,
            scale=scale,
            multi=multi,
        )
        self.pack_start(self.graph, False, False, 0)

    def set_graph_color(self, color: str) -> None:
        self.graph.set_color(color)


class CoreList(Gtk.Box):
    """Per-core/thread usage laid out in a 2-column grid (no scrolling needed).

    Each core gets a thin progress bar + live %. The grid height is sized to
    the current core count so every core is visible at once; it only scrolls
    on absurdly large core counts that cannot fit the fixed panel.
    """

    ROW_HEIGHT = 20
    MAX_HEIGHT = 300

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label = Gtk.Label(label="Cores / Threads", xalign=0)
        label.get_style_context().add_class("mc-graph-title")
        head.pack_start(label, True, True, 0)
        self._count = Gtk.Label(label="", xalign=1)
        self._count.get_style_context().add_class("mc-stat-value")
        head.pack_start(self._count, False, False, 0)
        self.pack_start(head, False, False, 0)

        self._rows: list[tuple[Gtk.Label, Gtk.ProgressBar, Gtk.Label]] = []
        self._grid = Gtk.Grid(row_spacing=2, column_spacing=20)
        self._scroller = Gtk.ScrolledWindow()
        self._scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroller.add(self._grid)
        self.pack_start(self._scroller, True, True, 0)

    def update(self, pcts: list[float]) -> None:
        n = len(pcts)
        while len(self._rows) < n:
            self._rows.append(self._make_row(len(self._rows)))
        for i, pct in enumerate(pcts):
            lbl, bar, val = self._rows[i]
            lbl.set_text(f"Core {i}")
            bar.set_fraction(max(0.0, min(float(pct) / 100.0, 1.0)))
            val.set_text(f"{pct:.0f}%")
        for i in range(n, len(self._rows)):
            row = self._rows[i][0].get_parent()
            if row is not None:
                row.hide()
        self._count.set_text(f"{n} threads")
        rows_needed = (n + 1) // 2
        height = min(self.MAX_HEIGHT, 14 + rows_needed * self.ROW_HEIGHT)
        self._scroller.set_size_request(-1, max(60, height))
        self._grid.show_all()

    def _make_row(self, index: int) -> tuple[Gtk.Label, Gtk.ProgressBar, Gtk.Label]:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl = Gtk.Label(label=f"Core {index}", xalign=0)
        lbl.set_width_chars(6)
        lbl.get_style_context().add_class("mc-stat-label")
        row.pack_start(lbl, False, False, 0)
        bar = Gtk.ProgressBar()
        bar.get_style_context().add_class("mc-core-bar")
        bar.set_hexpand(True)
        bar.set_show_text(False)
        row.pack_start(bar, True, True, 0)
        val = Gtk.Label(label="--%", xalign=1)
        val.set_width_chars(4)
        val.get_style_context().add_class("mc-stat-value")
        row.pack_start(val, False, False, 0)
        self._grid.attach(row, index % 2, index // 2, 1, 1)
        return lbl, bar, val


class DimmSection(Gtk.Box):
    """Memory slot layout graphic: one card per DIMM slot (populated + size).

    Data comes from SMBIOS via dmidecode; the fetch needs root, so it is done
    once through sudo/pkexec (cached to ~/.cache/hyprtk-bar/dimm.json) in a
    background thread when the dialog is first opened — never at bar startup.
    """

    def __init__(self, cfg: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._cfg = cfg
        self._fetching = False
        self._rendered = False

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="Memory Slots", xalign=0)
        title.get_style_context().add_class("mc-graph-title")
        head.pack_start(title, True, True, 0)
        self._summary = Gtk.Label(label="", xalign=1)
        self._summary.get_style_context().add_class("mc-stat-value")
        head.pack_start(self._summary, False, False, 0)
        refresh = Gtk.Button()
        refresh.get_style_context().add_class("mc-close")
        refresh.set_relief(Gtk.ReliefStyle.NONE)
        refresh.set_tooltip_text("Re-read DIMM slots")
        glyph = Glyph("\uf021", "mc-icon")  # fa-refresh
        glyph.set_pixel_size(12)
        refresh.add(glyph)
        refresh.connect("clicked", lambda *_: self.ensure_loaded(force=True))
        head.pack_start(refresh, False, False, 0)
        self.pack_start(head, False, False, 0)

        self._status = Gtk.Label(label="", xalign=0)
        self._status.get_style_context().add_class("mc-unavailable")
        self.pack_start(self._status, False, False, 0)

        self._slot_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._slot_box.set_hexpand(True)
        self.pack_start(self._slot_box, False, False, 0)

    def ensure_loaded(self, force: bool = False) -> None:
        """Fetch + render the slot graphic if not already shown (idempotent)."""
        if self._rendered and not force:
            return
        if self._fetching:
            return
        if not force:
            cached = monitor_data.dimm_slots(use_cache=True)
            if cached:
                self._render(cached)
                return
        self._fetching = True
        self._status.set_text("Reading DIMM slots\u2026")
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self) -> None:
        slots = monitor_data.dimm_slots(use_cache=False)
        GLib.idle_add(self._on_fetch_done, slots)

    def _on_fetch_done(self, slots) -> bool:
        self._fetching = False
        if slots:
            self._render(slots)
        else:
            self._status.set_text("DIMM info unavailable \u2014 click refresh")
        return GLib.SOURCE_REMOVE

    def _render(self, slots: list[dict]) -> None:
        self._rendered = True
        self._status.set_text("")
        for child in list(self._slot_box.get_children()):
            self._slot_box.remove(child)
        populated = sum(1 for s in slots if s["populated"])
        total = sum(s["size_gb"] or 0 for s in slots)
        self._summary.set_text(f"{populated} populated \u00b7 {total:.0f} GB")
        for slot in slots:
            self._slot_box.pack_start(self._make_card(slot), True, True, 0)
        self._slot_box.show_all()

    @staticmethod
    def _make_card(slot: dict) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        card.set_size_request(-1, 58)
        ctx = card.get_style_context()
        ctx.add_class("dimm-slot")
        ctx.add_class("populated" if slot["populated"] else "empty")
        size_label = Gtk.Label(label="", xalign=0.5)
        size_label.get_style_context().add_class("dimm-size")
        loc_label = Gtk.Label(label="", xalign=0.5)
        loc_label.get_style_context().add_class("dimm-loc")
        card.pack_start(size_label, True, True, 0)
        card.pack_start(loc_label, False, False, 0)
        if slot["populated"]:
            size_label.set_text(f"{slot['size_gb']:.0f} GB")
        else:
            size_label.set_text("Empty")
        loc_label.set_text(slot["locator"])
        return card


class Readouts(Gtk.Grid):
    """A two-column grid of (icon, label, value) rows."""

    def __init__(self):
        super().__init__(row_spacing=6, column_spacing=28)
        self.vals: dict[str, Gtk.Label] = {}
        self._index = 0

    def add(self, key: str, glyph: str, label: str) -> None:
        cell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Glyph(glyph, "mc-icon")
        icon.set_pixel_size(14)
        cell.pack_start(icon, False, False, 0)
        lbl = Gtk.Label(label=label, xalign=0)
        lbl.get_style_context().add_class("mc-stat-label")
        cell.pack_start(lbl, True, True, 0)
        val = Gtk.Label(label="--", xalign=1)
        val.get_style_context().add_class("mc-stat-value")
        cell.pack_start(val, False, False, 0)
        self.attach(cell, self._index % 2, self._index // 2, 1, 1)
        self._index += 1
        self.vals[key] = val


class SysMonitorDialog(Popup):
    """The Mission Center-style panel: sidebar + per-page graphs/readouts."""

    def __init__(self, cfg: dict):
        super().__init__(cfg, cfg.get("position", "bottom"))
        self._cfg = cfg
        self._timer = None
        self._active = ""
        self._cards: dict[str, GraphCard] = {}
        self._stat_vals: dict[str, Gtk.Label] = {}
        self._side_buttons: dict[str, HoverButton] = {}
        self._graph_color: dict[str, str] = {}
        self._last_wal_mtime = None
        self._gpu_unavailable = None
        self._apps_store = None

        self._samplers = {
            "cpu": monitor_data.CpuSampler(),
            "disk": monitor_data.DiskSampler(
                (str((cfg.get("sysmon") or {}).get("disk_path", "/")),)
            ),
            "net": monitor_data.NetSampler(
                str((cfg.get("sysmon") or {}).get("network_iface", "auto"))
            ),
        }
        self._built_pages = set(self._pages_enabled())

        self._refresh_colors(force=True)

        # Fixed panel size: content natural size must never resize the popup.
        self._fixed_size = (DIALOG_WIDTH, DIALOG_HEIGHT)
        self.set_size_request(DIALOG_WIDTH, DIALOG_HEIGHT)
        self.content.set_size_request(DIALOG_WIDTH, DIALOG_HEIGHT)

        # ── header ────────────────────────────────────────────────
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="System Monitor", xalign=0)
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
            if key not in self._pages_enabled():
                continue
            sidebar.pack_start(self._build_side_button(key, glyph, label),
                               False, False, 0)
            self._stack.add_named(self._build_page(key), key)

        body.pack_start(sidebar, False, False, 0)
        body.pack_start(self._stack, True, True, 0)
        self.content.pack_start(body, True, True, 0)

        self._set_active(self._pages_enabled()[0])
        self.content.show_all()

    # ── config ────────────────────────────────────────────────────

    def _pages_enabled(self) -> list[str]:
        pages = (self._cfg.get("sysmon") or {}).get("pages")
        allowed = {p[0] for p in PAGES}
        if isinstance(pages, list):
            clean = [p for p in pages if p in allowed]
            if clean:
                return clean
        return [p[0] for p in PAGES]

    # ── sidebar ───────────────────────────────────────────────────

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
            self.refresh()

    def _set_active(self, key: str) -> None:
        self._active = key
        for k, btn in self._side_buttons.items():
            box = btn.box
            if k == key:
                box.get_style_context().add_class("active")
            else:
                box.get_style_context().remove_class("active")
        self._stack.set_visible_child_name(key)

    # ── pages ─────────────────────────────────────────────────────

    def _build_page(self, key: str) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_hexpand(True)
        page_title = Gtk.Label(label=_PAGE_TITLES[key], xalign=0)
        page_title.get_style_context().add_class("mc-page-title")
        page.pack_start(page_title, False, False, 0)

        if key == "cpu":
            self._build_cpu_page(page)
        elif key == "memory":
            self._build_memory_page(page)
        elif key == "disks":
            self._build_disks_page(page)
        elif key == "network":
            self._build_network_page(page)
        elif key == "gpu":
            self._build_gpu_page(page)
        elif key == "apps":
            self._build_apps_page(page)
        return page

    def _build_cpu_page(self, page: Gtk.Box) -> None:
        self._cards["cpu"] = GraphCard(
            self._cfg, "CPU usage (all threads)", "cpu", scale=100.0, multi=True
        )
        page.pack_start(self._cards["cpu"], False, False, 0)
        self._cards["cpu_temp"] = GraphCard(
            self._cfg, "Temperature", "cpu", height=40, scale=None
        )
        page.pack_start(self._cards["cpu_temp"], False, False, 0)

        stats = Readouts()
        stats.add("load", "\uf0e4", "Load average")
        stats.add("procs", "\uf0ae", "Processes")
        stats.add("threads", "\uf1b3", "Threads")
        stats.add("uptime", "\uf017", "Uptime")
        stats.add("freq", "\uf2db", "Current frequency")
        stats.add("freq_max", "\uf2db", "Max frequency")
        stats.add("temp", "\uf2c9", "CPU temperature")
        stats.add("model", "\uf2db", "Model")
        page.pack_start(stats, False, False, 0)
        self._stat_vals.update(stats.vals)

        self._core_list = CoreList()
        page.pack_start(self._core_list, False, False, 0)

    def _build_memory_page(self, page: Gtk.Box) -> None:
        self._cards["mem"] = GraphCard(self._cfg, "Memory usage", "memory", scale=100.0)
        page.pack_start(self._cards["mem"], False, False, 0)
        self._cards["swap"] = GraphCard(
            self._cfg, "Swap", "memory", height=40, scale=100.0
        )
        page.pack_start(self._cards["swap"], False, False, 0)

        stats = Readouts()
        stats.add("used", "\uf1c0", "Used")
        stats.add("total", "\uf1c0", "Total")
        stats.add("avail", "\uf1c0", "Available")
        stats.add("buffers", "\uf187", "Buffers")
        stats.add("cached", "\uf07c", "Cached")
        stats.add("swap_used", "\uf0ec", "Swap used")
        stats.add("swap_total", "\uf0ec", "Swap total")
        page.pack_start(stats, False, False, 0)
        self._stat_vals.update(stats.vals)

        self._dimm = DimmSection(self._cfg)
        page.pack_start(self._dimm, False, False, 0)

    def _build_disks_page(self, page: Gtk.Box) -> None:
        self._cards["disk_usage"] = GraphCard(
            self._cfg, "Disk usage", "disks", scale=100.0
        )
        page.pack_start(self._cards["disk_usage"], False, False, 0)
        self._cards["disk_read"] = GraphCard(
            self._cfg, "Read rate", "disks", height=40, scale=None
        )
        page.pack_start(self._cards["disk_read"], False, False, 0)
        self._cards["disk_write"] = GraphCard(
            self._cfg, "Write rate", "disks", height=40, scale=None
        )
        page.pack_start(self._cards["disk_write"], False, False, 0)

        stats = Readouts()
        stats.add("disk_used", "\uf0a0", "Used")
        stats.add("disk_rate", "\uf0ec", "Total I/O")
        stats.add("devices", "\uf0a0", "Devices")
        page.pack_start(stats, False, False, 0)
        self._stat_vals.update(stats.vals)

    def _build_network_page(self, page: Gtk.Box) -> None:
        self._cards["net_down"] = GraphCard(
            self._cfg, "Download", "network", scale=None
        )
        page.pack_start(self._cards["net_down"], False, False, 0)
        self._cards["net_up"] = GraphCard(
            self._cfg, "Upload", "network", height=40, scale=None
        )
        page.pack_start(self._cards["net_up"], False, False, 0)

        stats = Readouts()
        stats.add("iface", "\uf1eb", "Interface")
        stats.add("type", "\uf1eb", "Type")
        stats.add("ip", "\uf1eb", "IP address")
        stats.add("down", "\uf0ab", "Download")
        stats.add("up", "\uf0aa", "Upload")
        page.pack_start(stats, False, False, 0)
        self._stat_vals.update(stats.vals)

    def _build_gpu_page(self, page: Gtk.Box) -> None:
        self._cards["gpu_util"] = GraphCard(
            self._cfg, "GPU usage", "gpu", scale=100.0
        )
        page.pack_start(self._cards["gpu_util"], False, False, 0)
        self._cards["gpu_vram"] = GraphCard(
            self._cfg, "VRAM", "gpu", height=40, scale=100.0
        )
        page.pack_start(self._cards["gpu_vram"], False, False, 0)

        unavailable = Gtk.Label(label="GPU monitoring unavailable", xalign=0)
        unavailable.get_style_context().add_class("mc-unavailable")
        unavailable.set_visible(False)
        self._gpu_unavailable = unavailable
        page.pack_start(unavailable, False, False, 0)

        stats = Readouts()
        stats.add("gpu_util", "\uf03d", "Utilization")
        stats.add("gpu_vram", "\uf03d", "VRAM")
        stats.add("gpu_temp", "\uf2c9", "Temperature")
        stats.add("power", "\uf0e7", "Power")
        stats.add("fan", "\uf021", "Fan")
        page.pack_start(stats, False, False, 0)
        self._stat_vals.update(stats.vals)

    def _build_apps_page(self, page: Gtk.Box) -> None:
        self._apps_store = Gtk.ListStore(str, str, str)
        tree = Gtk.TreeView(model=self._apps_store)
        tree.get_style_context().add_class("mc-tree")
        for i, title in enumerate(("Process", "CPU", "Memory")):
            renderer = Gtk.CellRendererText()
            if i:
                renderer.set_property("xalign", 1)
            col = Gtk.TreeViewColumn(title, renderer, text=i)
            col.set_expand(i == 0)
            if i:
                col.set_alignment(1)
            tree.append_column(col)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add(tree)
        page.pack_start(scroll, True, True, 0)

    # ── theming ───────────────────────────────────────────────────

    def _wal_mtime(self):
        try:
            return PYWAL_PATH.stat().st_mtime
        except OSError:
            return None

    def _refresh_colors(self, force: bool = False) -> None:
        """Re-derive per-page graph colours when the wallpaper palette changes."""
        mtime = self._wal_mtime()
        if not force and mtime == self._last_wal_mtime:
            return
        self._last_wal_mtime = mtime
        palette = resolve_palette(self._cfg)
        accent = palette.get("accent", "#7aa2f7")
        pywal = load_pywal_colors() or {}
        self._graph_color = {
            key: pywal.get(pk) or accent
            for key, pk in _PAGE_PYWAL_KEYS.items()
        }
        for card in self._cards.values():
            card.set_graph_color(self._graph_color.get(card.color_key, accent))

    # ── per-page updates ──────────────────────────────────────────

    @staticmethod
    def _level_label(label: Gtk.Label, pct: float) -> None:
        ctx = label.get_style_context()
        if pct >= 90:
            ctx.add_class("high")
            ctx.remove_class("warn")
        elif pct >= 70:
            ctx.add_class("warn")
            ctx.remove_class("high")
        else:
            ctx.remove_class("high")
            ctx.remove_class("warn")

    def _update_cpu(self, data: dict) -> None:
        if "cpu" in self._cards:
            card = self._cards["cpu"]
            cores = data["cores"]
            accent = self._graph_color.get("cpu") or "#7aa2f7"
            colors = core_colors(accent, len(cores))
            card.graph.set_series_colors(
                {f"core{i}": c for i, c in enumerate(colors)}
            )
            card.graph.push_many({f"core{i}": v for i, v in enumerate(cores)})
            card.value.set_text(f"{data['overall']:.0f}%")
            self._level_label(card.value, data["overall"])

        temp = data.get("temp_c")
        if "cpu_temp" in self._cards:
            if temp is not None:
                self._cards["cpu_temp"].graph.push(temp)
                self._cards["cpu_temp"].value.set_text(f"{temp:.0f}\u00b0C")

        self._stat_vals["load"].set_text(
            f"{data['load'][0]:.2f} {data['load'][1]:.2f} {data['load'][2]:.2f}"
        )
        self._stat_vals["procs"].set_text(str(data["processes"]))
        self._stat_vals["threads"].set_text(str(data["threads"]))
        self._stat_vals["uptime"].set_text(monitor_data.fmt_uptime(data["uptime_s"]))
        self._stat_vals["freq"].set_text(
            f"{data['freq_mhz']:,} MHz" if data["freq_mhz"] else "--"
        )
        self._stat_vals["freq_max"].set_text(
            f"{data['freq_max_mhz']:,} MHz" if data["freq_max_mhz"] else "--"
        )
        self._stat_vals["temp"].set_text(
            f"{temp:.0f}\u00b0C" if temp is not None else "--"
        )
        self._stat_vals["model"].set_text(data["model"] or "--")

        core_list = getattr(self, "_core_list", None)
        if core_list is not None:
            core_list.update(data["cores"])

    def _update_memory(self, data: dict) -> None:
        self._cards["mem"].graph.push(data["used_pct"])
        self._cards["mem"].value.set_text(f"{data['used_pct']:.0f}%")
        self._level_label(self._cards["mem"].value, data["used_pct"])
        self._cards["swap"].graph.push(data["swap_pct"])
        self._cards["swap"].value.set_text(f"{data['swap_pct']:.0f}%")
        self._stat_vals["used"].set_text(f"{data['used_gb']:.1f} / {data['total_gb']:.1f} GB")
        self._stat_vals["total"].set_text(f"{data['total_gb']:.1f} GB")
        self._stat_vals["avail"].set_text(f"{data['avail_gb']:.1f} GB")
        self._stat_vals["buffers"].set_text(f"{data['buffers_gb']:.2f} GB")
        self._stat_vals["cached"].set_text(f"{data['cached_gb']:.2f} GB")
        self._stat_vals["swap_used"].set_text(f"{data['swap_used_gb']:.2f} GB")
        self._stat_vals["swap_total"].set_text(f"{data['swap_total_gb']:.2f} GB")

    def _update_disks(self, data: dict) -> None:
        self._cards["disk_usage"].graph.push(data["used_pct"])
        self._cards["disk_usage"].value.set_text(f"{data['used_pct']:.0f}%")
        self._level_label(self._cards["disk_usage"].value, data["used_pct"])
        self._cards["disk_read"].graph.push(data["read_bps"])
        self._cards["disk_read"].value.set_text(monitor_data.fmt_rate(data["read_bps"]))
        self._cards["disk_write"].graph.push(data["write_bps"])
        self._cards["disk_write"].value.set_text(monitor_data.fmt_rate(data["write_bps"]))
        self._stat_vals["disk_used"].set_text(
            f"{data['used_gb']:.1f} / {data['total_gb']:.1f} GB"
        )
        total_io = sum(d["read_bps"] + d["write_bps"] for d in data["devices"])
        self._stat_vals["disk_rate"].set_text(monitor_data.fmt_rate(total_io))
        self._stat_vals["devices"].set_text(
            ", ".join(d["name"] for d in data["devices"]) or "--"
        )

    def _update_network(self, data: dict) -> None:
        self._cards["net_down"].graph.push(data["down_bps"])
        self._cards["net_down"].value.set_text(monitor_data.fmt_rate(data["down_bps"]))
        self._cards["net_up"].graph.push(data["up_bps"])
        self._cards["net_up"].value.set_text(monitor_data.fmt_rate(data["up_bps"]))
        self._stat_vals["iface"].set_text(data["iface"] or "--")
        self._stat_vals["type"].set_text(data["type"] or "--")
        self._stat_vals["ip"].set_text(data["ip"] or "--")
        self._stat_vals["down"].set_text(monitor_data.fmt_rate(data["down_bps"]))
        self._stat_vals["up"].set_text(monitor_data.fmt_rate(data["up_bps"]))

    def _update_gpu(self, data: dict | None) -> None:
        if data is None:
            if self._gpu_unavailable is not None:
                self._gpu_unavailable.show()
            return
        if self._gpu_unavailable is not None:
            self._gpu_unavailable.hide()
        self._cards["gpu_util"].graph.push(data["util_pct"])
        self._cards["gpu_util"].value.set_text(f"{data['util_pct']:.0f}%")
        self._level_label(self._cards["gpu_util"].value, data["util_pct"])
        vram_pct = 0.0
        if data["vram_total_gb"]:
            vram_pct = 100.0 * data["vram_used_gb"] / data["vram_total_gb"]
        self._cards["gpu_vram"].graph.push(vram_pct)
        self._cards["gpu_vram"].value.set_text(
            f"{data['vram_used_gb']:.1f} / {data['vram_total_gb']:.1f} GB"
        )
        self._stat_vals["gpu_util"].set_text(f"{data['util_pct']:.0f}%")
        self._stat_vals["gpu_vram"].set_text(
            f"{data['vram_used_gb']:.1f} / {data['vram_total_gb']:.1f} GB"
        )
        temps = data.get("temps") or {}
        temp = temps.get("edge") or temps.get("junction") or temps.get("temp")
        self._stat_vals["gpu_temp"].set_text(
            f"{temp:.0f}\u00b0C" if temp is not None else "--"
        )
        power = data.get("power_w")
        self._stat_vals["power"].set_text(
            f"{power:.0f} W" if power is not None else "--"
        )
        fan = data.get("fan_rpm")
        self._stat_vals["fan"].set_text(f"{fan} RPM" if fan is not None else "--")

    def _update_apps(self) -> None:
        if self._apps_store is None:
            return
        rows = monitor_data.top_processes(APP_ROWS)
        self._apps_store.clear()
        for r in rows:
            mem = monitor_data.fmt_bytes(r["mem"]) if r["mem"] > 0 else "--"
            self._apps_store.append([r["name"], f"{r['cpu']:.1f}", mem])

    # ── refresh ───────────────────────────────────────────────────

    def refresh(self) -> None:
        self._refresh_colors()
        built = self._built_pages
        if "cpu" in built:
            self._update_cpu(self._samplers["cpu"].sample())
        if "memory" in built:
            self._update_memory(monitor_data.memory())
        if "disks" in built:
            self._update_disks(self._samplers["disk"].sample())
        if "network" in built:
            self._update_network(self._samplers["net"].sample())
        if "gpu" in built:
            self._update_gpu(monitor_data.gpu())
        if self._active == "apps" and "apps" in built:
            self._update_apps()

    # ── lifecycle ─────────────────────────────────────────────────

    def show_above(self, widget) -> None:
        self.refresh()
        self._start_poll()
        super().show_above(widget)
        # First open: lazily read the DIMM slots (may prompt via pkexec once).
        dimm = getattr(self, "_dimm", None)
        if dimm is not None:
            dimm.ensure_loaded()

    def hide_popup(self) -> None:
        self._stop_poll()
        super().hide_popup()

    def _start_poll(self) -> None:
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(POLL_SECONDS, self._on_poll)

    def _stop_poll(self) -> None:
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _on_poll(self) -> bool:
        try:
            self.refresh()
        except Exception:
            log.exception("system monitor refresh failed")
        return GLib.SOURCE_CONTINUE