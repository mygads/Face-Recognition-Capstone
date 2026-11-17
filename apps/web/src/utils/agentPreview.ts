/** URL + token opsional untuk stream/preview agent di PC lab yang sama. */

export const AGENT_PREVIEW_BASE_URL = 'http://127.0.0.1:8765'
export const AGENT_HINT_PATH = '/v1/kiosk-hint'
export const AGENT_STREAM_PATH = '/v1/kiosk-stream'
export const KIOSK_STREAM_TOKEN_KEY = 'presensi.kiosk_stream_token'

export function readKioskStreamToken(): string {
  try {
    return (window.localStorage.getItem(KIOSK_STREAM_TOKEN_KEY) ?? '').trim()
  } catch {
    return ''
  }
}

/** Simpan token sekali via ?stream_token=, lalu bersihkan dari URL. */
export function captureKioskStreamTokenFromQuery(): string {
  try {
    const params = new URLSearchParams(window.location.search)
    const viaQuery = (params.get('stream_token') ?? '').trim()
    if (viaQuery) {
      window.localStorage.setItem(KIOSK_STREAM_TOKEN_KEY, viaQuery)
      params.delete('stream_token')
      const rest = params.toString()
      window.history.replaceState(null, '', window.location.pathname + (rest ? `?${rest}` : ''))
    }
    return readKioskStreamToken()
  } catch {
    return ''
  }
}

export function agentUrlWithToken(base: string, token: string): string {
  if (!token) return base
  const sep = base.includes('?') ? '&' : '?'
  return `${base}${sep}token=${encodeURIComponent(token)}`
}

export function agentHintUrl(token: string): string {
  return agentUrlWithToken(`${AGENT_PREVIEW_BASE_URL}${AGENT_HINT_PATH}`, token)
}

export function agentStreamUrl(token: string): string {
  return agentUrlWithToken(`${AGENT_PREVIEW_BASE_URL}${AGENT_STREAM_PATH}`, token)
}
