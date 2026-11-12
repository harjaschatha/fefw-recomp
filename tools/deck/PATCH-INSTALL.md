# Deck diagnostic runtime patch (based on 0.1.7)

This patch adds separate queue-lock, queue-submission and presentation trace zones,
and a delayed, bounded trace window. It is a diagnostic build; no FPS improvement
has been established. The runtime API and generated game code are unchanged.

## Install

1. Exit the game and launcher completely.
2. In your existing game package, back up `fefw_rt.dll`,
   `tools/build/sdk/fefw_rt.lib` and `tools/deck/benchmark.py` outside the package.
3. Extract this patch into that package, merging the `tools` folder and replacing
   those three files. Keep `fefw.exe`, saves, dumps, shader caches and settings.
   You do not need to run Setup again for this patch.
4. Preserve `build-info.json` with the next benchmark logs so the build can be identified.

First test a normal launch without `--profile`. If that works, use your existing
profiling launch options (`--profile --delay 180 --duration 60`). The updated
wrapper tells this runtime to start tracing three minutes after runtime startup,
and stop recording after one minute. Hardware/FPS timing begins at wrapper launch,
so the trace and CSV windows can differ by Proton's startup time. Check
`prof: trace window: delay 180.0 s, duration 60.0 s` in `fefw.log`.

Profile mode disables CPU stack sampling. The trace should now contain
`present.queue_lock`, `present.queue_submit`, and `present.queue_present` zones.
GPU pass timestamps are disabled outside the trace window. A trace still has a
finite event budget; if the captured minute fills it, shorten the next capture.
Do not compare profile-mode FPS directly to baseline FPS.

Exit using Steam if necessary. Traces are flushed periodically; forced exit can
lose the final second. Send the latest run folder plus `build-info.json`.

To roll back, exit the game and restore the three backed-up files. Existing saves
and shader caches are compatible with both builds.
