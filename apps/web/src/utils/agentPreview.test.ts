import { describe, expect, it } from 'vitest'
import { agentStreamUrl, agentUrlWithToken } from './agentPreview'

describe('agentPreview', () => {
  it('tanpa token memakai URL loopback apa adanya', () => {
    expect(agentStreamUrl('')).toBe('http://127.0.0.1:8765/v1/kiosk-stream')
  })
  it('dengan token menambahkan query token ter-encode', () => {
    expect(agentUrlWithToken('http://127.0.0.1:8765/v1/kiosk-stream', 'a b&c')).toBe(
      'http://127.0.0.1:8765/v1/kiosk-stream?token=a%20b%26c',
    )
  })
})
