import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchWithPreviewTimeout } from './previewFetch'

describe('preview fetch timeout', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('menggagalkan request gantung dengan pesan Indonesia', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => {
              reject(new DOMException('The operation was aborted.', 'AbortError'))
            })
          }),
      ),
    )
    await expect(fetchWithPreviewTimeout('http://localhost/v1/frame.jpg', {}, 5)).rejects.toThrow(
      'tidak merespons tepat waktu',
    )
  })

  it('meloloskan respons cepat', async () => {
    const response = new Response('{}', { status: 200 })
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(response)),
    )
    await expect(fetchWithPreviewTimeout('http://localhost/v1/status', {}, 1_000)).resolves.toBe(
      response,
    )
  })

  it('pagu tetap berlaku walau penelepon menitipkan signal sendiri', async () => {
    const caller = new AbortController()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => {
              reject(new DOMException('The operation was aborted.', 'AbortError'))
            })
          }),
      ),
    )
    await expect(
      fetchWithPreviewTimeout('http://localhost/v1/frame.jpg', { signal: caller.signal }, 5),
    ).rejects.toThrow('tidak merespons tepat waktu')
  })
})
