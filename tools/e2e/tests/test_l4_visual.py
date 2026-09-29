"""L4 · visual captures — grim a PNG per surface and embed it in the report.

No golden diff (headless llvmpipe is not pixel-stable). The captures are for
human review: a layout/regression eyeball, attached next to the parity result so
a reviewer can see exactly what GTK3 vs GTK4 rendered.
"""
from __future__ import annotations

import pytest


def _capture(screenshot, name):
    try:
        screenshot(name)
    except Exception:
        pass


def test_capture_bar(runtime, screenshot, details):
    from harness.runtime import pump
    pump(120)
    _capture(screenshot, "bar")
    details["surface"] = "bar"


def test_capture_arc_menu(make_runtime, screenshot, details):
    from harness.runtime import pump
    rt = make_runtime()
    rt.arc_win.toggle()
    pump(200)
    _capture(screenshot, "arc-menu")
    details["surface"] = "arc menu"


def test_capture_start_menu(make_runtime, screenshot, details):
    from harness.runtime import pump
    rt = make_runtime()
    rt.menu_win.toggle()
    pump(200)
    _capture(screenshot, "start-menu")
    details["surface"] = "start menu"


@pytest.mark.parametrize("page", ["bar", "themes", "modules", "widgets"])
def test_capture_settings_page(make_runtime, screenshot, page, details):
    from harness.runtime import pump
    rt = make_runtime()
    rt.open_settings(page)
    pump(150)
    _capture(screenshot, f"settings-{page}")
    details["surface"] = f"settings/{page}"


def test_capture_desktop_widgets(make_runtime, screenshot, details):
    from harness.runtime import pump
    rt = make_runtime()
    for wid in ("clock", "weather", "resources"):
        rt.cfg["widgets"][wid]["enabled"] = True
    rt.widget_mgr.reload(rt.cfg)
    pump(200)
    _capture(screenshot, "desktop-widgets")
    details["surface"] = "desktop widgets"
