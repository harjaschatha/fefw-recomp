#!/usr/bin/env python3
"""Steam launch wrapper; stdlib only, no root or SteamOS modifications required."""
import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time


def read(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return ""


def number(path, scale=1):
    try:
        return float(read(path)) / scale
    except ValueError:
        return None


class Hardware:
    def __init__(self, root=Path("/")):
        self.root = root
        self.previous_cpu = None
        self.sensors = {}
        for hw in sorted((root / "sys/class/hwmon").glob("hwmon*")):
            name = read(hw / "name") or hw.name
            for pattern, unit, scale in [("temp*_input", "c", 1000),
                                         ("power*_average", "w", 1e6),
                                         ("power*_input", "w", 1e6),
                                         ("fan*_input", "rpm", 1)]:
                for path in sorted(hw.glob(pattern)):
                    stem = path.name.rsplit("_", 1)[0]
                    label = read(hw / (stem + "_label")) or stem
                    key = re.sub(r"[^a-z0-9]+", "_", f"{name}_{label}_{path.name}_{unit}".lower())
                    self.sensors[key] = (path, scale)
        for card in sorted((root / "sys/class/drm").glob("card[0-9]*")):
            if read(card / "device/vendor") == "0x1002":
                self.sensors[f"{card.name}_gpu_busy_percent"] = (card / "device/gpu_busy_percent", 1)
                for clock in ("sclk", "mclk"):
                    self.sensors[f"{card.name}_{clock}_mhz"] = (card / f"device/pp_dpm_{clock}", "clock")
        for bat in sorted((root / "sys/class/power_supply").glob("*")):
            if read(bat / "type") == "Battery":
                for field, scale in [("power_now", 1e6), ("capacity", 1)]:
                    self.sensors[f"{bat.name}_{field}"] = (bat / field, scale)

    def sample(self):
        result = {}
        for key, (path, scale) in self.sensors.items():
            if scale == "clock":
                active = next((line for line in read(path).splitlines() if "*" in line), "")
                match = re.search(r"([\d.]+)\s*Mhz", active, re.I)
                result[key] = float(match[1]) if match else None
            else:
                result[key] = number(path, scale)
        cpu = read(self.root / "proc/stat").splitlines()
        if cpu and cpu[0].startswith("cpu "):
            ticks = list(map(int, cpu[0].split()[1:9]))  # exclude guest, already counted in user/nice
            total, idle = sum(ticks), ticks[3] + ticks[4]
            if self.previous_cpu:
                delta = total - self.previous_cpu[0]
                result["system_cpu_busy_percent"] = 100 * (1 - (idle - self.previous_cpu[1]) / delta) if delta else None
            self.previous_cpu = (total, idle)
        mem = dict(re.findall(r"^(\w+):\s+(\d+)", read(self.root / "proc/meminfo"), re.M))
        if "MemTotal" in mem and "MemAvailable" in mem:
            result["system_ram_used_mib"] = (int(mem["MemTotal"]) - int(mem["MemAvailable"])) / 1024
        freqs = [number(p, 1000) for p in (self.root / "sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq")]
        freqs = [f for f in freqs if f is not None]
        result["cpu_clock_mean_mhz"] = statistics.mean(freqs) if freqs else None
        return result


def aggregate(rows):
    values = {}
    for row in rows:
        for key, value in row.items():
            if isinstance(value, (int, float)) and key != "elapsed_s":
                values.setdefault(key, []).append(value)
    return {key: {"mean": statistics.mean(v), "min": min(v), "max": max(v), "samples": len(v)}
            for key, v in values.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", required=True, type=Path, help="Folder containing fefw.ini and fefw.log")
    parser.add_argument("--output", type=Path, default=Path.home() / "fefw-benchmarks")
    parser.add_argument("--label", default="deck")
    parser.add_argument("--notes", default="", help="Scene, TDP cap, refresh rate, FPS cap, charger state")
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--manual", action="store_true", help="Exclude samples until START file is created; STOP ends measurement")
    parser.add_argument("--delay", type=float, default=0, help="Seconds after launch before automatic measurement")
    parser.add_argument("--duration", type=float, help="Seconds to measure; logging continues until game exit")
    parser.add_argument("--profile", action="store_true", help="Enable frame/GPU pass tracing; CPU stack sampling stays disabled")
    parser.add_argument("--cpu-profile", action="store_true", help="Experimental CPU stack sampling (may crash under Proton); separate from --profile")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.interval < 0.2 or args.delay < 0 or (args.duration is not None and args.duration <= 0):
        parser.error("supply a command after --; interval >= 0.2, delay >= 0, duration > 0")
    game = args.game_dir.expanduser().resolve()
    if not game.is_dir():
        parser.error("--game-dir must be an existing game run folder")
    label = re.sub(r"[^\w.-]+", "-", args.label).strip(".-") or "deck"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = args.output.expanduser().resolve() / f"{stamp}-{label}"
    out.mkdir(parents=True)
    # Stable pointer lets a back-button/keyboard shortcut mark the scene without knowing the timestamp.
    latest = out.parent / "latest"
    if latest.is_symlink():
        latest.unlink()
    if not latest.exists():
        latest.symlink_to(out.name, target_is_directory=True)
    hw = Hardware()
    metadata = {"started_utc": stamp, "label": args.label, "notes": args.notes,
                "command": command, "game_dir": str(game), "profile": args.profile, "cpu_profile": args.cpu_profile,
                "manual_measurement": args.manual, "os_release": read("/etc/os-release"),
                "delay_s": args.delay, "measurement_duration_s": args.duration,
                "kernel": list(os.uname()), "cpu": read("/proc/cpuinfo"),
                "board": read("/sys/class/dmi/id/product_name"),
                "sensors": {k: str(v[0]) for k, v in hw.sensors.items()},
                "environment": {k: os.environ[k] for k in ("SteamDeck", "PROTON_DIR", "STEAM_COMPAT_DATA_PATH", "MANGOHUD_CONFIG") if k in os.environ}}
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2))
    for name in ("fefw.ini", "controls.ini"):
        if (game / name).is_file():
            shutil.copy2(game / name, out / name)
    env = os.environ.copy()
    env["NXRT_GFX_LOG_FPS"] = "1"
    if args.profile:
        env.update(NXRT_PROF_SAMPLE_HZ="0", NXRT_PROF_TRACE="Z:" + str(out / "frame.trace"), NXRT_PROF_GPU_PASSES="1")
        # Supported by the Deck diagnostic runtime; older releases ignore these.
        # Manual markers filter CSVs only, so leave trace timing automatic in manual mode.
        env["NXRT_PROF_DELAY_SEC"] = str(0 if args.manual else args.delay)
        env["NXRT_PROF_DURATION_SEC"] = str(args.duration or 0)
    if args.cpu_profile:
        env.update(NXRT_PROF_SAMPLE_HZ="100", NXRT_PROF_SAMPLE_OUT="Z:" + str(out / "cpu.folded"))
    print(f"Benchmark logs: {out}", flush=True)
    started = time.monotonic()
    wall_start = time.time()
    rows, fps_rows = [], []
    measuring = not args.manual
    measurement_start = None
    stopped = False
    log_offset = 0
    log_identity = None
    pending = ""
    # Never parse a previous run's log if the new command fails before opening one.
    old_log = game / "fefw.log"
    initial_stat = old_log.stat() if old_log.exists() else None
    if initial_stat:
        log_offset = initial_stat.st_size
        log_identity = (initial_stat.st_dev, initial_stat.st_ino)
    fields = ["elapsed_s", "measuring", "system_cpu_busy_percent", "system_ram_used_mib", "cpu_clock_mean_mhz"] + list(hw.sensors)
    exit_code = 1
    interrupted = False
    with (out / "hardware.csv").open("w", newline="") as hardware_file, \
         (out / "fps.csv").open("w", newline="") as fps_file, \
         (out / "runner.log").open("w") as runner_file:
        writer = csv.DictWriter(hardware_file, fieldnames=fields)
        writer.writeheader()
        fps_writer = csv.DictWriter(fps_file, fieldnames=["elapsed_s", "measuring", "fps", "present_pass_gpu_ms"])
        fps_writer.writeheader()
        child = None
        def forward(sig, _frame):
            nonlocal interrupted
            interrupted = True
            if child and child.poll() is None:
                try:
                    os.killpg(child.pid, sig)
                except ProcessLookupError:
                    pass
        old_handlers = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            child = subprocess.Popen(command, env=env, stdout=runner_file, stderr=subprocess.STDOUT, start_new_session=True)
            while True:
                elapsed = time.monotonic() - started
                if args.manual:
                    if (out / "STOP").exists():
                        stopped = True
                    measuring = (out / "START").exists() and not stopped
                else:
                    measuring = elapsed >= args.delay
                if measuring and measurement_start is None:
                    measurement_start = elapsed
                if args.duration is not None and measurement_start is not None and elapsed - measurement_start >= args.duration:
                    measuring = False
                row = {"elapsed_s": round(elapsed, 3), "measuring": int(measuring), **hw.sample()}
                writer.writerow(row)
                hardware_file.flush()
                if measuring:
                    rows.append({k: v for k, v in row.items() if k != "measuring"})
                try:
                    st = old_log.stat()
                    identity = (st.st_dev, st.st_ino)
                    if identity != log_identity or st.st_size < log_offset:
                        log_offset, pending = 0, ""
                    log_identity = identity
                    with old_log.open("rb") as stream:
                        stream.seek(log_offset)
                        chunk = stream.read()
                        log_offset = stream.tell()
                    lines = (pending + chunk.decode("utf-8", errors="replace")).split("\n")
                    pending = lines.pop()
                    for line in lines:
                        match = re.search(r"fps ([\d.]+), present pass GPU ([\d.]+) ms avg", line)
                        if match:
                            fr = {"elapsed_s": round(elapsed, 3), "measuring": int(measuring), "fps": float(match[1]), "present_pass_gpu_ms": float(match[2])}
                            fps_writer.writerow(fr)
                            if measuring:
                                fps_rows.append(fr)
                    fps_file.flush()
                except OSError:
                    pass
                if child.poll() is not None:
                    exit_code = child.returncode
                    break
                time.sleep(args.interval)
        except OSError as error:
            runner_file.write(f"Launch failed: {error}\n")
        finally:
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
    for name in ("fefw.log", "fefw_crash.txt", "fefw_freeze.txt", "fefw_fatal.txt"):
        source = game / name
        if source.is_file() and source.stat().st_mtime >= wall_start:
            shutil.copy2(source, out / name)
    metrics = aggregate(rows)
    metrics.update(aggregate([{k: v for k, v in row.items() if k != "measuring"} for row in fps_rows]))
    summary = {"exit_code": exit_code, "interrupted": interrupted, "duration_s": time.monotonic() - started,
               "measured_hardware_samples": len(rows), "measured_fps_samples": len(fps_rows), "metrics": metrics}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    lines = [f"# Deck benchmark: {args.label}", "", args.notes, "",
             f"Exit code: {exit_code}; duration: {summary['duration_s']:.1f} s; measured hardware samples: {len(rows)}.", "",
             "| Metric | Mean | Min | Max | Samples |", "|---|---:|---:|---:|---:|"]
    for key, value in metrics.items():
        lines.append(f"| {key} | {value['mean']:.2f} | {value['min']:.2f} | {value['max']:.2f} | {value['samples']} |")
    lines += ["", "FPS is sampled once per second, not per-frame; minimum is not a 1% low.",
              "Present-pass GPU time excludes the game's other GPU passes.",
              "Power sensors describe their named device; battery power is whole-device draw on battery, not the TDP cap.",
              "CPU/RAM readings are system-wide. Blank sensors are unavailable, not zero.",
              "Profile mode changes performance. Use separate baseline runs."]
    if not fps_rows:
        lines += ["", "No measured FPS samples: check game-dir, START marker, runtime log, and runner exit status."]
    if not rows:
        lines += ["", "No measurement window was recorded. Create START after loading the save."]
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print(f"Benchmark complete: {out / 'summary.md'}", flush=True)
    return exit_code if exit_code >= 0 else 128 - exit_code


if __name__ == "__main__":
    sys.exit(main())
