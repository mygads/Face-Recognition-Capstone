import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import CameraPreviewView from './CameraPreviewView.vue'

const mockRouteQuery = vi.hoisted(() => ({ value: {} as Record<string, string> }))
vi.mock('vue-router', () => ({
  RouterLink: { template: '<a><slot /></a>' },
  useRoute: () => ({ query: mockRouteQuery.value }),
  useRouter: () => ({ replace: vi.fn() }),
}))

vi.mock('../api/client', () => ({
  listDevices: vi.fn(async () => ({
    items: [
      {
        device_id: 'dev-1',
        name: 'Kamera Lab 1',
        laboratory_id: 'lab-1',
        laboratory_name: 'LAB-1',
        deployment_profile: 'AI_EDGE',
        health_status: 'healthy',
      },
      {
        device_id: 'dev-2',
        name: 'Kamera Lab 2',
        laboratory_id: 'lab-1',
        laboratory_name: 'LAB-1',
        deployment_profile: 'AI_EDGE',
        health_status: 'healthy',
      },
    ],
    pagination: { page: 1, per_page: 50, total_items: 2, total_pages: 1 },
  })),
}))

function laborantPinia() {
  const pinia = createPinia()
  useAuthStore(pinia).$patch({
    accessToken: 'test-token',
    expiresAt: Date.now() + 60_000,
    account: {
      id: 'laborant-1',
      email: 'laborant@example.test',
      full_name: 'Test Laborant',
      roles: ['LABORANT'],
      must_change_password: false,
    },
  })
  return pinia
}

describe('camera preview confidence companion', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    mockRouteQuery.value = {}
  })

  it('does not expose identity candidates before a session and never creates attendance', async () => {
    const fetchCalls: string[] = []
    const nowSeconds = Date.now() / 1000
    const stubFetch = vi.fn(async (input: unknown) => {
      const url = String(input)
      fetchCalls.push(url)
      if (url.endsWith('/v1/session')) {
        return { ok: true, status: 200, json: async () => ({ preview_token: 'preview-1' }) }
      }
      if (url.endsWith('/v1/status')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            device_id: 'dev-1',
            camera_open: true,
            session_active: false,
            recognition_state: 'preview_only',
            display_name: null,
            diagnostic_candidate: {
              student_id: '33000000-0000-4000-8000-000000000003',
              display_name: 'Siswa Sintetis',
              class_name: 'X-A',
              similarity: 0.87,
              updated_at: nowSeconds,
            },
            updated_at: nowSeconds,
            camera_observation: {
              state: 'ready',
              message: 'ok',
              frame_width: 640,
              frame_height: 480,
              face_count: 1,
              faces: [
                {
                  x: 1,
                  y: 1,
                  width: 10,
                  height: 10,
                  detection_confidence: 0.93,
                  acceptable: true,
                  reason_codes: [],
                },
              ],
            },
          }),
        }
      }
      if (url.endsWith('/v1/frame.jpg')) {
        return { ok: false, status: 503, blob: async () => new Blob() }
      }
      return { ok: false, status: 404, json: async () => ({}), blob: async () => new Blob() }
    })
    vi.stubGlobal('fetch', stubFetch)
    Object.defineProperty(window, 'location', {
      value: { hostname: '127.0.0.1' },
      writable: true,
    })

    const wrapper = mount(CameraPreviewView, { global: { plugins: [laborantPinia()] } })
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 50))
    await flushPromises()

    expect(wrapper.get('[data-testid="preview-session-required"]').text()).toContain(
      'Buka sesi untuk memeriksa nama',
    )
    expect(wrapper.text()).not.toContain('Siswa Sintetis')
    expect(wrapper.text()).not.toContain('0.870')
    expect(wrapper.text()).not.toContain('bukan tingkat akurasi')
    expect(wrapper.find('[data-testid="preview-device-select"]').exists()).toBe(true)
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    expect(
      wrapper.findAll('input').some((input) => input.attributes('inputmode') === 'numeric'),
    ).toBe(false)
    const streamImg = wrapper.find('[data-testid="preview-stream-img"]')
    expect(streamImg.exists()).toBe(true)
    expect(streamImg.attributes('src')).toContain('/v1/stream?token=preview-1')
    expect(wrapper.findAll('.face-overlay__point')).toHaveLength(0)
    expect(wrapper.findAll('[data-testid^="face-mark-"]')).toHaveLength(0)
    const forbidden = fetchCalls.filter(
      (url) =>
        url.includes('recognition-event') ||
        url.includes('attendance') ||
        url.includes('/sessions'),
    )
    expect(forbidden).toEqual([])
    wrapper.unmount()
  })

  it('explains that identity checks wait for an active session roster', async () => {
    const nowSeconds = Date.now() / 1000
    const stubFetch = vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.endsWith('/v1/session')) {
        return { ok: true, status: 200, json: async () => ({ preview_token: 'preview-1' }) }
      }
      if (url.endsWith('/v1/status')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            device_id: 'dev-1',
            camera_open: true,
            session_active: false,
            recognition_state: 'waiting_for_session',
            display_name: null,
            diagnostic_candidate: null,
            attendance_result: null,
            updated_at: nowSeconds,
            camera_observation: {
              state: 'ready',
              message: 'Wajah siap diperiksa.',
              frame_width: 640,
              frame_height: 480,
              face_count: 1,
              faces: [{ x: 0.2, y: 0.1, width: 0.6, height: 0.75, acceptable: true }],
            },
          }),
        }
      }
      return { ok: false, status: 404, json: async () => ({}), blob: async () => new Blob() }
    })
    vi.stubGlobal('fetch', stubFetch)
    Object.defineProperty(window, 'location', {
      value: { hostname: '127.0.0.1' },
      writable: true,
    })

    const wrapper = mount(CameraPreviewView, { global: { plugins: [laborantPinia()] } })
    try {
      await flushPromises()
      await new Promise((resolve) => setTimeout(resolve, 50))
      await flushPromises()

      expect(wrapper.get('[aria-label="Status pengenalan siswa"]').text()).toContain(
        'Sesi belum dibuka',
      )
      expect(wrapper.get('[data-testid="preview-session-required"]').text()).toContain(
        'Acuan wajah yang sudah terdaftar dipakai saat siswa ada di daftar sesi aktif',
      )
      expect(wrapper.find('[data-testid="preview-unmatched-face"]').exists()).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })

  it('explains when the AI_EDGE camera is paused and waits before attaching the stream', async () => {
    const nowSeconds = Date.now() / 1000
    const stubFetch = vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.endsWith('/v1/session')) {
        return { ok: true, status: 201, json: async () => ({ preview_token: 'preview-1' }) }
      }
      if (url.endsWith('/v1/status')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            device_id: 'dev-1',
            camera_open: false,
            session_active: false,
            recognition_state: 'camera_disabled',
            display_name: null,
            updated_at: nowSeconds,
            camera_observation: {
              state: 'unavailable',
              message: 'Frame kamera terputus.',
              frame_width: 0,
              frame_height: 0,
              face_count: 0,
              faces: [],
            },
          }),
        }
      }
      return { ok: false, status: 404, json: async () => ({}) }
    })
    vi.stubGlobal('fetch', stubFetch)
    Object.defineProperty(window, 'location', {
      value: { hostname: '127.0.0.1' },
      writable: true,
    })

    const wrapper = mount(CameraPreviewView, { global: { plugins: [laborantPinia()] } })
    try {
      await flushPromises()
      await new Promise((resolve) => setTimeout(resolve, 50))
      await flushPromises()

      expect(wrapper.get('[data-testid="preview-camera-placeholder"]').text()).toContain(
        'Lanjutkan kamera dari halaman Perangkat',
      )
      expect(wrapper.get('[aria-label="Status pengenalan siswa"]').text()).toContain(
        'Kamera dijeda',
      )
      expect(wrapper.find('[data-testid="preview-mesh-status"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="preview-capture-fps"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="preview-stream-img"]').exists()).toBe(false)
      expect(wrapper.find('.face-overlay').exists()).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })

  it('keeps confirmed attendance visible when a later frame has no match', async () => {
    const nowSeconds = Date.now() / 1000
    const stubFetch = vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.endsWith('/v1/session')) {
        return { ok: true, status: 200, json: async () => ({ preview_token: 'preview-1' }) }
      }
      if (url.endsWith('/v1/status')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            device_id: 'dev-1',
            camera_open: true,
            session_active: true,
            recognition_state: 'no_match',
            display_name: null,
            diagnostic_candidate: null,
            attendance_result: {
              decision: 'recorded',
              attendance_status: 'present',
              display_name: 'Yoga',
              class_name: 'MIPATES',
              updated_at: nowSeconds,
            },
            updated_at: nowSeconds,
            camera_observation: {
              state: 'ready',
              message: 'Wajah siap diperiksa.',
              frame_width: 640,
              frame_height: 480,
              face_count: 1,
              faces: [
                {
                  x: 0.2,
                  y: 0.1,
                  width: 0.5,
                  height: 0.7,
                  acceptable: true,
                  reason_codes: [],
                },
              ],
            },
          }),
        }
      }
      return { ok: false, status: 404, json: async () => ({}) }
    })
    vi.stubGlobal('fetch', stubFetch)
    Object.defineProperty(window, 'location', {
      value: { hostname: '127.0.0.1' },
      writable: true,
    })

    const wrapper = mount(CameraPreviewView, { global: { plugins: [laborantPinia()] } })
    try {
      await flushPromises()
      await new Promise((resolve) => setTimeout(resolve, 50))
      await flushPromises()

      const identityPanel = wrapper.get('[aria-label="Status pengenalan siswa"]')
      expect(identityPanel.text()).toContain('Yoga')
      expect(identityPanel.text()).toContain('Presensi tercatat')
      expect(wrapper.find('[data-testid="preview-unmatched-face"]').exists()).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })

  it('falls back to frame polling when the stream errors', async () => {
    const fetchCalls: string[] = []
    const nowSeconds = Date.now() / 1000
    const stubFetch = vi.fn(async (input: unknown) => {
      const url = String(input)
      fetchCalls.push(url)
      if (url.endsWith('/v1/session')) {
        return { ok: true, status: 200, json: async () => ({ preview_token: 'preview-1' }) }
      }
      if (url.endsWith('/v1/status')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            device_id: 'dev-1',
            camera_open: true,
            session_active: false,
            recognition_state: 'preview_only',
            display_name: null,
            diagnostic_candidate: null,
            attendance_result: null,
            updated_at: nowSeconds,
          }),
        }
      }
      if (url.endsWith('/v1/frame.jpg')) {
        return { ok: true, status: 200, blob: async () => new Blob(['frame']) }
      }
      return { ok: false, status: 404, json: async () => ({}), blob: async () => new Blob() }
    })
    vi.stubGlobal('fetch', stubFetch)
    Object.defineProperty(window, 'location', {
      value: { hostname: '127.0.0.1' },
      writable: true,
    })
    const urlWithStubs = URL as unknown as {
      createObjectURL: () => string
      revokeObjectURL: (url: string) => void
    }
    urlWithStubs.createObjectURL = () => 'blob:fallback-frame'
    urlWithStubs.revokeObjectURL = () => {}

    const wrapper = mount(CameraPreviewView, { global: { plugins: [laborantPinia()] } })
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 100))
    await flushPromises()
    // Mode stream: belum ada fetch frame.jpg (browser memuat via <img>).
    expect(fetchCalls.some((url) => url.endsWith('/v1/frame.jpg'))).toBe(false)

    await wrapper.find('[data-testid="preview-stream-img"]').trigger('error')
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 200))
    await flushPromises()

    expect(fetchCalls.some((url) => url.endsWith('/v1/frame.jpg'))).toBe(true)
    expect(wrapper.find('[data-testid="camera-frame"] img').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('camera preview source switching', () => {
  beforeEach(() => {
    mockRouteQuery.value = { transport: 'poll' }
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    mockRouteQuery.value = {}
  })

  function stubCompanion(options: { framesOk: number; failStatus?: number }) {
    let frameCalls = 0
    const nowSeconds = Date.now() / 1000
    const stubFetch = vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.endsWith('/v1/session')) {
        return { ok: true, status: 200, json: async () => ({ preview_token: 'preview-1' }) }
      }
      if (url.endsWith('/v1/status')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            device_id: 'dev-1',
            camera_open: true,
            session_active: false,
            recognition_state: 'preview_only',
            display_name: null,
            diagnostic_candidate: null,
            attendance_result: null,
            updated_at: nowSeconds,
          }),
        }
      }
      if (url.endsWith('/v1/frame.jpg')) {
        frameCalls += 1
        if (frameCalls <= options.framesOk) {
          return { ok: true, status: 200, blob: async () => new Blob(['frame']) }
        }
        const failStatus = options.failStatus ?? 503
        return { ok: false, status: failStatus, blob: async () => new Blob() }
      }
      return { ok: false, status: 404, json: async () => ({}), blob: async () => new Blob() }
    })
    vi.stubGlobal('fetch', stubFetch)
    Object.defineProperty(window, 'location', {
      value: { hostname: '127.0.0.1' },
      writable: true,
    })
    const urlWithStubs = URL as unknown as {
      createObjectURL: () => string
      revokeObjectURL: (url: string) => void
    }
    urlWithStubs.createObjectURL = () => `blob:frame-${frameCalls}`
    urlWithStubs.revokeObjectURL = () => {}
  }

  it('clears the old frame when the source changes', async () => {
    stubCompanion({ framesOk: 99 })
    const wrapper = mount(CameraPreviewView, { global: { plugins: [laborantPinia()] } })
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 200))
    await flushPromises()
    expect(wrapper.find('[data-testid="camera-frame"] img').exists()).toBe(true)

    await wrapper.find('[data-testid="preview-device-select"]').setValue('dev-2')
    await flushPromises()

    expect(wrapper.find('[data-testid="camera-frame"] img').exists()).toBe(false)
    expect(wrapper.text()).toContain('Perangkat kamera berbeda')
    expect(wrapper.text()).toContain('Agent pada komputer ini milik Kamera Lab 1')
    wrapper.unmount()
  })

  it('meminta fullscreen pada root halaman saat tombol diklik', async () => {
    stubCompanion({ framesOk: 1 })
    const wrapper = mount(CameraPreviewView, { global: { plugins: [laborantPinia()] } })
    await flushPromises()
    const requestFullscreen = vi.fn(async () => undefined)
    const root = wrapper.element as HTMLElement
    Object.defineProperty(root, 'requestFullscreen', { value: requestFullscreen, writable: true })
    const button = wrapper
      .findAll('button')
      .find((candidate) => candidate.text().includes('Layar penuh'))
    expect(button?.exists()).toBe(true)
    await button?.trigger('click')
    await flushPromises()
    expect(requestFullscreen).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('warns when the frame freezes', async () => {
    stubCompanion({ framesOk: 2, failStatus: 500 })
    const wrapper = mount(CameraPreviewView, { global: { plugins: [laborantPinia()] } })
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 150))
    await flushPromises()
    expect(wrapper.find('[data-testid="camera-frame"] img').exists()).toBe(true)
    expect(wrapper.find('[data-testid="preview-stale-warning"]').exists()).toBe(false)

    const realNow = Date.now()
    vi.spyOn(Date, 'now').mockReturnValue(realNow + 10_000)
    await new Promise((resolve) => setTimeout(resolve, 700))
    await flushPromises()

    const warning = wrapper.find('[data-testid="preview-stale-warning"]')
    expect(warning.exists()).toBe(true)
    expect(warning.text()).toContain('Frame beku')
    wrapper.unmount()
  })
})
