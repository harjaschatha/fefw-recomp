# Steam Deck benchmark logging

Each launch produces a unique run directory under `~/fefw-benchmarks/`, with a
`summary.md` to read afterwards. No root, package installation or SteamOS changes
are required. This uses Python's standard library and readable Linux sensors.

## Install on an existing 0.1.7 package

Copy this folder into the extracted game's `tools/deck/` folder. Future Linux
packages built from this checkout include it. Finish normal game setup and use
the launcher's **Add to Steam** first. Find the **run folder** containing the active
`fefw.ini`, `controls.ini`, and `fefw.log`; it may differ from the package folder.

In Steam, open the game's Properties and set **Launch Options**, replacing both
example paths below. Preserve `%command%` literally, without quotes around it:

```text
"/home/deck/Games/fefw/tools/python/bin/python3" -I "/home/deck/Games/fefw/tools/deck/benchmark.py" --game-dir "/home/deck/Games/fefw" --label "lcd-12w-balanced" --notes "Crowded map; 12 W cap; 60 Hz; Steam cap 30; battery; TAAU 59%; shadows 1024" -- %command%
```

The wrapper inherits Steam's working directory and launches its original Proton
command. It enables the existing runtime FPS log for this run only. Leave the
AppImage closed while playing through the Steam shortcut. Run one benchmark at a
time. Remove the launch options to return to normal launching.

## Measure your demanding save

For a hands-off Game Mode run, insert `--delay 180 --duration 300` before `--` in
the launch options. Load the save and reach the chosen camera view within three
minutes; the summary then measures the next five minutes. Adjust the delay if
needed. Exit normally when finished; the wrapper writes the summary at game exit.
All hardware samples remain in the CSV, with a `measuring` column identifying
the selected window. Loading screens and menus are included unless excluded by
your measurement window. FPS window boundaries are approximate to one log sample.

For precise manual control, use `--manual` instead of `--delay`. After loading the
save, create the START file from a Desktop Mode terminal or an already configured
remote terminal:

```sh
touch ~/fefw-benchmarks/latest/START
```

End measurement before leaving the scene:

```sh
touch ~/fefw-benchmarks/latest/STOP
```

STOP is final for that run. A new launch starts with fresh marker files. You may
combine `--manual` with `--duration 300` to stop measuring automatically five
minutes after START. With no window options, the whole launch is measured.

For useful comparisons:

1. Use the same save, camera, unit count, route and measured duration.
2. Warm up in the scene before measuring; keep charger state and ambient conditions consistent.
3. Record Steam's TDP cap, refresh rate, FPS limit, GPU-clock setting, Proton version,
   game version and graphics settings in `--notes`. These settings cannot all be
   reliably inferred from sensors. Avoid changing them during a run.
4. Begin with the game's 60 and 120 FPS modes disabled for a 30 FPS baseline.
5. Compare one change at a time, for example 50% versus 59% render scale at the
   same TDP. Repeat runs to distinguish a change from normal variation.

## Run artifacts

- `summary.md` / `summary.json`: measured-window mean, minimum and maximum, sample
  counts, duration and command exit status. Printed summary path is in Steam's
  launch output; open `~/fefw-benchmarks/latest/summary.md` in Desktop Mode.
- `hardware.csv`: one-second readings when available: CPU utilisation and clock,
  AMD GPU utilisation and clocks, temperatures, fan RPM, device power, battery
  power and capacity, system RAM use. Sensor names include their hwmon device,
  label and units; metadata maps names to source files.
- `fps.csv`: runtime one-second FPS readings and presentation-pass GPU timing.
- `runner.log`: stdout/stderr from Steam's runner and the game.
- `fefw.log` and fresh crash/freeze/fatal reports from this run, when available.
- `fefw.ini`, `controls.ini`: launch-time settings snapshots, when present.
- `metadata.json`: UTC start, command, OS, kernel, CPU, board, sensor paths and notes.

Blank sensor cells mean unavailable. Power readings are **not the configured TDP
cap**: APU/device sensors and whole-device battery draw measure different things.
Battery readings while charging do not measure total system power. CPU utilisation
and RAM use are system-wide, not game-only. Per-core saturation can be hidden by
the aggregate CPU percentage. Temperatures alone do not prove thermal throttling;
compare clocks, utilisation and power as well.

FPS is a sequence of one-second averages; it cannot provide accurate per-frame
stutter statistics or 1% lows. Presentation-pass GPU time covers only output work,
**not total game GPU time**. No FPS readings means the game did not reach rendering,
the run folder is wrong, or the runtime didn't emit the expected log lines. Check
`runner.log` and `fefw.log`. The wrapper must remain alive until the game exits;
detaching launch scripts that return early are unsuitable.

## Optional diagnostic runs

For the source build that adds bounded capture and detailed queue timings, see
[the Windows patch build guide](BUILD-WINDOWS.md) and [patch installation](PATCH-INSTALL.md).

Add `--profile` for a separate short run (about 30–60 measured seconds is useful).
It enables the existing runtime's render/GPU-pass trace, writing `frame.trace`
into the run directory through Wine's Z: mapping. CPU stack sampling is explicitly
disabled: a Proton run crashed inside Wine's `ntdll` with combined profiling,
and the sampler's stack-unwinding path is suspected. This trace-only configuration
still needs validation on the Deck. Traces may reach the
runtime's event limit during long runs. Profiling covers the whole process run,
including loading; START/STOP only filter the hardware/FPS summary.

GPU timestamp profiling introduces pipeline drains.
**Do not compare diagnostic FPS against baseline FPS.** Use these captures
to identify expensive passes and CPU stacks, then validate changes without profiling.

`--cpu-profile` separately enables experimental 100 Hz CPU sampling and writes
`cpu.folded`. It briefly stops threads to unwind their stacks and may crash under
Proton; leave it off on the Deck while investigating the reported crash. The
sampler flushes periodically (about every three seconds) and at normal shutdown;
forced termination can lose the final samples.

With the Deck diagnostic runtime, `--delay` and `--duration` also bound frame/GPU
trace recording. Older 0.1.7 runtimes ignore these trace-window settings and
record from startup. Manual START/STOP still only filters CSV summaries; it does
not dynamically control the runtime trace. Trace timing is relative to runtime
startup, while CSV timing is relative to wrapper startup.

Logs and configuration can contain local paths and command arguments. Review the
run folder before sharing. Saves, dumps and shader caches are not collected.

## Local verification

```sh
python3 -m unittest discover -s tools/deck -p 'test_*.py'
```

These tests exercise sensor conversion and a synthetic launch; real Deck sensor
availability, Proton lifetime and GPU profiling still need validation on hardware.
