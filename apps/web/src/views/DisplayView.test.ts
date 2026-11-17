import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import DisplayView from './DisplayView.vue'

const api = vi.hoisted(() => ({
  getKioskDisplay: vi.fn(),
  getPublicDisplay: vi.fn(),
  listPublicKioskScreens: vi.fn(
    async (): Promise<
      { device_id: string; display_name: string; camera_label: string | null }[]
    > => [],
  ),
  listPublicLaboratories: vi.fn(async () => [{ id: 'lab-1', code: 'LAB-1', name: 'Lab Kimia 1' }]),
  openKioskDisplaySession: vi.fn(),
  openPublicDisplaySession: vi.fn(),
  rotateKioskDisplaySession: vi.fn(),
  rotatePublicDisplaySession: vi.fn(),
  publicDisplayStreamUrl: (token: string) => `/api/v1/public/display/stream?token=${token}`,
  kioskDisplayStreamUrl: (token: string) => `/api/v1/public/kiosk-display/stream?token=${token}`,
  publicDisplayStreamPath: () => '/api/v1/public/display/stream',
  kioskDisplayStreamPath: () => '/api/v1/public/kiosk-display/stream',
  streamDisplayUpdates: vi.fn(
    async (
      _path: string,
      _token: string,
      _signal: AbortSignal,
      _onEvent: (event: string, data: string, done: () => void) => void,
    ): Promise<void> => {
      void _path
      void _token
      void _signal
      void _onEvent
      throw new Error('stream off')
    },
  ),
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
    let streamHandler: ((event: string, data: string, done: () => void) => void) | null = null
    api.streamDisplayUpdates.mockImplementationOnce(
      async (
        _path: string,
        _token: string,
        _signal: AbortSignal,
        onEvent: (event: string, data: string, done: () => void) => void,
      ) => {
        streamHandler = onEvent
        await new Promise(() => undefined)
      },
    )
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
      // Jalur utama: fetch + header Authorization, bukan EventSource query-token.
      expect(api.streamDisplayUpdates).toHaveBeenCalled()
      const call = api.streamDisplayUpdates.mock.calls[0] as unknown[]
      expect(String(call[0])).toContain('/display/stream')
      expect(call[1]).toBe('tok-live')
      expect(FakeEventSource.instances).toHaveLength(0)
      // roster tidak lagi dirender di layar kiosk
      expect(w.find('[data-testid="display-board"]').text()).not.toContain('S-001')
      // push snapshot ringan lewat SSE
      expect(streamHandler).not.toBeNull()
      streamHandler!(
        'snapshot',
        JSON.stringify({
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
        }),
        () => undefined,
      )
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

describe('DisplayView sinyal agent lokal', () => {
  class FakeEventSource {
    static instances: FakeEventSource[] = []
    url: string
    private handlers: Record<string, Array<(ev: unknown) => void>> = {}
    constructor(url: string) {
      this.url = url
      FakeEventSource.instances.push(this)
    }
    addEventListener(type: string, cb: (ev: unknown) => void): void {
      this.handlers[type] = [...(this.handlers[type] ?? []), cb]
    }
    emit(type: string, data: unknown): void {
      for (const cb of this.handlers[type] ?? []) cb({ data: JSON.stringify(data) })
    }
    close(): void {}
  }

  async function mountLiveBoard(hint: unknown): Promise<ReturnType<typeof mount>> {
    const g = globalThis as unknown as Record<string, unknown>
    const realES = g['EventSource']
    g['EventSource'] = FakeEventSource
    FakeEventSource.instances = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => hint,
      })),
    )
    api.openPublicDisplaySession.mockResolvedValueOnce({
      display_token: 'tok-hint',
      snapshot,
    })
    const w = mount(DisplayView)
    await flushPromises()
    await w.find('[data-testid="display-pin-input"]').setValue('1234')
    await w.find('form').trigger('submit.prevent')
    await flushPromises()
    FakeEventSource.instances[0].emit('snapshot', {
      laboratory_id: 'lab-1',
      laboratory_name: 'Lab Kimia 1',
      session_id: 'ses-1',
      subject: 'Uji Larutan',
      status: 'active',
      opened_at: null,
      present_count: 1,
      late_count: 0,
      waiting_count: 2,
      total_roster: 3,
      spotlight: null,
      server_time: new Date().toISOString(),
    })
    await flushPromises()
    await flushPromises()
    g['EventSource'] = realES
    return w
  }

  it('menampilkan Memverifikasi saat wajah terdeteksi tanpa membocorkan nama', async () => {
    const w = await mountLiveBoard({
      session_active: true,
      camera_open: true,
      recognition_state: 'collecting',
      face_present: true,
      face_count: 1,
      attendance_result: null,
    })
    try {
      const chip = w.find('[data-testid="display-verifying"]')
      expect(chip.exists()).toBe(true)
      expect(chip.text()).toContain('Memverifikasi')
      expect(chip.attributes('role')).toBe('status')
    } finally {
      w.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('menyembunyikan indikator saat hint gagal dijangkau', async () => {
    const g = globalThis as unknown as Record<string, unknown>
    const realES = g['EventSource']
    g['EventSource'] = FakeEventSource
    FakeEventSource.instances = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('agent tidak di PC ini')
      }),
    )
    api.openPublicDisplaySession.mockResolvedValueOnce({
      display_token: 'tok-hint-off',
      snapshot,
    })
    const w = mount(DisplayView)
    try {
      await flushPromises()
      await w.find('[data-testid="display-pin-input"]').setValue('1234')
      await w.find('form').trigger('submit.prevent')
      await flushPromises()
      expect(w.find('[data-testid="display-verifying"]').exists()).toBe(false)
      expect(w.find('[data-testid="display-board"]').exists()).toBe(true)
    } finally {
      g['EventSource'] = realES
      w.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('menyembunyikan gambar basi saat stream live tetapi hint tak segar', async () => {
    const g = globalThis as unknown as Record<string, unknown>
    const realES = g['EventSource']
    g['EventSource'] = FakeEventSource
    FakeEventSource.instances = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('agent mati di tengah jalan')
      }),
    )
    api.openPublicDisplaySession.mockResolvedValueOnce({
      display_token: 'tok-hint-stale',
      snapshot,
    })
    const w = mount(DisplayView)
    try {
      await flushPromises()
      await w.find('[data-testid="display-pin-input"]').setValue('1234')
      await w.find('form').trigger('submit.prevent')
      await flushPromises()
      FakeEventSource.instances[0].emit('snapshot', {
        laboratory_id: 'lab-1',
        laboratory_name: 'Lab Kimia 1',
        session_id: 'ses-1',
        subject: 'Uji Larutan',
        status: 'active',
        opened_at: null,
        present_count: 0,
        late_count: 0,
        waiting_count: 3,
        total_roster: 3,
        spotlight: null,
        server_time: new Date().toISOString(),
      })
      await flushPromises()
      // Gambar masih tampil saat status idle (upaya koneksi awal).
      expect(w.find('[data-testid="display-agent-video"]').exists()).toBe(true)
      // Setelah frame pertama, stream diklaim live tetapi hint basi:
      // gambar beku disembunyikan, bukan disajikan sebagai live.
      await w.find('[data-testid="display-agent-video"]').trigger('load')
      await flushPromises()
      expect(w.find('[data-testid="display-agent-video"]').exists()).toBe(false)
      expect(w.text()).toContain('Menghubungkan ulang')
      expect(w.find('[data-testid="face-overlay"]').exists()).toBe(false)
    } finally {
      g['EventSource'] = realES
      w.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('menambahkan token stream kios ke URL hint/stream bila dikonfigurasi', async () => {
    window.localStorage.setItem('presensi.kiosk_stream_token', 'kios-token-1')
    try {
      const w = await mountLiveBoard({
        session_active: true,
        camera_open: true,
        recognition_state: null,
        face_present: false,
        face_count: 0,
        attendance_result: null,
      })
      try {
        const img = w.find('[data-testid="display-agent-video"]')
        expect(img.exists()).toBe(true)
        expect(img.attributes('src') ?? '').toContain('token=kios-token-1')
        const fetchMock = fetch as unknown as { mock: { calls: unknown[][] } }
        const hintCall = fetchMock.mock.calls.find((args) => String(args[0]).includes('kiosk-hint'))
        expect(hintCall).toBeDefined()
        expect(String(hintCall?.[0])).toContain('token=kios-token-1')
      } finally {
        w.unmount()
        vi.unstubAllGlobals()
      }
    } finally {
      window.localStorage.removeItem('presensi.kiosk_stream_token')
    }
  })

  it('menyembunyikan video saat hint berasal dari perangkat berbeda', async () => {
    const g = globalThis as unknown as Record<string, unknown>
    const realES = g['EventSource']
    g['EventSource'] = FakeEventSource
    FakeEventSource.instances = []
    try {
      // Satu kiosk terpasang -> deviceId terpilih otomatis (dev-A).
      api.listPublicKioskScreens.mockResolvedValueOnce([
        { device_id: 'dev-A', display_name: 'Kiosk A', camera_label: 'Pintu 01' },
      ])
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => ({
          ok: true,
          json: async () => ({
            device_id: 'dev-B',
            session_active: true,
            camera_open: true,
            recognition_state: null,
            face_present: false,
            face_count: 0,
            attendance_result: null,
          }),
        })),
      )
      api.openKioskDisplaySession.mockResolvedValueOnce({
        display_token: 'tok-kiosk',
        snapshot,
      })
      const w = mount(DisplayView)
      await flushPromises()
      await w.find('[data-testid="display-pin-input"]').setValue('1234')
      await w.find('form').trigger('submit.prevent')
      await flushPromises()
      FakeEventSource.instances[0].emit('snapshot', {
        laboratory_id: 'lab-1',
        laboratory_name: 'Lab Kimia 1',
        session_id: 'ses-1',
        subject: 'Uji Larutan',
        status: 'active',
        opened_at: null,
        present_count: 1,
        late_count: 0,
        waiting_count: 2,
        total_roster: 3,
        spotlight: null,
        server_time: new Date().toISOString(),
      })
      await flushPromises()
      await flushPromises()
      expect(w.find('[data-testid="display-board"]').exists()).toBe(true)
      // Pairing dev-A vs hint dev-B: tidak ada gambar, ada peringatan.
      expect(w.find('[data-testid="display-agent-video"]').exists()).toBe(false)
      expect(w.find('[data-testid="face-overlay"]').exists()).toBe(false)
      expect(w.text()).toContain('Kamera Tidak Sesuai')
      expect(w.text()).toContain('dipasangkan ke kamera lain')
    } finally {
      g['EventSource'] = realES
      vi.unstubAllGlobals()
    }
  })

  it('menyembunyikan gambar saat kamera lab dilaporkan mati', async () => {
    const w = await mountLiveBoard({
      session_active: true,
      camera_open: false,
      recognition_state: null,
      face_present: false,
      face_count: 0,
      attendance_result: null,
    })
    try {
      await flushPromises()
      expect(w.find('[data-testid="display-agent-video"]').exists()).toBe(false)
      expect(w.text()).toContain('Kamera tidak tersedia')
      expect(w.find('[data-testid="face-overlay"]').exists()).toBe(false)
    } finally {
      w.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('mencoba ulang stream agent otomatis lalu pulih saat frame tersedia', async () => {
    vi.useFakeTimers()
    try {
      const w = await mountLiveBoard({
        session_active: true,
        camera_open: true,
        recognition_state: null,
        face_present: false,
        face_count: 0,
        attendance_result: null,
      })
      try {
        const first = w.find('[data-testid="display-agent-video"]')
        expect(first.exists()).toBe(true)
        expect(first.attributes('src') ?? '').not.toContain('retry=')
        // 503 awal (buffer JPEG belum ada) -> error -> gambar dilepas.
        await first.trigger('error')
        await flushPromises()
        expect(w.find('[data-testid="display-agent-video"]').exists()).toBe(false)
        expect(w.text()).toContain('Stream Lab Terputus')
        // Backoff pertama 1 detik: belum ada upaya ulang sebelum waktunya.
        await vi.advanceTimersByTimeAsync(999)
        expect(w.find('[data-testid="display-agent-video"]').exists()).toBe(false)
        await vi.advanceTimersByTimeAsync(1)
        const retry1 = w.find('[data-testid="display-agent-video"]')
        expect(retry1.exists()).toBe(true)
        expect(retry1.attributes('src') ?? '').toContain('retry=1')
        // Gagal lagi -> backoff kedua 2 detik.
        await retry1.trigger('error')
        await flushPromises()
        await vi.advanceTimersByTimeAsync(1999)
        expect(w.find('[data-testid="display-agent-video"]').exists()).toBe(false)
        await vi.advanceTimersByTimeAsync(1)
        const retry2 = w.find('[data-testid="display-agent-video"]')
        expect(retry2.exists()).toBe(true)
        expect(retry2.attributes('src') ?? '').toContain('retry=2')
        // Frame tersedia -> live dan hitungan retry direset ke backoff awal.
        await retry2.trigger('load')
        await flushPromises()
        await retry2.trigger('error')
        await flushPromises()
        await vi.advanceTimersByTimeAsync(1000)
        const retryAgain = w.find('[data-testid="display-agent-video"]')
        expect(retryAgain.exists()).toBe(true)
        expect(retryAgain.attributes('src') ?? '').toContain('retry=1')
      } finally {
        w.unmount()
        vi.unstubAllGlobals()
      }
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('DisplayView kamera lokal', () => {
  class FakeES {
    static instances: FakeES[] = []
    url: string
    private handlers: Record<string, Array<(ev: unknown) => void>> = {}
    constructor(url: string) {
      this.url = url
      FakeES.instances.push(this)
    }
    addEventListener(type: string, cb: (ev: unknown) => void): void {
      this.handlers[type] = [...(this.handlers[type] ?? []), cb]
    }
    close(): void {}
  }

  it('menampilkan stream agent sebagai primer tanpa membuka kamera browser', async () => {
    const g = globalThis as unknown as Record<string, unknown>
    const realES = g['EventSource']
    g['EventSource'] = FakeES
    FakeES.instances = []
    const fakeTrack = { stop: vi.fn() }
    const fakeStream = { getTracks: () => [fakeTrack] }
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    const realMediaDevices = window.navigator.mediaDevices
    Object.defineProperty(window.navigator, 'mediaDevices', {
      value: { getUserMedia: vi.fn(async () => fakeStream) },
      configurable: true,
    })
    const realPlay = HTMLMediaElement.prototype.play
    HTMLMediaElement.prototype.play = vi.fn(async () => undefined) as unknown as () => Promise<void>
    api.openPublicDisplaySession.mockResolvedValueOnce({ display_token: 'tok-cam', snapshot })
    const w = mount(DisplayView)
    try {
      await flushPromises()
      await w.find('[data-testid="display-pin-input"]').setValue('1234')
      await w.find('form').trigger('submit.prevent')
      await flushPromises()
      await flushPromises()
      // Single-owner: browser tidak membuka kamera; stream agent yang tampil.
      expect(window.navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
      expect(w.find('[data-testid="display-agent-video"]').exists()).toBe(true)
      // Fallback diagnostik: stream gagal lalu operator meminta kamera perangkat.
      await w.find('[data-testid="display-agent-video"]').trigger('error')
      await w
        .findAll('button')
        .find((b) => b.text().includes('diagnostik'))!
        .trigger('click')
      await flushPromises()
      await flushPromises()
      const video = w.find('[data-testid="display-local-video"]')
      expect(video.exists()).toBe(true)
      expect((video.element as unknown as { srcObject: unknown }).srcObject).toBe(fakeStream)
    } finally {
      w.unmount()
      g['EventSource'] = realES
      Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
      Object.defineProperty(window.navigator, 'mediaDevices', {
        value: realMediaDevices,
        configurable: true,
      })
      HTMLMediaElement.prototype.play = realPlay
    }
  })
})

describe('DisplayView sorotan aman (grace + sumber + basi)', () => {
  class FreshES {
    static instances: FreshES[] = []
    url: string
    handlers: Record<string, Array<(ev: { data: string }) => void>> = {}
    constructor(url: string) {
      this.url = url
      FreshES.instances.push(this)
    }
    addEventListener(type: string, cb: (ev: { data: string }) => void): void {
      this.handlers[type] = [...(this.handlers[type] ?? []), cb]
    }
    emit(type: string, data: unknown): void {
      for (const cb of this.handlers[type] ?? []) cb({ data: JSON.stringify(data) })
    }
    close(): void {}
  }

  async function mountWithSnapshot(snap: unknown) {
    const g = globalThis as unknown as Record<string, unknown>
    const realES = g['EventSource']
    g['EventSource'] = FreshES
    FreshES.instances = []
    api.openPublicDisplaySession.mockResolvedValueOnce({ display_token: 'tok-x', snapshot: snap })
    const w = mount(DisplayView)
    await flushPromises()
    await w.find('[data-testid="display-pin-input"]').setValue('1234')
    await w.find('form').trigger('submit.prevent')
    await flushPromises()
    return { w, realES }
  }

  it('sorotan basi berlabel Hasil terakhir, bukan Hasil Dikonfirmasi', async () => {
    const { w, realES } = await mountWithSnapshot(snapshot)
    try {
      const spot = w.find('[data-testid="display-spotlight"]')
      expect(spot.exists()).toBe(true)
      expect(spot.text()).toContain('Hasil terakhir')
      expect(spot.text()).not.toContain('Hasil Dikonfirmasi')
    } finally {
      ;(globalThis as Record<string, unknown>)['EventSource'] = realES
      w.unmount()
    }
  })

  it('toleransi memakai grace_period_minutes dari server', async () => {
    const g = globalThis as unknown as Record<string, unknown>
    const realES = g['EventSource']
    g['EventSource'] = FreshES
    FreshES.instances = []
    try {
      api.openPublicDisplaySession.mockResolvedValueOnce({ display_token: 'tok-g', snapshot })
      const w = mount(DisplayView)
      await flushPromises()
      await w.find('[data-testid="display-pin-input"]').setValue('1234')
      await w.find('form').trigger('submit.prevent')
      await flushPromises()
      FreshES.instances[0].emit('snapshot', {
        laboratory_id: 'lab-1',
        laboratory_name: 'Lab Kimia 1',
        session_id: 'ses-1',
        subject: 'Uji Larutan',
        status: 'active',
        opened_at: null,
        present_count: 1,
        late_count: 1,
        waiting_count: 1,
        total_roster: 3,
        grace_period_minutes: 20,
        spotlight: {
          full_name: 'Raka Pratama',
          status: 'late',
          recorded_at: new Date().toISOString(),
          recognition_event_id: 'ev-1',
          source: 'face_recognition',
        },
        server_time: new Date().toISOString(),
      })
      await flushPromises()
      const spot = w.find('[data-testid="display-spotlight"]')
      expect(spot.text()).toContain('Hasil Dikonfirmasi')
      expect(spot.text()).toContain('20 menit')
      expect(spot.text()).not.toContain('15 menit')
      w.unmount()
    } finally {
      g['EventSource'] = realES
    }
  })

  it('sorotan manual berlabel petugas, bukan hasil pindaian', async () => {
    const g = globalThis as unknown as Record<string, unknown>
    const realES = g['EventSource']
    g['EventSource'] = FreshES
    FreshES.instances = []
    try {
      api.openPublicDisplaySession.mockResolvedValueOnce({ display_token: 'tok-m', snapshot })
      const w = mount(DisplayView)
      await flushPromises()
      await w.find('[data-testid="display-pin-input"]').setValue('1234')
      await w.find('form').trigger('submit.prevent')
      await flushPromises()
      FreshES.instances[0].emit('snapshot', {
        laboratory_id: 'lab-1',
        laboratory_name: 'Lab Kimia 1',
        session_id: 'ses-1',
        subject: 'Uji Larutan',
        status: 'active',
        opened_at: null,
        present_count: 1,
        late_count: 0,
        waiting_count: 2,
        total_roster: 3,
        grace_period_minutes: 15,
        spotlight: {
          full_name: 'Budi Santoso',
          status: 'present',
          recorded_at: new Date().toISOString(),
          recognition_event_id: null,
          source: 'manual',
        },
        server_time: new Date().toISOString(),
      })
      await flushPromises()
      const spot = w.find('[data-testid="display-spotlight"]')
      expect(spot.text()).toContain('Dicatat manual oleh petugas')
      w.unmount()
    } finally {
      g['EventSource'] = realES
    }
  })
})
