"""Pure (no-GTK) data readers for the system monitor dialog.

Everything is plain Python over /proc + /sys so the readers work without a
display and are trivially testable. Every reader is defensive: on any error it
returns a zero/empty value rather than raising. Rate readers (CPU, disk I/O,
network) are sampler classes that keep a previous sample and compute deltas.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

_KB = 1024
_GB = 1024 ** 3

HWMON = Path("/sys/class/hwmon")
DRM = Path("/sys/class/drm")
DIMM_CACHE = Path.home() / ".cache" / "hyprtk-bar" / "dimm.json"
DIMM_TTL = 24 * 3600

_PHYS_DEVICE = re.compile(r"^(sd[a-z]+|nvme\d+n\d+|vd[a-z]+|mmcblk\d+)$")


def _read_text(path) -> str:
    try:
        return Path(path).read_text().strip()
    except (OSError, ValueError):
        return ""


# ── formatting ────────────────────────────────────────────────────

def fmt_bytes(n: float) -> str:
    """Human-readable size (B/KiB/MiB/GiB/TiB)."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        n = 0.0
    n = max(n, 0.0)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    if i == 0:
        return f"{int(n)} B"
    return f"{n:.1f} {units[i]}"


def fmt_rate(bps: float) -> str:
    return fmt_bytes(bps) + "/s"


def fmt_uptime(seconds: float) -> str:
    try:
        seconds = int(float(seconds))
    except (TypeError, ValueError):
        return "--"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}d {hours}h {mins}m"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


# ── CPU ───────────────────────────────────────────────────────────

def _read_cpu_times() -> dict[str, tuple[int, int]]:
    """``/proc/stat`` -> {name: (total_jiffies, idle_jiffies)} for cpu/cpuN."""
    times: dict[str, tuple[int, int]] = {}
    try:
        with open("/proc/stat") as f:
            for line in f:
                parts = line.split()
                if not parts or not parts[0].startswith("cpu"):
                    continue
                vals = [int(v) for v in parts[1:]]
                idle = vals[3] + vals[4]
                times[parts[0]] = (sum(vals), idle)
    except (OSError, ValueError, IndexError):
        pass
    return times


def _loadavg() -> tuple[float, float, float]:
    try:
        fields = Path("/proc/loadavg").read_text().split()
        return (float(fields[0]), float(fields[1]), float(fields[2]))
    except (OSError, ValueError, IndexError):
        return (0.0, 0.0, 0.0)


def _uptime_s() -> float:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def _cpu_freq() -> tuple[int, int]:
    """(current_mhz, max_mhz) from the cpu0 cpufreq sysfs nodes."""
    cur = _read_text("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
    mx = _read_text("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
    try:
        return int(cur) // 1000, int(mx) // 1000
    except ValueError:
        return 0, 0


def _process_count() -> int:
    try:
        return sum(1 for d in os.listdir("/proc") if d.isdigit())
    except OSError:
        return 0


def _thread_count() -> int:
    count = 0
    try:
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            status = Path("/proc", d, "status")
            try:
                for line in status.read_text().splitlines():
                    if line.startswith("Threads:"):
                        count += int(line.split()[1])
                        break
            except (OSError, ValueError, IndexError):
                continue
    except OSError:
        pass
    return count


def hwmon_temps() -> dict[str, float]:
    """All hwmon temps as {label: celsius}."""
    temps: dict[str, float] = {}
    try:
        for hw in HWMON.iterdir():
            name = _read_text(hw / "name")
            if not name:
                continue
            for entry in hw.iterdir():
                if not (entry.name.startswith("temp") and entry.name.endswith("_input")):
                    continue
                try:
                    value = int(entry.read_text().strip()) / 1000.0
                except (OSError, ValueError):
                    continue
                label = name
                lbl = _read_text(entry.with_name(entry.name[:-6] + "_label"))
                if lbl:
                    label = f"{name} {lbl}"
                temps[label] = value
    except OSError:
        pass
    return temps


class CpuSampler:
    """Overall + per-core CPU usage with a process/thread/uptime readout."""

    def __init__(self):
        self._prev: dict[str, tuple[int, int]] = {}
        self._model = self._cpu_model()

    @staticmethod
    def _cpu_model() -> str:
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
        return ""

    def sample(self) -> dict:
        cur = _read_cpu_times()
        prev = self._prev or cur
        self._prev = cur

        def pct(name: str) -> float:
            a, b = cur.get(name), prev.get(name)
            if not a or not b:
                return 0.0
            total = a[0] - b[0]
            if total <= 0:
                return 0.0
            return 100.0 * (total - (a[1] - b[1])) / total

        overall = pct("cpu")
        core_names = sorted(
            (k for k in cur if k.startswith("cpu") and k[3:].isdigit()),
            key=lambda s: int(s[3:]),
        )
        cores = [pct(k) for k in core_names]

        load = _loadavg()
        freq_cur, freq_max = _cpu_freq()
        uptime = _uptime_s()
        processes = _process_count()
        threads = _thread_count()
        temp_c = None
        temps = hwmon_temps()
        for label, value in temps.items():
            low = label.lower()
            if "k10temp" in low or "tctl" in low or "cpu" in low:
                temp_c = value
                break
        return {
            "overall": overall,
            "cores": cores,
            "load": load,
            "processes": processes,
            "threads": threads,
            "uptime_s": uptime,
            "freq_mhz": freq_cur,
            "freq_max_mhz": freq_max,
            "temp_c": temp_c,
            "temps": temps,
            "model": self._model,
        }


# ── memory ────────────────────────────────────────────────────────

def memory() -> dict:
    """RAM + swap usage from /proc/meminfo (values in GB / percent)."""
    data: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                data[key] = int(rest.split()[0])
    except (OSError, ValueError, IndexError):
        pass
    total = data.get("MemTotal", 0)
    if total <= 0:
        return {
            "used_pct": 0.0, "used_gb": 0.0, "total_gb": 0.0, "avail_gb": 0.0,
            "buffers_gb": 0.0, "cached_gb": 0.0,
            "swap_pct": 0.0, "swap_used_gb": 0.0, "swap_total_gb": 0.0,
        }
    avail = data.get("MemAvailable", total - data.get("MemFree", 0))
    used = total - avail
    swap_total = data.get("SwapTotal", 0)
    swap_used = swap_total - data.get("SwapFree", swap_total)
    return {
        "used_pct": 100.0 * used / total,
        "used_gb": used * _KB / _GB,
        "total_gb": total * _KB / _GB,
        "avail_gb": avail * _KB / _GB,
        "buffers_gb": data.get("Buffers", 0) * _KB / _GB,
        "cached_gb": data.get("Cached", 0) * _KB / _GB,
        "swap_pct": 100.0 * swap_used / swap_total if swap_total else 0.0,
        "swap_used_gb": swap_used * _KB / _GB,
        "swap_total_gb": swap_total * _KB / _GB,
    }


# ── disk ──────────────────────────────────────────────────────────

def _diskstats() -> dict[str, tuple[int, int]]:
    """``/proc/diskstats`` -> {device: (read_bytes, write_bytes)}."""
    out: dict[str, tuple[int, int]] = {}
    try:
        with open("/proc/diskstats") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 10:
                    continue
                name = parts[2]
                if not _PHYS_DEVICE.match(name):
                    continue
                try:
                    rbytes = int(parts[5]) * 512
                    wbytes = int(parts[9]) * 512
                except ValueError:
                    continue
                out[name] = (rbytes, wbytes)
    except OSError:
        pass
    return out


class DiskSampler:
    """Disk usage of a mount + aggregate read/write transfer rates."""

    def __init__(self, paths=("/",)):
        self._paths = paths
        self._prev: dict[str, tuple[int, int]] = {}

    def sample(self) -> dict:
        cur = _diskstats()
        prev = self._prev or cur
        self._prev = cur
        read_bps = write_bps = 0.0
        devices = []
        for name, (r0, w0) in cur.items():
            p = prev.get(name)
            rd = (r0 - p[0]) if p else 0
            wr = (w0 - p[1]) if p else 0
            devices.append(
                {"name": name, "read_bps": max(rd, 0), "write_bps": max(wr, 0)}
            )
            read_bps += max(rd, 0)
            write_bps += max(wr, 0)

        used_pct = used_gb = total_gb = 0.0
        try:
            usage = shutil.disk_usage(self._paths[0])
            used_pct = 100.0 * usage.used / usage.total
            used_gb = usage.used / _GB
            total_gb = usage.total / _GB
        except (OSError, IndexError):
            pass
        return {
            "used_pct": used_pct,
            "used_gb": used_gb,
            "total_gb": total_gb,
            "read_bps": read_bps,
            "write_bps": write_bps,
            "devices": devices,
        }


# ── network ───────────────────────────────────────────────────────

def _netdev() -> dict[str, tuple[int, int]]:
    """``/proc/net/dev`` -> {iface: (rx_bytes, tx_bytes)}."""
    out: dict[str, tuple[int, int]] = {}
    try:
        with open("/proc/net/dev") as f:
            next(f, None)
            next(f, None)
            for line in f:
                if ":" not in line:
                    continue
                name, rest = line.split(":", 1)
                fields = rest.split()
                if len(fields) < 9:
                    continue
                try:
                    rx, tx = int(fields[0]), int(fields[8])
                except ValueError:
                    continue
                out[name.strip()] = (rx, tx)
    except (OSError, StopIteration):
        pass
    return out


def _iface_ip(iface: str) -> str:
    try:
        out = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", iface],
            capture_output=True, text=True, timeout=3,
        ).stdout
        m = re.search(r"inet\s+(\S+)", out)
        return m.group(1).split("/")[0] if m else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _iface_type(iface: str) -> str:
    if Path("/sys/class/net", iface, "wireless").exists():
        return "Wi-Fi"
    if _read_text(f"/sys/class/net/{iface}/type") == "1":
        return "Ethernet"
    return ""


class NetSampler:
    """Per-interface up/down rates, auto-selecting the active interface."""

    def __init__(self, iface: str = "auto"):
        self._iface = iface
        self._prev: dict[str, tuple[int, int]] = {}

    def _pick(self, rates: dict) -> str:
        if rates:
            best = max(rates, key=lambda n: rates[n][0] + rates[n][1])
            if best != "lo" and rates[best][0] + rates[best][1] > 0:
                return best
        for name in rates:
            if name == "lo":
                continue
            if _read_text(f"/sys/class/net/{name}/operstate") == "up":
                return name
        if "enp7s0" in rates:
            return "enp7s0"
        return next(iter(rates), "")

    def sample(self) -> dict:
        cur = _netdev()
        prev = self._prev or cur
        self._prev = cur
        rates: dict[str, tuple[int, int]] = {}
        for name, (r0, t0) in cur.items():
            p = prev.get(name)
            rates[name] = (max(r0 - p[0], 0), max(t0 - p[1], 0)) if p else (0, 0)

        iface = self._iface
        if iface == "auto" or iface not in rates:
            iface = self._pick(rates)
        down, up = rates.get(iface, (0, 0))
        return {
            "iface": iface,
            "down_bps": down,
            "up_bps": up,
            "ip": _iface_ip(iface),
            "type": _iface_type(iface),
            "all": [
                {"name": n, "down_bps": r[0], "up_bps": r[1]}
                for n, r in rates.items()
            ],
        }


# ── GPU (AMD) ─────────────────────────────────────────────────────

def _find_gpu_dir() -> Path | None:
    """The first ``/sys/class/drm/card*/device`` exposing gpu_busy_percent."""
    try:
        for card in DRM.iterdir():
            name = card.name
            if not name.startswith("card") or not name[4:].isdigit():
                continue
            dev = card / "device"
            if (dev / "gpu_busy_percent").is_file():
                return dev
    except OSError:
        pass
    return None


def _amdgpu_hwmon() -> Path | None:
    try:
        for hw in HWMON.iterdir():
            if _read_text(hw / "name") == "amdgpu":
                return hw
    except OSError:
        pass
    return None


def gpu() -> dict | None:
    """AMD GPU utilization/VRAM/temps/power, or None when not available."""
    dev = _find_gpu_dir()
    if dev is None:
        return None

    def read(path) -> int | None:
        try:
            return int(_read_text(path))
        except ValueError:
            return None

    util = read(dev / "gpu_busy_percent") or 0
    vram_used = read(dev / "mem_info_vram_used")
    vram_total = read(dev / "mem_info_vram_total")

    hw = _amdgpu_hwmon()
    power_w = fan_rpm = fan_max = None
    temps: dict[str, float] = {}
    if hw is not None:
        for entry in hw.iterdir():
            name = entry.name
            if name in ("power1_input", "power1_average"):
                v = read(entry)
                if v is not None:
                    value = v / 1_000_000.0
                    if name == "power1_input" or power_w is None:
                        power_w = value
            elif name == "fan1_input":
                fan_rpm = read(entry)
            elif name == "fan1_max":
                fan_max = read(entry)
            elif name.startswith("temp") and name.endswith("_input"):
                v = read(entry)
                if v is not None:
                    key = "temp"
                    lbl = _read_text(entry.with_name(name[:-6] + "_label")).lower()
                    if "edge" in lbl:
                        key = "edge"
                    elif "junction" in lbl:
                        key = "junction"
                    elif "mem" in lbl:
                        key = "mem"
                    temps[key] = v / 1000.0

    return {
        "util_pct": float(util),
        "vram_used_gb": (vram_used or 0) / _GB,
        "vram_total_gb": (vram_total or 0) / _GB,
        "power_w": power_w,
        "fan_rpm": fan_rpm,
        "fan_max": fan_max,
        "temps": temps,
        "name": _read_text(dev / "product_number") or "",
    }


# ── processes ─────────────────────────────────────────────────────

def _read_pid_cpu(pid: int):
    """(comm, utime+stime) for a pid, or None."""
    try:
        data = Path("/proc", str(pid), "stat").read_text()
    except OSError:
        return None
    idx = data.rfind(")")
    if idx < 0:
        return None
    comm = data[data.find("(") + 1:idx]
    rest = data[idx + 2:].split()
    if len(rest) < 14:
        return None
    try:
        ticks = int(rest[11]) + int(rest[12])
    except ValueError:
        return None
    return comm, ticks


def _read_pid_rss(pid: int) -> int:
    """Resident set size in kB."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def top_processes(n: int = 15) -> list[dict]:
    """Top-N processes by per-core CPU% (two /proc samples ~150ms apart)."""
    ncpu = os.cpu_count() or 1

    def sample() -> tuple[int, dict]:
        total = 1
        try:
            with open("/proc/stat") as f:
                parts = f.readline().split()
            total = sum(int(v) for v in parts[1:])
        except (OSError, ValueError):
            pass
        pids = {}
        try:
            for d in os.listdir("/proc"):
                if not d.isdigit():
                    continue
                pid = int(d)
                info = _read_pid_cpu(pid)
                if info:
                    pids[pid] = info
        except OSError:
            pass
        return max(total, 1), pids

    t1, p1 = sample()
    time.sleep(0.15)
    t2, p2 = sample()
    delta = max(t2 - t1, 1)

    rows = []
    for pid, (comm, ticks) in p2.items():
        first = p1.get(pid)
        if first is None:
            continue
        cpu = 100.0 * ncpu * (ticks - first[1]) / delta
        if cpu < 0.05:
            continue
        rows.append(
            {
                "pid": pid,
                "name": comm,
                "cpu": cpu,
                "mem": _read_pid_rss(pid) * _KB / _GB,
            }
        )
    rows.sort(key=lambda r: r["cpu"], reverse=True)
    return rows[:n]


# ── DIMM slots (SMBIOS via dmidecode) ────────────────────────────

def _dimm_size_gb(size: str) -> float | None:
    """Normalise a dmidecode Size field to GB; None when no module is present."""
    s = (size or "").strip().lower()
    if s in (
        "no module installed",
        "none",
        "not provided",
        "not specified",
        "unknown",
    ):
        return None
    m = re.search(r"([\d.]+)\s*(mib|gib|mb|gb)", s)
    if not m:
        return None
    val = float(m.group(1))
    if m.group(2) in ("mb", "mib"):
        val /= 1024.0
    return val


def parse_dmidecode(text: str) -> list[dict]:
    """Parse ``dmidecode -t 17`` output into a list of DIMM slot dicts.

    Each entry carries ``locator`` (the slot name), ``bank``, ``size`` (raw),
    ``size_gb`` and ``populated`` — empty slots report No Module Installed.
    """
    slots: list[dict] = []
    for block in text.split("Memory Device"):
        size = locator = bank = ""
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("Size:"):
                size = line.split(":", 1)[1].strip()
            elif line.startswith("Locator:"):
                locator = line.split(":", 1)[1].strip()
            elif line.startswith("Bank Locator:"):
                bank = line.split(":", 1)[1].strip()
        if not locator:
            continue
        gb = _dimm_size_gb(size)
        slots.append(
            {
                "locator": locator,
                "bank": bank,
                "size": size or "Unknown",
                "size_gb": gb,
                "populated": gb is not None,
            }
        )
    return slots


def _dimm_cache_fresh() -> bool:
    try:
        return time.time() - DIMM_CACHE.stat().st_mtime < DIMM_TTL
    except OSError:
        return False


def _dimm_read_cache() -> list[dict] | None:
    try:
        data = json.loads(DIMM_CACHE.read_text())
        return data if isinstance(data, list) else None
    except (OSError, json.JSONDecodeError):
        return None


def _dimm_fetch() -> str:
    """Fetch ``dmidecode -t 17`` via sudo -n (fast, non-interactive) then pkexec."""
    for cmd in (
        ["sudo", "-n", "dmidecode", "-t", "17"],
        ["pkexec", "dmidecode", "-t", "17"],
    ):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        except (subprocess.SubprocessError, OSError):
            continue
        if out.returncode == 0 and "Memory Device" in out.stdout:
            return out.stdout
    return ""


def dimm_slots(use_cache: bool = True) -> list[dict] | None:
    """DIMM slot list, or None when unavailable.

    With ``use_cache`` a fresh ~/.cache/hyprtk-bar/dimm.json is served directly
    (no prompt). Otherwise the data is fetched via sudo/pkexec and cached; the
    fetch may show a polkit password dialog, so call it off the UI thread.
    """
    if use_cache:
        if _dimm_cache_fresh():
            cached = _dimm_read_cache()
            if cached:
                return cached
        return None
    text = _dimm_fetch()
    if not text:
        return None
    slots = parse_dmidecode(text)
    try:
        DIMM_CACHE.parent.mkdir(parents=True, exist_ok=True)
        DIMM_CACHE.write_text(json.dumps(slots, indent=2))
    except OSError:
        pass
    return slots


# ── physical drives ──────────────────────────────────────────────

def drives() -> list[dict]:
    """Per-physical-disk info (size, available, type) via ``lsblk -J``.

    Each entry carries ``name``, ``model``, a ``type_key``/``type_label`` and
    a Nerd Font ``glyph`` for NVMe / HDD / SSD / USB / card readers, plus the
    raw ``size_b``/``used_b``/``free_b`` summed over the disk's mounted
    partitions (``mounted``). Empty USB readers report 0 bytes and ``mounted``
    False. Ordered by drive class (NVMe first, readers last).
    """
    try:
        out = subprocess.run(
            ["lsblk", "-J", "-b", "-o",
             "NAME,TYPE,SIZE,FSTYPE,MOUNTPOINT,MODEL,ROTA,TRAN"],
            capture_output=True, text=True, timeout=5,
        )
        data = json.loads(out.stdout)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return []

    def _collect(node, used, free, mounts) -> None:
        for child in node.get("children") or []:
            mp = child.get("mountpoint")
            if mp:
                try:
                    usage = shutil.disk_usage(mp)
                    used.append(usage.used)
                    free.append(usage.free)
                    mounts.append(mp)
                except OSError:
                    pass
            _collect(child, used, free, mounts)

    result = []
    for block in data.get("blockdevices") or []:
        if block.get("type") != "disk":
            continue
        name = block.get("name") or ""
        try:
            size_b = int(block.get("size") or 0)
        except (TypeError, ValueError):
            size_b = 0
        rotational = str(block.get("rota")) in ("1", "True", "true")
        transport = str(block.get("tran") or "")
        model = str(block.get("model") or "").strip()

        used, free, mounts = [], [], []
        _collect(block, used, free, mounts)
        used_b = sum(used)
        free_b = sum(free)
        mounted = bool(mounts)
        is_root = "/" in mounts

        if transport == "nvme":
            type_key, type_label, glyph = "nvme", "NVMe SSD", "\uf2db"
        elif transport == "usb":
            if size_b == 0:
                type_key, type_label, glyph = "reader", "Card reader", "\uf287"
            elif rotational:
                type_key, type_label, glyph = "usb", "USB HDD", "\uf287"
            else:
                type_key, type_label, glyph = "usb", "USB SSD", "\uf287"
        elif rotational:
            type_key, type_label, glyph = "hdd", "HDD", "\uf0a0"
        else:
            type_key, type_label, glyph = "ssd", "SSD", "\uf0e7"

        result.append(
            {
                "name": name,
                "model": model or name,
                "type_key": type_key,
                "type_label": type_label,
                "glyph": glyph,
                "size_b": size_b,
                "used_b": used_b,
                "free_b": free_b,
                "mounted": mounted,
                "is_root": is_root,
            }
        )

    order = {"nvme": 0, "hdd": 1, "ssd": 2, "usb": 3, "reader": 4}
    result.sort(key=lambda d: (order.get(d["type_key"], 9), d["name"]))
    return result