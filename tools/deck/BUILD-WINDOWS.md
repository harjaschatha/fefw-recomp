# Build the Deck diagnostic patch on Windows

The game uses a Windows runtime DLL under Proton. Rebuild that DLL on your Windows
laptop and copy a small patch to the existing Deck installation. No game dump,
shader translation, launcher rebuild, Rust or .NET is needed for this patch.

## Prerequisites

Install these using their normal Windows installers:

- Visual Studio 2022 Build Tools or newer, with **Desktop development with C++**
  and a Windows SDK.
- LLVM **23 or newer**, including `clang-cl` (default path `C:\Program Files\LLVM\bin`).
- Git, CMake 3.25+, Ninja, NASM 2.14+, and PowerShell 7 (`pwsh`).

The source repository's existing [build guide](../../docs/BUILDING.md) describes
tool locations. `NX_LLVM_BIN`, `NX_CMAKE_BIN`, `NX_NINJA_BIN` and `NX_VCVARS` can
override discovery. Add NASM to PATH or install it in `C:\Program Files\NASM`.

Install the movie decoder dependency once. For example, in PowerShell:

```powershell
git clone https://github.com/microsoft/vcpkg.git C:\vcpkg
C:\vcpkg\bootstrap-vcpkg.bat
C:\vcpkg\vcpkg.exe install libvpx:x64-windows-static
```

If vcpkg already exists, reuse it; do not clone over it. A different installation
folder can be supplied through `-LibVpxRoot` below. The script requires libvpx and
NASM so this diagnostic build does not silently drop existing movie support.

## Transfer the source changes

These changes may still be uncommitted on the Mac. A fresh clone alone will not
contain them. Transfer the prepared diagnostic source zip and extract it on the
laptop, or copy these changed/new source files into a checkout of this same base:

```text
game-build/fefw/CMakeLists.txt
game-build/scripts/build-deck-patch.ps1
runtime/include/nxrt/ftrace.h
runtime/src/diag/ftrace.cpp
runtime/src/gfx/nvn/nvn_gpu.cpp
runtime/src/gfx/vk_renderer.cpp
runtime/tests/test_ftrace.cpp
tools/deck/
```

The prepared source zip includes `SOURCE-SNAPSHOT.json`, which identifies the
base commit and hashes of all included files. No `git init`, commit or upload is
required. The build checks those hashes before packaging. Keep this source zip
and the generated build manifest together. If you want to edit the snapshot,
first put it in a local Git repository; edited builds use that repository's
commit and working-tree status instead.

## Build

Open PowerShell at the repository root:

```powershell
pwsh -File game-build/scripts/build-deck-patch.ps1 -Jobs 6
```

For a different vcpkg installation:

```powershell
pwsh -File game-build/scripts/build-deck-patch.ps1 -Jobs 6 -LibVpxRoot "D:\vcpkg\installed\x64-windows-static"
```

The script fetches the pinned ASTC decoder sources if absent, builds the DLL with
texture and movie support, builds the core test executable, and runs the `ftrace`
and `log_config` groups. It packages output only if those checks pass. These are
focused diagnostic tests, not the full runtime/GPU test suite. Real Vulkan and
Steam Deck behaviour still require a hardware run. `-SkipTests` is available for
troubleshooting; the manifest records that tests were skipped.

The first build downloads dependencies and may take a while. If memory runs low,
rerun with `-Jobs 2`. Build products are reused on subsequent runs.

Output:

```text
work/release/deck-patch/fefw-deck-diagnostic-<timestamp>-<commit>.zip
```

Transfer that zip to the Deck and follow [PATCH-INSTALL.md](PATCH-INSTALL.md).
It contains the runtime DLL, matching import library, updated benchmark wrapper,
installation instructions, licences, and a manifest with file hashes. It contains
no game executable, dump, saves or shader cache.

The planned measurements are queue-lock wait, Vulkan queue submission, and Vulkan
presentation. This build preserves rendering and synchronisation behaviour; it
does not yet change compute-buffer copies, shader code or scheduling.
