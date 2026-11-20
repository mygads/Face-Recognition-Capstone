import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import FaceOverlay from '../components/FaceOverlay.vue'
import EnrollmentView from './EnrollmentView.vue'

const api = vi.hoisted(() => ({
  listClasses: vi.fn(),
  listClassEnrollmentStatus: vi.fn(),
  listFaceTemplates: vi.fn(),
  revokeFaceTemplate: vi.fn(),
  submitEnrollmentCaptures: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class extends Error {
    code?: string
    details?: { field: string; message: string }[]
    constructor(_status?: number, code?: string, message?: string) {
      super(message)
      if (code !== undefined) this.code = code
    }
  },
  ...api,
}))

const enrolledStudent = {
  id: 'student-enrolled',
  student_number: '2403',
  full_name: 'Tio Mahendra',
  template_status: 'enrolled',
}
const pendingStudent = {
  id: 'student-pending',
  student_number: '2407',
  full_name: 'Sinta Aulia',
  template_status: 'not_enrolled',
}

function mountView() {
  let previewSessionCounter = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/v1/session') && init?.method === 'POST') {
        return {
          ok: true,
          status: 201,
          json: async () => ({
            preview_token: `synthetic-preview-token-${++previewSessionCounter}`,
          }),
        } as Response
      }
      if (url.endsWith('/v1/session') && init?.method === 'DELETE') {
        return { ok: true, status: 200, json: async () => ({ closed: true }) } as Response
      }
      if (url.endsWith('/v1/status')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            camera_open: true,
            camera_observation: {
              state: 'ready',
              message: 'Frame siap diperiksa.',
              frame_width: 640,
              frame_height: 480,
              face_count: 1,
              faces: [
                {
                  x: 0.25,
                  y: 0.12,
                  width: 0.5,
                  height: 0.7,
                  acceptable: true,
                  landmarks: [
                    [0.4, 0.35],
                    [0.6, 0.35],
                    [0.5, 0.48],
                    [0.42, 0.6],
                    [0.58, 0.6],
                  ],
                },
              ],
            },
          }),
        } as Response
      }
      return { ok: false, status: 404 } as Response
    }),
  )
  const pinia = createPinia()
  useAuthStore(pinia).$patch({ accessToken: 'synthetic-token', expiresAt: Date.now() + 60_000 })
  return mount(EnrollmentView, {
    global: {
      plugins: [pinia],
      stubs: { UiPageHeader: { template: '<div><slot name="actions" /><slot /></div>' } },
    },
  })
}

describe('enrollment revoke dialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listClasses.mockResolvedValue({
      items: [
        {
          id: 'class-1',
          code: 'XII-RPL-1',
          name: 'Kelas XII RPL 1',
          academic_year: '2026-2027',
          grade: 12,
          homeroom_teacher_id: null,
          is_active: true,
        },
      ],
      pagination: { total: 1, limit: 100, offset: 0 },
    })
    api.listClassEnrollmentStatus.mockResolvedValue([enrolledStudent, pendingStudent])
    api.listFaceTemplates.mockResolvedValue([{ id: 'template-1' }])
    api.revokeFaceTemplate.mockResolvedValue({ id: 'template-1' })
  })

  it('membuka dialog konfirmasi kritis dan memvalidasi alasan', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper
      .find('[data-testid="enrollment-student-student-enrolled"] .st-rowbtn')
      .trigger('click')
    await flushPromises()

    const opener = wrapper.find('[data-testid="revoke-enrollment-template"]')
    expect(opener.exists()).toBe(true)
    await opener.trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="revoke-identity"]').text()).toContain('Tio Mahendra')
    const confirm = wrapper.find('[data-testid="confirm-revoke-template"]')
    expect(confirm.attributes('disabled')).toBeDefined()

    await wrapper.find('[data-testid="revoke-reason-input"]').setValue('kurang')
    expect(
      wrapper.find('[data-testid="confirm-revoke-template"]').attributes('disabled'),
    ).toBeDefined()

    await wrapper
      .find('[data-testid="revoke-reason-input"]')
      .setValue('Kualitas tangkapan lama buruk dan sering galat')
    expect(
      wrapper.find('[data-testid="confirm-revoke-template"]').attributes('disabled'),
    ).toBeUndefined()

    await wrapper.find('[data-testid="confirm-revoke-template"]').trigger('click')
    await flushPromises()

    expect(api.revokeFaceTemplate).toHaveBeenCalledWith('template-1')
    expect(wrapper.find('[data-testid="revoke-identity"]').exists()).toBe(false)
  })
})

describe('enrollment camera source', () => {
  it('memproses stream MJPEG AI_EDGE dengan mesh lokal meski img belum complete', async () => {
    api.listClasses.mockResolvedValue({
      items: [
        {
          id: 'class-1',
          code: 'XII-RPL-1',
          name: 'Kelas XII RPL 1',
          academic_year: '2026-2027',
          grade: 12,
          homeroom_teacher_id: null,
          is_active: true,
        },
      ],
      pagination: { total: 1, limit: 100, offset: 0 },
    })
    api.listClassEnrollmentStatus.mockResolvedValue([pendingStudent])

    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn(async () => ({ width: 640, height: 480, close: vi.fn() })),
    )
    class FakeWorker {
      private handlers = new Map<string, ((event: MessageEvent) => void)[]>()
      addEventListener(type: string, handler: (event: MessageEvent) => void): void {
        this.handlers.set(type, [...(this.handlers.get(type) ?? []), handler])
      }
      postMessage(message: { type: string }): void {
        const data =
          message.type === 'initialize'
            ? { type: 'ready', delegate: 'CPU' }
            : {
                type: 'result',
                delegate: 'CPU',
                width: 640,
                height: 480,
                inferenceMs: 4,
                faces: [
                  {
                    x: 0.2,
                    y: 0.1,
                    width: 0.6,
                    height: 0.75,
                    landmarks: Array.from({ length: 478 }, () => [0.5, 0.5]),
                  },
                ],
              }
        queueMicrotask(() => {
          for (const handler of this.handlers.get('message') ?? []) {
            handler({ data } as MessageEvent)
          }
        })
      }
      terminate(): void {}
    }
    vi.stubGlobal('Worker', FakeWorker)
    const wrapper = mountView()
    try {
      await flushPromises()
      expect(wrapper.find('[data-testid="enrollment-lab-stream"]').exists()).toBe(true)
      expect(wrapper.get('[data-testid="enrollment-lab-stream"]').classes()).toContain(
        'enrollment-view__camera--mirror',
      )
      const image = wrapper.get('[data-testid="enrollment-lab-stream"]').element as HTMLImageElement
      Object.defineProperties(image, {
        complete: { configurable: true, value: false },
        naturalWidth: { configurable: true, value: 640 },
        naturalHeight: { configurable: true, value: 480 },
      })
      await wrapper.get('[data-testid="enrollment-lab-stream"]').trigger('load')
      await new Promise((resolve) => setTimeout(resolve, 80))
      await flushPromises()

      expect(wrapper.get('[data-testid="enrollment-face-guidance"]').text()).toContain(
        'Wajah siap ditangkap',
      )
      expect(wrapper.get('[data-testid="enrollment-lab-mesh-status"]').text()).toContain(
        'Mesh aktif · 478 titik',
      )
      expect(wrapper.find('.enrollment-view__face-overlay').exists()).toBe(true)
      expect(wrapper.findComponent(FaceOverlay).props('fit')).toBe('contain')
      expect(wrapper.findComponent(FaceOverlay).props('mirrored')).toBe(true)
      expect(
        (wrapper.get('.enrollment-view__camera-frame').element as HTMLElement).style.aspectRatio,
      ).toBe('640 / 480')
      expect(wrapper.findAll('.face-overlay__skeleton')).toHaveLength(0)
      expect(wrapper.findAll('.face-overlay__point')).toHaveLength(0)
      expect(wrapper.findAll('.enrollment-view__face-overlay rect')).toHaveLength(0)
      expect(wrapper.text()).not.toContain('Sejajarkan wajah')
      expect(
        (wrapper.get('[data-testid="start-enrollment-capture"]').element as HTMLButtonElement)
          .disabled,
      ).toBe(false)
    } finally {
      wrapper.unmount()
      vi.restoreAllMocks()
      vi.unstubAllGlobals()
    }
  })

  it('opsi kamera lab menampilkan stream agent dan satu pemilik', async () => {
    api.listClasses.mockResolvedValue({
      items: [
        {
          id: 'class-1',
          code: 'XII-RPL-1',
          name: 'Kelas XII RPL 1',
          academic_year: '2026-2027',
          grade: 12,
          homeroom_teacher_id: null,
          is_active: true,
        },
      ],
      pagination: { total: 1, limit: 100, offset: 0 },
    })
    api.listClassEnrollmentStatus.mockResolvedValue([pendingStudent])
    const wrapper = mountView()
    await flushPromises()
    await wrapper
      .find('[data-testid="enrollment-student-student-pending"] .st-rowbtn')
      .trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="enrollment-source-lab"]').setValue('lab')
    expect(wrapper.find('[data-testid="enrollment-lab-stream"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Satu kamera satu pemilik')
    wrapper.unmount()
  })

  it('memperbarui sesi AI_EDGE saat stream gagal lalu menyambungkannya kembali', async () => {
    api.listClasses.mockResolvedValue({
      items: [
        {
          id: 'class-1',
          code: 'XII-RPL-1',
          name: 'Kelas XII RPL 1',
          academic_year: '2026-2027',
          grade: 12,
          homeroom_teacher_id: null,
          is_active: true,
        },
      ],
      pagination: { total: 1, limit: 100, offset: 0 },
    })
    api.listClassEnrollmentStatus.mockResolvedValue([pendingStudent])
    const wrapper = mountView()
    try {
      await flushPromises()
      const firstStream = wrapper.get('[data-testid="enrollment-lab-stream"]')
      const firstUrl = firstStream.attributes('src')

      await firstStream.trigger('error')
      expect(wrapper.find('[data-testid="enrollment-lab-stream"]').exists()).toBe(false)

      await wrapper.get('[data-testid="retry-lab-stream"]').trigger('click')
      await flushPromises()

      const reconnectedStream = wrapper.get('[data-testid="enrollment-lab-stream"]')
      expect(reconnectedStream.attributes('src')).not.toBe(firstUrl)
      expect(reconnectedStream.attributes('src')).toContain('synthetic-preview-token-2')
    } finally {
      wrapper.unmount()
    }
  })

  it('membuka webcam browser sendiri dan menggambar mesh tanpa kotak wajah', async () => {
    api.listClasses.mockResolvedValue({
      items: [
        {
          id: 'class-1',
          code: 'XII-RPL-1',
          name: 'Kelas XII RPL 1',
          academic_year: '2026-2027',
          grade: 12,
          homeroom_teacher_id: null,
          is_active: true,
        },
      ],
      pagination: { total: 1, limit: 100, offset: 0 },
    })
    api.listClassEnrollmentStatus.mockResolvedValue([pendingStudent])

    const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices')
    const originalSecureContext = Object.getOwnPropertyDescriptor(window, 'isSecureContext')
    const stopTrack = vi.fn()
    const fakeStream = {
      getTracks: () => [{ stop: stopTrack }],
    } as unknown as MediaStream
    const getUserMedia = vi.fn(async () => fakeStream)
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    })
    Object.defineProperty(window, 'isSecureContext', { configurable: true, value: true })
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn(async () => ({ close: vi.fn() })),
    )

    class FakeWorker {
      private handlers = new Map<string, ((event: MessageEvent) => void)[]>()
      addEventListener(type: string, handler: (event: MessageEvent) => void): void {
        this.handlers.set(type, [...(this.handlers.get(type) ?? []), handler])
      }
      postMessage(message: { type: string }): void {
        const data =
          message.type === 'initialize'
            ? { type: 'ready', delegate: 'CPU' }
            : {
                type: 'result',
                delegate: 'CPU',
                width: 640,
                height: 480,
                inferenceMs: 4,
                faces: [
                  {
                    x: 0.2,
                    y: 0.1,
                    width: 0.6,
                    height: 0.75,
                    landmarks: Array.from({ length: 478 }, () => [0.5, 0.5]),
                  },
                ],
              }
        queueMicrotask(() => {
          for (const handler of this.handlers.get('message') ?? []) {
            handler({ data } as MessageEvent)
          }
        })
      }
      terminate(): void {}
    }
    vi.stubGlobal('Worker', FakeWorker)

    const wrapper = mountView()
    try {
      await flushPromises()
      await wrapper.find('[data-testid="enrollment-source-device"]').setValue('device')
      await flushPromises()
      const video = wrapper.get('[data-testid="enrollment-camera"]').element as HTMLVideoElement
      expect(wrapper.get('[data-testid="enrollment-camera"]').classes()).toContain(
        'enrollment-view__camera--mirror',
      )
      Object.defineProperties(video, {
        readyState: { configurable: true, value: 2 },
        videoWidth: { configurable: true, value: 640 },
        videoHeight: { configurable: true, value: 480 },
      })
      await new Promise((resolve) => setTimeout(resolve, 80))
      await flushPromises()

      expect(getUserMedia).toHaveBeenCalledOnce()
      expect((video.srcObject as MediaStream).getTracks()).toHaveLength(1)
      expect(wrapper.get('[data-testid="enrollment-device-guidance"]').text()).toContain(
        'Wajah terdeteksi',
      )
      expect(wrapper.find('.enrollment-view__face-overlay').exists()).toBe(true)
      expect(wrapper.findComponent(FaceOverlay).props('mirrored')).toBe(true)
      expect(wrapper.findAll('.enrollment-view__face-overlay rect')).toHaveLength(0)
    } finally {
      wrapper.unmount()
      vi.restoreAllMocks()
      vi.unstubAllGlobals()
      if (originalMediaDevices) {
        Object.defineProperty(navigator, 'mediaDevices', originalMediaDevices)
      } else {
        Reflect.deleteProperty(navigator, 'mediaDevices')
      }
      if (originalSecureContext) {
        Object.defineProperty(window, 'isSecureContext', originalSecureContext)
      } else {
        Reflect.deleteProperty(window, 'isSecureContext')
      }
    }
  })

  it('menjelaskan saat webcam perangkat sedang dipakai AI_EDGE atau aplikasi lain', async () => {
    api.listClasses.mockResolvedValue({
      items: [
        {
          id: 'class-1',
          code: 'XII-RPL-1',
          name: 'Kelas XII RPL 1',
          academic_year: '2026-2027',
          grade: 12,
          homeroom_teacher_id: null,
          is_active: true,
        },
      ],
      pagination: { total: 1, limit: 100, offset: 0 },
    })
    api.listClassEnrollmentStatus.mockResolvedValue([pendingStudent])

    const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices')
    const originalSecureContext = Object.getOwnPropertyDescriptor(window, 'isSecureContext')
    const getUserMedia = vi.fn(async () => {
      throw new DOMException('Camera is busy', 'NotReadableError')
    })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    })
    Object.defineProperty(window, 'isSecureContext', { configurable: true, value: true })

    const wrapper = mountView()
    try {
      await flushPromises()
      await wrapper.find('[data-testid="enrollment-source-device"]').setValue('device')
      await flushPromises()

      expect(getUserMedia).toHaveBeenCalledOnce()
      expect(wrapper.get('[data-testid="enrollment-device-guidance"]').text()).toContain(
        'Kamera sedang dipakai aplikasi lain',
      )
      expect(wrapper.get('[data-testid="enrollment-device-guidance"]').text()).toContain(
        'Kamera lab via AI_EDGE',
      )
    } finally {
      wrapper.unmount()
      if (originalMediaDevices) {
        Object.defineProperty(navigator, 'mediaDevices', originalMediaDevices)
      } else {
        Reflect.deleteProperty(navigator, 'mediaDevices')
      }
      if (originalSecureContext) {
        Object.defineProperty(window, 'isSecureContext', originalSecureContext)
      } else {
        Reflect.deleteProperty(window, 'isSecureContext')
      }
    }
  })
})
