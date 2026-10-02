import { describe, expect, it } from 'vitest'
import { buildDeviceSetupCommand } from './deviceSetup'

const base = {
  profile: 'AI_EDGE' as const,
  platform: 'windows' as const,
  connectionMode: 'same-host' as const,
  coreApiUrl: 'http://127.0.0.1:8000',
  deviceId: '76f1f10d-df24-4ffc-a5bc-6ff273dc8e2b',
  modelVersion: 'opencv-zoo-sface-2021dec',
  useWorkingCopy: true,
}

describe('device setup command', () => {
  it('uses the local repository on the same host without downloading GitHub source', () => {
    expect(buildDeviceSetupCommand(base)).toContain(
      '.\\scripts\\bootstrap-camera-device.ps1 -UseWorkingCopy',
    )
    expect(buildDeviceSetupCommand(base)).toContain('PRESENSI_DEVICE_ID=')
    expect(buildDeviceSetupCommand(base)).not.toContain('https://raw.githubusercontent.com')
  })

  it('generates a Linux bootstrap for a remote STB with both service origins', () => {
    const command = buildDeviceSetupCommand({
      ...base,
      profile: 'STB_GATEWAY',
      platform: 'armbian',
      connectionMode: 'private-network',
      coreApiUrl: 'https://presensi.internal.school.test',
      centralAiUrl: 'https://ai.internal.school.test',
      modelVersion: undefined,
      useWorkingCopy: false,
    })

    expect(command).toContain('curl -fsSL')
    expect(command).toContain('sudo apt-get install -y curl')
    expect(command).toContain('PRESENSI_CORE_API_URL=')
    expect(command).toContain('PRESENSI_CENTRAL_AI_URL=')
    expect(command).toContain('PRESENSI_DEVICE_ID=')
    expect(command).not.toContain('token')
  })

  it('rejects public and Cloudflare routes before producing a command', () => {
    expect(() => buildDeviceSetupCommand({ ...base, connectionMode: 'public-domain' })).toThrow(
      'Jalur publik belum diaktifkan',
    )
    expect(() => buildDeviceSetupCommand({ ...base, connectionMode: 'cloudflare-tunnel' })).toThrow(
      'Jalur publik belum diaktifkan',
    )
  })
})
