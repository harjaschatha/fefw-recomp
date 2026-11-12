# SPDX-License-Identifier: GPL-3.0-or-later
# Build a Windows runtime DLL for an existing Linux/Deck 0.1.7 install. No game dump needed.
param(
    [int]$Jobs = 6,
    [string]$Out = "",
    [string]$LibVpxRoot = "",
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if ($Jobs -lt 1) { throw '-Jobs must be positive' }
if (-not $Out) { $Out = Join-Path $root 'work\release\deck-patch' }
$Out = [IO.Path]::GetFullPath($Out)

function Run([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE) { throw "$Program failed with exit code $LASTEXITCODE" }
}

if (-not $env:NX_LLVM_BIN) { $env:NX_LLVM_BIN = 'C:\Program Files\LLVM\bin' }
$clang = Join-Path $env:NX_LLVM_BIN 'clang-cl.exe'
if (-not (Test-Path $clang)) { throw "Install LLVM 23+ or set NX_LLVM_BIN (missing $clang)" }
$compilerVersion = (& $clang --version | Out-String).Trim()
if ($compilerVersion -notmatch 'clang version (\d+)' -or [int]$Matches[1] -lt 23) {
    throw "LLVM 23+ required; found: $compilerVersion"
}

# Fetch only the decoder source needed by the C++ ASTC transcoder fallback.
# This avoids requiring ISPC or carrying extra decoder DLLs in the patch.
$astc = Join-Path $root 'tools\textures\third_party\astc-encoder'
if (-not (Test-Path $astc)) {
    Run 'git' @('clone', '--depth', '1', '--branch', '5.7.0', 'https://github.com/ARM-software/astc-encoder.git', $astc)
}
$astcVersion = (& git -C $astc describe --tags --exact-match 2>$null | Out-String).Trim()
if ($LASTEXITCODE -or $astcVersion -ne '5.7.0') { throw "ASTC decoder must be at tag 5.7.0: $astc" }
Run 'git' @('-C', $astc, 'diff', '--exit-code', 'HEAD')

if (-not $LibVpxRoot) {
    $vcpkg = if ($env:VCPKG_ROOT) { $env:VCPKG_ROOT } elseif ($env:VCPKG_INSTALLATION_ROOT) { $env:VCPKG_INSTALLATION_ROOT } else { 'C:\vcpkg' }
    $LibVpxRoot = Join-Path $vcpkg 'installed\x64-windows-static'
}
if (-not (Test-Path (Join-Path $LibVpxRoot 'lib\vpx.lib')) -or
    -not (Test-Path (Join-Path $LibVpxRoot 'include\vpx\vpx_decoder.h'))) {
    throw "Install libvpx:x64-windows-static using vcpkg, then pass -LibVpxRoot <vcpkg>\installed\x64-windows-static. Refusing a patch with missing movie decoders."
}
$nasm = Get-Command nasm -ErrorAction SilentlyContinue
$nasmPath = if ($nasm) { $nasm.Source } else { 'C:\Program Files\NASM\nasm.exe' }
if (-not (Test-Path $nasmPath)) { throw 'Install NASM 2.14+ for movie decoding, or add nasm.exe to PATH' }

$bd = Join-Path $root 'game-build\fefw\build\deck-patch'
$tests = if ($SkipTests) { 'OFF' } else { 'ON' }
$cmakeArgs = "-DFEFW_RT_DLL=ON -DNXRT_ASTC2BC7=ON -DFEFW_BUILD_RUNTIME_TESTS=$tests -DNXRT_BUILD_LIFT_TESTS=OFF -DNXRT_DAV1D_ASM=ON -DNXRT_NASM=`"$nasmPath`" -DNXRT_LIBVPX_ROOT=`"$LibVpxRoot`""
& (Join-Path $PSScriptRoot 'build_fefw.ps1') -Target fefw_rt -BuildDir $bd -Jobs $Jobs -CMakeArgs $cmakeArgs
if ($LASTEXITCODE) { throw 'Runtime DLL build failed' }

if (-not $SkipTests) {
    $envCmd = Join-Path $root 'runtime\scripts\env.cmd'
    cmd /c "call `"$envCmd`" && cmake --build `"$bd`" --target nxrt_tests -j $Jobs && ctest --test-dir `"$bd\runtime`" --output-on-failure -R `"^(ftrace|log_config)$`""
    if ($LASTEXITCODE) { throw 'Runtime diagnostic tests failed; no patch packaged' }
}

$snapshotHash = $null
if (Test-Path (Join-Path $root '.git')) {
    $commit = (& git -C $root rev-parse HEAD | Out-String).Trim()
    if ($LASTEXITCODE) { throw 'Cannot identify source commit' }
    $dirty = (& git -C $root status --porcelain --untracked-files=normal | Out-String).Trim()
} elseif (Test-Path (Join-Path $root 'SOURCE-SNAPSHOT.json')) {
    $snapshotPath = Join-Path $root 'SOURCE-SNAPSHOT.json'
    $snapshot = Get-Content -Raw $snapshotPath | ConvertFrom-Json
    $commit = $snapshot.base_commit
    $snapshotHash = (Get-FileHash $snapshotPath -Algorithm SHA256).Hash.ToLower()
    foreach ($file in $snapshot.files) {
        $filePath = Join-Path $root $file.path
        if (-not (Test-Path $filePath) -or (Get-FileHash $filePath -Algorithm SHA256).Hash.ToLower() -ne $file.sha256) {
            throw "Source snapshot changed: $($file.path). Use a Git checkout for edited builds, or extract a fresh snapshot."
        }
    }
    $dirty = 'Diagnostic source snapshot (changes on top of base commit; SOURCE-SNAPSHOT.json verified)'
} else {
    throw 'Build from a Git checkout or the prepared source zip containing SOURCE-SNAPSHOT.json'
}
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$name = "fefw-deck-diagnostic-$stamp-$($commit.Substring(0, 10))"
$package = Join-Path $Out $name
New-Item -ItemType Directory -Force "$package\tools\build\sdk", "$package\tools\deck", "$package\licenses" | Out-Null
Copy-Item (Join-Path $bd 'fefw_rt.dll') $package
Copy-Item (Join-Path $bd 'fefw_rt.lib') "$package\tools\build\sdk"
Copy-Item "$root\tools\deck\benchmark.py", "$root\tools\deck\README.md" "$package\tools\deck"
Copy-Item "$root\tools\deck\BUILD-WINDOWS.md", "$root\tools\deck\PATCH-INSTALL.md" "$package\tools\deck"
Copy-Item "$root\tools\deck\PATCH-INSTALL.md" "$package\README.md"
Copy-Item "$root\LICENSE" "$package\licenses\LICENSE.GPL-3.0.txt"
Copy-Item "$root\runtime\THIRD_PARTY_NOTICES.md" "$package\licenses"
$manifest = [ordered]@{
    kind = 'deck-diagnostic'; base_version = '0.1.7'; runtime_api = 1
    source_commit = $commit; source_dirty = [bool]$dirty; source_status = $dirty
    source_snapshot_sha256 = $snapshotHash
    built_utc = $stamp; compiler = $compilerVersion; tests_run = (-not $SkipTests)
    purpose = 'Separate queue lock/submit/present timings; bounded frame/GPU trace; CPU sampler disabled by benchmark --profile'
    performance_improvement_claimed = $false
    files = @()
}
$manifest.files = @(Get-ChildItem $package -Recurse -File | ForEach-Object {
    [ordered]@{ path = $_.FullName.Substring($package.Length + 1).Replace('\', '/'); sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower() }
})
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 "$package\build-info.json"
Compress-Archive -Path "$package\*" -DestinationPath "$package.zip"
Write-Host "Deck patch: $package.zip"
Write-Host 'Keep the matching source checkout; this build contains diagnostic changes, not a validated FPS improvement.'
