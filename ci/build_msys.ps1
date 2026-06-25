[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Service,
    [Parameter(Mandatory = $true)][string]$BaseUrl
)

$ErrorActionPreference = "Stop"
$workspace = (Get-Location).Path
$buildDirectory = Join-Path $env:RUNNER_TEMP "orion-msys-$Service"
New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null
$windowsGit = (Get-Command git.exe -ErrorAction Stop).Source
$env:MSYSTEM = "MINGW64"
$env:CHERE_INVOKING = "1"
$env:HOME = $buildDirectory
Move-Item -Path (Join-Path $workspace "orion") -Destination $buildDirectory
$archive = Join-Path $buildDirectory "msys-base.tar.xz"

Write-Host "Downloading MSYS base for $Service"
Invoke-WebRequest -Uri $BaseUrl -OutFile $archive
& tar.exe -xf $archive -C $buildDirectory
if ($LASTEXITCODE -ne 0) { throw "Could not extract the MSYS base archive (exit $LASTEXITCODE)" }
Remove-Item $archive

$bash = Join-Path $buildDirectory "msys64/usr/bin/bash.exe"
if (-not (Test-Path $bash)) { throw "The MSYS base did not contain msys64/usr/bin/bash.exe" }
$env:PATH = @(
    (Join-Path $buildDirectory "msys64/mingw64/bin"),
    (Join-Path $buildDirectory "msys64/usr/bin"),
    (Split-Path $windowsGit -Parent),
    $env:PATH
) -join ";"

# Run login setup once, then let pacman replace its runtime if needed. MSYS2 can
# terminate the first shell with status 1 during that replacement; pass two must
# succeed before the bundle can be packaged.
Push-Location $buildDirectory
try {
    & $bash -lc " "
    if ($LASTEXITCODE -ne 0) { throw "MSYS login initialization failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
for ($pass = 1; $pass -le 2; $pass++) {
    Push-Location $buildDirectory
    try {
        & $bash -c "pacman --noconfirm -Syu"
        if ($pass -eq 1 -and $LASTEXITCODE -notin @(0, 1)) {
            throw "pacman update pass $pass failed with exit code $LASTEXITCODE"
        }
        if ($pass -eq 2 -and $LASTEXITCODE -ne 0) {
            throw "pacman update pass $pass failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

$setup = "./orion/services/$Service/setup.sh"
Push-Location $buildDirectory
try {
    & $bash -c $setup
} finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0) { throw "MSYS bundle setup failed with exit code $LASTEXITCODE" }

$builtArtifact = Join-Path $buildDirectory "msys2.tar.bz2"
if (-not (Test-Path $builtArtifact)) { throw "Setup did not produce msys2.tar.bz2" }
Copy-Item $builtArtifact (Join-Path $workspace "msys2.tar.bz2") -Force
