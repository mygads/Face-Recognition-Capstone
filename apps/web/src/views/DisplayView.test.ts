import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import DisplayView from './DisplayView.vue'

const api = vi.hoisted(() => ({
  getKioskDisplay: vi.fn(),
  getPublicDisplay: vi.fn(),
  listPublicKioskScreens: vi.fn(async () => []),
  listPublicLaboratories: vi.fn(async () => [{ id: 'lab-1', code: 'LAB-1', name: 'Lab Kimia 1' }]),
  openKioskDisplaySession: vi.fn(),
  openPublicDisplaySession: vi.fn(),
  rotateKioskDisplaySession: vi.fn(),
  rotatePublicDisplaySession: vi.fn(),
  publicDisplayStreamUrl: (token: string) => `/api/v1/public/display/stream?token=${token}`,
  kioskDisplayStreamUrl: (token: string) => `/api/v1/public/kiosk-display/stream?token=${token}`,
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  ...api,
}))

const snapshot = {
  laboratory_name: 'Lab Kimia 1',
  subject: 'Uji Larutan',
  status: 'active',
  present_count: 1,
  late_count: 1,
  total_roster: 3,
  students: [
    {
      student_number: 'S-001',
      full_name: 'Raka Pratama',
      status: 'late',
      recorded_at: '2026-11-06T06:18:00+07:00',
    },
    {
      student_number: 'S-002',
      full_name: 'Sinta Anggraini',
      status: 'present',
      recorded_at: '2026-11-06T06:05:00+07:00',
    },
    { student_number: 'S-003', full_name: 'Budi Santoso', status: 'absent', recorded_at: null },
  ],
}

describe('DisplayView ala Stitch', () => {
  it('menampilkan nama singkat tanpa NIS dan sorotan hasil terakhir', async () => {
    api.openPublicDisplaySession.mockResolvedValueOnce({
      display_token: 'tok',
      snapshot,
    })
    const w = mount(DisplayView)
    await flushPromises()
    await w.find('[data-testid="display-pin-input"]').setValue('1234')
    await w.find('form').trigger('submit.prevent')
    await flushPromises()
    const board = w.find('[data-testid="display-board"]')
    expect(board.exists()).toBe(true)
    // nama singkat ala Stitch, bukan NIS penuh
    expect(board.text()).toContain('Raka P.')
    expect(board.text()).not.toContain('S-001')
    // sorotan hasil terakhir = Raka (terbaru) dengan badge TERLAMBAT
    const spotlight = w.find('[data-testid="display-spotlight"]')
    expect(spotlight.exists()).toBe(true)
    expect(spotlight.text()).toContain('Raka P.')
    expect(spotlight.text()).toContain('TERLAMBAT')
  })
})

describe('DisplayView realtime (SSE + video lokal)', () => {
  class FakeEventSource {
    static instances: FakeEventSource[] = []
    url: string
    handlers: Record<string, ((ev: { data: string }) => void)[]> = {}
    onmessage: ((ev: { data: string }) => void) | null = null
    onerror: (() => void) | null = null
    closed = false
    constructor(url: string) {
      this.url = url
      FakeEventSource.instances.push(this)
    }
    addEventListener(type: string, cb: (ev: { data: string }) => void): void {
      this.handlers[type] = [...(this.handlers[type] ?? []), cb]
    }
    emit(type: string, data: unknown): void {
      for (const cb of this.handlers[type] ?? []) cb({ data: JSON.stringify(data) })
    }
    fail(): void {
      this.onerror?.()
    }
    close(): void {
      this.closed = true
    }
  }

  it('memakai stream SSE tanpa daftar roster dan menampilkan hasil push', async () => {
    const g = globalThis as unknown as Record<string, unknown>
    const realES = g['EventSource']
    g['EventSource'] = FakeEventSource
    FakeEventSource.instances = []
    try {
      api.openPublicDisplaySession.mockResolvedValueOnce({
        display_token: 'tok-live',
        snapshot,
      })
      const w = mount(DisplayView)
      await flushPromises()
      await w.find('[data-testid="display-pin-input"]').setValue('1234')
      await w.find('form').trigger('submit.prevent')
      await flushPromises()
      expect(FakeEventSource.instances).toHaveLength(1)
      expect(FakeEventSource.instances[0].url).toContain('/display/stream')
      // roster tidak lagi dirender di layar kiosk
      expect(w.find('[data-testid="display-board"]').text()).not.toContain('S-001')
      // push snapshot ringan lewat SSE
      FakeEventSource.instances[0].emit('snapshot', {
        laboratory_id: 'lab-1',
        laboratory_name: 'Lab Kimia 1',
        session_id: 'ses-1',
        subject: 'Uji Larutan',
        status: 'active',
        opened_at: null,
        present_count: 2,
        late_count: 0,
        waiting_count: 1,
        total_roster: 3,
        spotlight: {
          full_name: 'Sinta Anggraini',
          status: 'present',
          recorded_at: '2026-11-06T06:05:00+07:00',
        },
        server_time: '2026-11-06T06:06:00+07:00',
      })
      await flushPromises()
      const board = w.find('[data-testid="display-board"]')
      expect(board.text()).toContain('Sinta A.')
      expect(board.text()).toContain('HADIR')
      expect(board.text()).not.toContain('S-002')
    } finally {
      g['EventSource'] = realES
    }
  })

  it('jatuh kembali ke polling saat SSE gagal', async () => {
    const g = globalThis as unknown as Record<string, unknown>
    const realES = g['EventSource']
    g['EventSource'] = FakeEventSource
    FakeEventSource.instances = []
    try {
      api.openPublicDisplaySession.mockResolvedValueOnce({
        display_token: 'tok-fallback',
        snapshot,
      })
      api.getPublicDisplay.mockResolvedValueOnce(snapshot)
      const w = mount(DisplayView)
      await flushPromises()
      await w.find('[data-testid="display-pin-input"]').setValue('1234')
      await w.find('form').trigger('submit.prevent')
      await flushPromises()
      FakeEventSource.instances[0].fail()
      await flushPromises()
      expect(w.find('[data-testid="display-board"]').exists()).toBe(true)
      expect(w.find('[data-testid="display-board"]').text()).toContain('Raka P.')
    } finally {
      g['EventSource'] = realES
    }
  })
})

describe('DisplayView rotasi token', () => {
  class FakeES2 {
    static instances: FakeES2[] = []
    url: string
    handlers: Record<string, ((ev: { data: string }) => void)[]> = {}
    onerror: (() => void) | null = null
    constructor(url: string) {
      this.url = url
      FakeES2.instances.push(this)
    }
    addEventListener(type: string, cb: (ev: { data: string }) => void): void {
      this.handlers[type] = [...(this.handlers[type] ?? []), cb]
    }
    close(): void {}
  }

  it('memutar token sebelum kedaluwarsa dan menyambung ulang stream', async () => {
    const g = globalThis as unknown as Record<string, unknown>
    const realES = g['EventSource']
    g['EventSource'] = FakeES2
    FakeES2.instances = []
    vi.useFakeTimers()
    try {
      api.openPublicDisplaySession.mockResolvedValueOnce({
        display_token: 'tok-lama',
        expires_in_seconds: 3600,
        snapshot,
      })
      api.rotatePublicDisplaySession.mockResolvedValueOnce({
        display_token: 'tok-baru',
        expires_in_seconds: 3600,
        snapshot,
      })
      const w = mount(DisplayView)
      await flushPromises()
      await w.find('[data-testid="display-pin-input"]').setValue('1234')
      await w.find('form').trigger('submit.prevent')
      await flushPromises()
      expect(FakeES2.instances).toHaveLength(1)
      expect(FakeES2.instances[0].url).toContain('tok-lama')
      await vi.advanceTimersByTimeAsync(30 * 60 * 1000)
      await flushPromises()
      expect(api.rotatePublicDisplaySession).toHaveBeenCalledWith('tok-lama')
      expect(FakeES2.instances).toHaveLength(2)
      expect(FakeES2.instances[1].url).toContain('tok-baru')
    } finally {
      vi.useRealTimers()
      g['EventSource'] = realES
    }
  })
})
