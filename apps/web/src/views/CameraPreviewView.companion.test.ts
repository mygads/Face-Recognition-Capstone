import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import CameraPreviewView from './CameraPreviewView.vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
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
        health_status: 'healthy',
      },
      {
        device_id: 'dev-2',
        name: 'Kamera Lab 2',
        laboratory_id: 'lab-1',
        laboratory_name: 'LAB-1',
        health_status: 'healthy',
      },
    ],
    pagination: { page: 1, per_page: 50, total_items: 2, total_pages: 1 },
  })),
  listLaboratories: vi.fn(async () => ({
    items: [{ id: 'lab-1', code: 'LAB-1', name: 'Lab 1' }],
    pagination: { page: 1, per_page: 50, total_items: 1, total_pages: 1 },
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
  })

  it('labels candidates as non-accuracy and never creates attendance', async () => {
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

    expect(wrapper.text()).toContain('bukan tingkat akurasi')
    const forbidden = fetchCalls.filter(
      (url) =>
        url.includes('recognition-event') ||
        url.includes('attendance') ||
        url.includes('/sessions'),
    )
    expect(forbidden).toEqual([])
    wrapper.unmount()
  })
})

describe('camera preview source switching', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
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
    expect(wrapper.find('.camera-preview-view__frame-stage img').exists()).toBe(true)

    await wrapper.find('[data-testid="preview-device-select"]').setValue('dev-2')
    await flushPromises()

    expect(wrapper.find('.camera-preview-view__frame-stage img').exists()).toBe(false)
    expect(wrapper.text()).toContain('Menghubungkan ke agent')
    wrapper.unmount()
  })

  it('warns when the frame freezes', async () => {
    stubCompanion({ framesOk: 2, failStatus: 500 })
    const wrapper = mount(CameraPreviewView, { global: { plugins: [laborantPinia()] } })
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 150))
    await flushPromises()
    expect(wrapper.find('.camera-preview-view__frame-stage img').exists()).toBe(true)
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
