param(
    [Parameter(Position = 0)]
    [string]$BundlePath
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

if (-not $BundlePath) {
    $BundlePath = Read-Host 'Path to presensi-device-setup.json'
}
$resolvedBundle = (Resolve-Path -LiteralPath $BundlePath).Path
$bundle = Get-Content -LiteralPath $resolvedBundle -Raw | ConvertFrom-Json
if ($bundle.schema_version -ne 1) {
    throw 'Unsupported device setup bundle version.'
}
if ($bundle.deployment_profile -ne 'AI_EDGE') {
    throw 'This Windows installer supports AI_EDGE only. STB_GATEWAY must be installed on its supported Linux gateway.'
}

$pythonVersion = & py -3 -c 'import sys; print(sys.version_info[0], sys.version_info[1])'
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.11 or newer is required. Install Python and the Windows py launcher, then retry.'
}
$pythonVersionParts = ([string]$pythonVersion).Trim() -split '\s+'
if ($pythonVersionParts.Count -ne 2) {
    throw 'Could not determine the selected Python version.'
}
$version = [version]::new([int]$pythonVersionParts[0], [int]$pythonVersionParts[1])
if ($version -lt [version]'3.11') {
    throw "Python 3.11 or newer is required. The selected runtime is $pythonVersion."
}

$venv = Join-Path $repoRoot '.venv-edge-agent'
if (-not (Test-Path (Join-Path $venv 'Scripts/python.exe'))) {
    & py -3 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the edge-agent Python environment.' }
}
$venvPython = Join-Path $venv 'Scripts/python.exe'
& $venvPython -m pip install -e (Join-Path $repoRoot 'apps/edge-agent[camera]') -e (Join-Path $repoRoot 'libs/recognition-core[opencv]')
if ($LASTEXITCODE -ne 0) { throw 'Could not install edge-agent packages.' }

$dataDirectory = Join-Path $env:LOCALAPPDATA 'Presensi'
New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $dataDirectory '/inheritance:r' '/grant:r' "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not protect the local Presensi data directory.' }

$tokenPath = Join-Path $dataDirectory 'device.token'
$replaceToken = $false
if (Test-Path -LiteralPath $tokenPath) {
    $replace = Read-Host 'A token file exists. Replace it with the token in this setup bundle? [y/N]'
    if ($replace -notin @('y', 'Y', 'yes', 'YES')) {
        throw 'Setup cancelled. The existing token file was left unchanged.'
    }
    $replaceToken = $true
}

$configPath = Join-Path $repoRoot 'apps/edge-agent/config/edge-agent.yaml'
$statePath = Join-Path $dataDirectory 'state'
$helperArgs = @(
    (Join-Path $repoRoot 'scripts/apply_device_setup.py'),
    '--bundle', $resolvedBundle,
    '--config', $configPath,
    '--token-file', $tokenPath,
    '--state-dir', $statePath
)
if ($replaceToken) { $helperArgs += '--replace-token' }
& $venvPython @helperArgs
if ($LASTEXITCODE -ne 0) { throw 'Could not apply the device setup bundle.' }
if (Test-Path -LiteralPath $tokenPath) {
    & icacls.exe $tokenPath '/inheritance:r' '/grant:r' "${identity}:F" 'SYSTEM:F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not protect the device token file.' }
}

if ($bundle.deployment_profile -eq 'AI_EDGE') {
    Write-Host 'Provisioning checksum-verified YuNet/SFace models for AI_EDGE...'
    Write-Warning 'SFace is provisioned for evaluation; obtain school/institutional license clearance before operational use.'
    & $venvPython (Join-Path $repoRoot 'scripts/download_face_models.py')
    if ($LASTEXITCODE -ne 0) { throw 'Model tidak berhasil diunduh/diverifikasi.' }
}

$agent = Join-Path $venv 'Scripts/presensi-edge-agent.exe'
Write-Host ''
Write-Host 'Camera setup: select a detected index, capture resolution, and requested FPS.'
$configureCamera = Read-Host 'Run the interactive camera setup now? [Y/n]'
if ($configureCamera -notin @('n', 'N', 'no', 'NO')) {
    & $agent --config $configPath configure-camera
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'Camera setup did not complete. Check OS camera permission and close other apps using the camera.'
        Write-Host "Run later: `"$agent`" --config `"$configPath`" configure-camera"
    }
} else {
    Write-Host "Camera setup skipped. Run later: `"$agent`" --config `"$configPath`" configure-camera"
}

Write-Host ''
Write-Host 'Checking camera indexes. Close browser enrollment and camera calibration first.'
& $agent --config $configPath cameras
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'Camera discovery did not complete. Check Windows camera permissions and close other camera apps.'
}

Write-Host ''
Write-Host 'Device setup is installed. The setup bundle is a secret; remove it from Downloads after verifying this device.'
Write-Host "Config: $configPath"
Write-Host "Protected token file: $tokenPath"
Write-Host ''
Write-Host 'Checking Core API, model/config readiness, and selected camera.'
Write-Host 'Without calibrated thresholds, AI_EDGE can still run camera, heartbeat, and config sync; recognition stays paused.'
& $agent --config $configPath status
$runtimeStatus = $LASTEXITCODE
if ($runtimeStatus -eq 0) {
    $startNow = Read-Host 'Start camera and heartbeat now? Recognition remains paused until thresholds are calibrated. [Y/n]'
    if ($startNow -notin @('n', 'N', 'no', 'NO')) {
        Write-Host 'Agent is running. Press Ctrl+C to stop this commissioning run.'
        & $agent --config $configPath run
    }
} else {
    Write-Warning 'Resolve API, credential, model, or camera issues shown in the status output before starting the agent.'
    Write-Host "After those issues are fixed: `"$agent`" --config `"$configPath`" run"
}
