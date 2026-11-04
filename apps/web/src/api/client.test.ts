import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiTimeout, fetchWithTimeout, toTransportError } from './client'

describe('api client timeout', () => {
  afterEach(() => {
    apiTimeout.milliseconds = 30_000
    vi.unstubAllGlobals()
  })

  it('menggagalkan request yang menggantung setelah batas waktu', async () => {
    apiTimeout.milliseconds = 5
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
    await expect(fetchWithTimeout(new Request('http://localhost/api/x'))).rejects.toMatchObject({
      name: 'AbortError',
    })
  })

  it('meloloskan respons cepat tanpa abort', async () => {
    apiTimeout.milliseconds = 1_000
    const response = new Response('{}', { status: 200 })
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(response)),
    )
    await expect(fetchWithTimeout(new Request('http://localhost/api/x'))).resolves.toBe(response)
  })

  it('meneruskan abort milik penelepon', async () => {
    const controller = new AbortController()
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
    const pending = fetchWithTimeout(
      new Request('http://localhost/api/x', { signal: controller.signal }),
    )
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('memakai pagu kustom saat diminta', async () => {
    apiTimeout.milliseconds = 1_000
    const response = new Response('{}', { status: 200 })
    let observedSignal: AbortSignal | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
        observedSignal = init?.signal ?? undefined
        return Promise.resolve(response)
      }),
    )
    await fetchWithTimeout(new Request('http://localhost/api/x'), 50)
    expect(observedSignal).toBeInstanceOf(AbortSignal)
  })

  it('memetakan AbortError ke request_timeout', () => {
    const failure = toTransportError(new DOMException('aborted', 'AbortError'))
    expect(failure).toBeInstanceOf(ApiError)
    expect(failure.code).toBe('request_timeout')
  })

  it('memetakan galat jaringan ke network_error', () => {
    const failure = toTransportError(new TypeError('Failed to fetch'))
    expect(failure).toBeInstanceOf(ApiError)
    expect(failure.code).toBe('network_error')
  })
})
