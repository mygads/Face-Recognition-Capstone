param(
    [switch]$UseWorkingCopy,
    [string]$BundlePath
)

$ErrorActionPreference = 'Stop'
$installRef = if ($env:PRESENSI_INSTALL_REF) { $env:PRESENSI_INSTALL_REF } else { 'main' }

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = @($machinePath, $userPath) -join ';'
}

function Install-WinGetPackage([string]$PackageId) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget tidak tersedia. Pasang prasyarat $PackageId, lalu jalankan bootstrap lagi."
    }
    & winget install --id $PackageId --exact --silent `
        --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Instalasi $PackageId melalui winget gagal." }
    Refresh-ProcessPath
}

function ConvertTo-Origin([string]$Value, [bool]$AllowLocalHttp) {
    $parsed = $null
    if (-not [Uri]::TryCreate($Value.Trim(), [UriKind]::Absolute, [ref]$parsed)) {
        throw 'URL harus berupa origin penuh, misalnya https://presensi.sekolah.id.'
    }
    $loopback = [Uri]::IsLoopback($parsed)
    if (
        $parsed.Scheme -notin @('https', 'http') -or
        ($parsed.Scheme -eq 'http' -and (-not $AllowLocalHttp -or -not $loopback)) -or
        $parsed.UserInfo -or $parsed.Query -or $parsed.Fragment -or
        $parsed.AbsolutePath -notin @('', '/')
    ) {
        throw 'Gunakan origin HTTPS tanpa path/query. HTTP hanya untuk localhost pada API lokal.'
    }
    return $parsed.GetLeftPart([UriPartial]::Authority).TrimEnd('/')
}

if (-not $UseWorkingCopy -and -not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host 'Git belum terpasang; mencoba memasangnya melalui winget...'
    Install-WinGetPackage 'Git.Git'
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw 'Git terpasang tetapi belum tersedia di PATH. Buka PowerShell baru lalu jalankan bootstrap lagi.'
    }
}
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host 'Python Launcher belum terpasang; mencoba memasang Python 3.12 melalui winget...'
    Install-WinGetPackage 'Python.Python.3.12'
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'Python terpasang tetapi launcher belum tersedia di PATH. Buka PowerShell baru lalu jalankan bootstrap lagi.'
    }
}
& py -3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>$null
if ($LASTEXITCODE -ne 0) {
    $installPython = Read-Host 'Python 3.11+ belum tersedia. Install Python 3.12 sekarang dengan py install 3.12? [Y/n]'
    if ($installPython -in @('n', 'N', 'no', 'NO')) {
        throw 'Python 3.11+ dibutuhkan untuk memasang edge-agent.'
    }
    & py install 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 tidak berhasil dipasang.' }
    & py -3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ belum tersedia setelah instalasi.' }
}

$inputBundlePath = if ($BundlePath) { $BundlePath } else { $env:PRESENSI_DEVICE_SETUP_BUNDLE }
$setupBundle = $null
$token = $null
if ($inputBundlePath) {
    $resolvedInputBundle = (Resolve-Path -LiteralPath $inputBundlePath).Path
    $setupBundle = Get-Content -LiteralPath $resolvedInputBundle -Raw | ConvertFrom-Json
    if ($setupBundle.schema_version -ne 1 -or $setupBundle.deployment_profile -ne 'AI_EDGE') {
        throw 'Setup bundle tidak valid untuk Windows AI_EDGE.'
    }
    $apiUrl = ConvertTo-Origin ([string]$setupBundle.core_api_url) $true
    $deviceId = ([Guid]$setupBundle.device_id).ToString()
    $token = [string]$setupBundle.token
    if ($env:PRESENSI_CORE_API_URL -and (ConvertTo-Origin $env:PRESENSI_CORE_API_URL $true) -ne $apiUrl) {
        throw 'Core API pada command tidak cocok dengan setup bundle.'
    }
    if ($env:PRESENSI_DEVICE_ID -and ([Guid]$env:PRESENSI_DEVICE_ID).ToString() -ne $deviceId) {
        throw 'Device ID pada command tidak cocok dengan setup bundle.'
    }
    if ($env:PRESENSI_MODEL_VERSION -and $env:PRESENSI_MODEL_VERSION -ne [string]$setupBundle.model_version) {
        throw 'Versi model pada command tidak cocok dengan setup bundle.'
    }
    if ($token.Length -lt 40 -or $token -notmatch '^[A-Za-z0-9_-]+$') {
        throw 'Credential pada setup bundle tidak valid.'
    }
    if (-not $setupBundle.model_version -or ([string]$setupBundle.model_version).Length -gt 128) {
        throw 'Bundle harus berisi versi model AI_EDGE yang valid.'
    }
} else {
    $apiInput = $env:PRESENSI_CORE_API_URL
    if (-not $apiInput) {
        $apiInput = Read-Host 'URL origin Core API (misalnya https://presensi.sekolah.id)'
    }
    $apiUrl = ConvertTo-Origin $apiInput $true
}
$secureCredential = $null
$pointer = [IntPtr]::Zero
$plainCredential = $null
$bundlePath = $null
try {
    if (-not $setupBundle) {
        $secureCredential = Read-Host 'Kredensial bootstrap (UUID:token) dari halaman Perangkat' -AsSecureString
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureCredential)
        $plainCredential = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        $separator = $plainCredential.IndexOf(':')
        if ($separator -lt 1) {
            throw 'Kredensial harus berformat UUID:token.'
        }
        $deviceId = ([Guid]$plainCredential.Substring(0, $separator)).ToString()
        $token = $plainCredential.Substring($separator + 1)
        $plainCredential = $null
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        $pointer = [IntPtr]::Zero
    }
    if ($env:PRESENSI_DEVICE_ID) {
        $expectedDeviceId = ([Guid]$env:PRESENSI_DEVICE_ID).ToString()
        if ($deviceId -ne $expectedDeviceId) {
            throw 'Device ID dari setup tidak cocok dengan PRESENSI_DEVICE_ID.'
        }
    }
    if ($token.Length -lt 40 -or $token -notmatch '^[A-Za-z0-9_-]+$') {
        throw 'Token perangkat tidak valid.'
    }

    Write-Host 'Memvalidasi kredensial dan membaca profile perangkat dari Core API...'
    $headers = @{
        Authorization = "Bearer $token"
        'X-Device-ID' = $deviceId
    }
    try {
        $status = Invoke-RestMethod -Method Get `
            -Uri "$apiUrl/api/v1/devices/$deviceId/device-status" `
            -Headers $headers
    }
    catch {
        throw 'API menolak kredensial atau tidak dapat dijangkau. Periksa URL/token atau rotasi token di UI.'
    }
    if ($status.device_id -ne $deviceId -or $status.deployment_profile -ne 'AI_EDGE') {
        throw 'Windows bootstrap mendukung profile AI_EDGE. Untuk STB_GATEWAY, gunakan bootstrap Linux di Armbian.'
    }

    $modelVersion = if ($setupBundle) { [string]$setupBundle.model_version } else { $env:PRESENSI_MODEL_VERSION }
    if (-not $modelVersion) {
        $modelVersion = Read-Host 'Versi model template (default opencv-zoo-sface-2021dec)'
    }
    if (-not $modelVersion) { $modelVersion = 'opencv-zoo-sface-2021dec' }
    if ($modelVersion.Length -gt 128) { throw 'Versi model terlalu panjang.' }

    if ($UseWorkingCopy) {
        $sourceDir = (Get-Location).Path
        if (-not (Test-Path -LiteralPath (Join-Path $sourceDir 'scripts/install-camera-device.ps1'))) {
            throw 'Jalankan command local bootstrap dari root checkout Face-Recognition-Capstone.'
        }
    }
    else {
        $sourceDir = Join-Path $env:LOCALAPPDATA 'Presensi/source'
    }
    $sourceParent = Join-Path $env:LOCALAPPDATA 'Presensi'
    New-Item -ItemType Directory -Path $sourceParent -Force | Out-Null
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $sourceParent '/inheritance:r' '/grant:r' "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Tidak dapat melindungi folder setup lokal.' }

    if (-not $UseWorkingCopy) {
        if (Test-Path -LiteralPath $sourceDir) {
            if (-not (Test-Path -LiteralPath (Join-Path $sourceDir '.git'))) {
                throw "Folder $sourceDir ada tetapi bukan checkout repository."
            }
            $changes = & git -C $sourceDir status --porcelain
            if ($changes) { throw "Checkout $sourceDir memiliki perubahan lokal; simpan/pindahkan dulu." }
            & git -C $sourceDir fetch --depth 1 origin $installRef
            if ($LASTEXITCODE -ne 0) { throw 'Tidak dapat mengunduh source terbaru dari GitHub.' }
            & git -C $sourceDir checkout --detach FETCH_HEAD
            if ($LASTEXITCODE -ne 0) { throw 'Tidak dapat memilih source yang diunduh.' }
        }
        else {
            & git clone --depth 1 --branch $installRef `
                https://github.com/mygads/Face-Recognition-Capstone.git $sourceDir
            if ($LASTEXITCODE -ne 0) { throw 'Tidak dapat mengunduh source dari GitHub.' }
        }
    }

    $bundlePath = Join-Path $sourceParent ("bootstrap-{0}.json" -f [Guid]::NewGuid())
    $bundle = @{
        schema_version = 1
        device_id = $deviceId
        deployment_profile = 'AI_EDGE'
        core_api_url = $apiUrl
        central_ai_url = $null
        model_version = $modelVersion
        token = $token
    }
    $json = $bundle | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText($bundlePath, $json, [Text.UTF8Encoding]::new($false))
    & icacls.exe $bundlePath '/inheritance:r' '/grant:r' "${identity}:F" 'SYSTEM:F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Tidak dapat melindungi file setup sementara.' }
    $token = $null
    $headers = $null
    $bundle = $null
    $setupBundle = $null

    & (Join-Path $sourceDir 'scripts/install-camera-device.ps1') -BundlePath $bundlePath
}
finally {
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    $token = $null
    $plainCredential = $null
    $json = $null
    $secureCredential = $null
    if ($bundlePath -and (Test-Path -LiteralPath $bundlePath)) {
        Remove-Item -LiteralPath $bundlePath -Force
    }
}
