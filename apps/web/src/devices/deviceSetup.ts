export type DeviceSetupProfile = 'AI_EDGE' | 'STB_GATEWAY'
export type DeviceSetupPlatform = 'windows' | 'ubuntu' | 'armbian'
export type DeviceConnectionMode =
  'same-host' | 'private-network' | 'public-domain' | 'cloudflare-tunnel'

export type DeviceSetupCommandInput = {
  profile: DeviceSetupProfile
  platform: DeviceSetupPlatform
  connectionMode: DeviceConnectionMode
  coreApiUrl: string
  centralAiUrl?: string
  deviceId: string
  modelVersion?: string
  useWorkingCopy: boolean
}

const WINDOWS_BOOTSTRAP =
  'https://raw.githubusercontent.com/mygads/Face-Recognition-Capstone/main/scripts/bootstrap-camera-device.ps1'
const LINUX_BOOTSTRAP =
  'https://raw.githubusercontent.com/mygads/Face-Recognition-Capstone/main/scripts/bootstrap-camera-device.sh'

function quotePowerShell(value: string): string {
  return `'${value.replaceAll("'", "''")}'`
}

function quotePosix(value: string): string {
  return `'${value.replaceAll("'", "'\"'\"'")}'`
}

function requireDeviceApiAccess(mode: DeviceConnectionMode): void {
  if (mode === 'public-domain' || mode === 'cloudflare-tunnel') {
    throw new Error(
      'Jalur publik belum diaktifkan: agent mengambil gallery template biometrik dari Core API. Gunakan LAN/VPN privat sampai kebijakan jalur publik disetujui.',
    )
  }
}

export function buildDeviceSetupCommand(input: DeviceSetupCommandInput): string {
  requireDeviceApiAccess(input.connectionMode)
  if (input.profile === 'STB_GATEWAY' && input.platform !== 'armbian') {
    throw new Error('STB_GATEWAY saat ini dipasang pada Armbian/Linux, bukan Windows.')
  }
  if (input.profile === 'AI_EDGE' && input.platform === 'armbian') {
    throw new Error('Pilih Windows atau Ubuntu untuk perangkat AI_EDGE.')
  }
  if (input.profile === 'STB_GATEWAY' && !input.centralAiUrl) {
    throw new Error('URL AI Central diperlukan untuk STB_GATEWAY.')
  }

  const values: Record<string, string> = {
    PRESENSI_CORE_API_URL: input.coreApiUrl,
    PRESENSI_DEVICE_ID: input.deviceId,
  }
  const bundleFile = `presensi-device-${input.deviceId}-setup.json`
  if (input.profile === 'AI_EDGE' && input.modelVersion) {
    values.PRESENSI_MODEL_VERSION = input.modelVersion
  }
  if (input.profile === 'STB_GATEWAY' && input.centralAiUrl) {
    values.PRESENSI_CENTRAL_AI_URL = input.centralAiUrl
  }

  if (input.platform === 'windows') {
    const environment = Object.entries(values)
      .map(([name, value]) => `$env:${name}=${quotePowerShell(value)}`)
      .join('; ')
    const bundlePath = `$env:PRESENSI_DEVICE_SETUP_BUNDLE="$HOME\\Downloads\\${bundleFile}"`
    const script = input.useWorkingCopy
      ? '.\\scripts\\bootstrap-camera-device.ps1 -UseWorkingCopy'
      : `irm ${WINDOWS_BOOTSTRAP} | iex`
    return `${environment}; ${bundlePath}; ${script}`
  }

  const environment = Object.entries(values)
    .map(([name, value]) => `${name}=${quotePosix(value)}`)
    .join(' ')
  const bundlePath = `PRESENSI_DEVICE_SETUP_BUNDLE="$HOME/Downloads/${bundleFile}"`
  const script = input.useWorkingCopy
    ? 'bash scripts/bootstrap-camera-device.sh --use-working-copy'
    : `set -o pipefail; if ! command -v curl >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y curl || exit 1; fi; curl -fsSL ${quotePosix(LINUX_BOOTSTRAP)}`
  return input.useWorkingCopy
    ? `${environment} ${bundlePath} ${script}`.trim()
    : `${script} | ${environment} ${bundlePath} bash`.trim()
}
