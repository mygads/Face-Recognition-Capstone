<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { UiBadge, UiButton, UiEmptyState, UiInput } from '../components/ui'
import { shortDisplayName } from '../utils/displayName'
import { timeFormatterFor } from '../utils/dateFormat'
import {
  ApiError,
  getKioskDisplay,
  getPublicDisplay,
  listPublicKioskScreens,
  listPublicLaboratories,
  openKioskDisplaySession,
  openPublicDisplaySession,
  type PublicDisplay,
  type PublicKioskOption,
  type PublicLaboratory,
} from '../api/client'

const labs = ref<PublicLaboratory[]>([])
const kiosks = ref<PublicKioskOption[]>([])
const labId = ref('')
const deviceId = ref('')
const pin = ref('')
const display = ref<PublicDisplay | null>(null)
const displayToken = ref('')
const error = ref<string | null>(null)
const isLoadingLabs = ref(false)
const isLoadingDisplay = ref(false)
const isFullscreen = ref(false)
let timer: ReturnType<typeof setInterval> | undefined

const STATUS_GUIDE = [
  { key: 'waiting', label: 'Menunggu', hint: 'Silakan berdiri di dalam bingkai' },
  {
    key: 'adjust',
    label: 'Perlu penyesuaian',
    hint: 'Hadapkan wajah / maju sedikit / satu orang dulu',
  },
  { key: 'processing', label: 'Memproses', hint: 'Sedang memeriksa…' },
  { key: 'present', label: 'Hadir ✓', hint: 'Presensi tercatat' },
  { key: 'late', label: 'Terlambat', hint: 'Badge TERLAMBAT + menit keterlambatan' },
  { key: 'duplicate', label: 'Sudah tercatat', hint: 'Anda sudah tercatat' },
  { key: 'retry', label: 'Coba ulang', hint: 'Wajah belum dapat dipastikan' },
  { key: 'unready', label: 'Belum dibuka', hint: 'Presensi belum dibuka. Tunggu petugas' },
] as const

function formatError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Layar tidak dapat dimuat.'
}

async function loadLabs(): Promise<void> {
  isLoadingLabs.value = true
  try {
    labs.value = await listPublicLaboratories()
    if (!labId.value && labs.value.length) labId.value = labs.value[0].id
  } catch (err) {
    error.value = formatError(err)
  } finally {
    isLoadingLabs.value = false
  }
}

async function loadKiosks(): Promise<void> {
  kiosks.value = []
  deviceId.value = ''
  if (!labId.value) return
  try {
    kiosks.value = await listPublicKioskScreens(labId.value)
    if (kiosks.value.length === 1) deviceId.value = kiosks.value[0].device_id
  } catch {
    kiosks.value = []
  }
}

async function loadDisplay(silent = false): Promise<void> {
  if (!displayToken.value) return
  if (!silent) isLoadingDisplay.value = true
  try {
    display.value = deviceId.value
      ? await getKioskDisplay(displayToken.value)
      : await getPublicDisplay(displayToken.value)
    error.value = null
  } catch (err) {
    if (!silent) error.value = formatError(err)
    if (err instanceof ApiError && err.status === 401) stopPolling()
  } finally {
    if (!silent) isLoadingDisplay.value = false
  }
}

function startPolling(): void {
  stopPolling()
  timer = setInterval(() => void loadDisplay(true), 5000)
}

function stopPolling(): void {
  if (timer) clearInterval(timer)
  timer = undefined
}

async function submit(): Promise<void> {
  if (!labId.value || !pin.value) return
  isLoadingDisplay.value = true
  error.value = null
  try {
    const opened = deviceId.value
      ? await openKioskDisplaySession(deviceId.value, pin.value)
      : await openPublicDisplaySession(labId.value, pin.value)
    displayToken.value = opened.display_token
    display.value = opened.snapshot
    pin.value = ''
    startPolling()
  } catch (err) {
    error.value = formatError(err)
  } finally {
    isLoadingDisplay.value = false
  }
}

function toggleFullscreen(): void {
  const el = document.querySelector('.display-view')
  if (!document.fullscreenElement && el instanceof HTMLElement) {
    void el
      .requestFullscreen()
      .then(() => {
        isFullscreen.value = true
      })
      .catch(() => undefined)
  } else if (document.fullscreenElement) {
    void document
      .exitFullscreen()
      .then(() => {
        isFullscreen.value = false
      })
      .catch(() => undefined)
  }
}

const now = ref(new Date())
let clockTimer: ReturnType<typeof setInterval> | undefined
const clockWib = computed(() => {
  try {
    return new Intl.DateTimeFormat('id-ID', {
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Asia/Jakarta',
    })
      .format(now.value)
      .replace(':', '.')
  } catch {
    return ''
  }
})
const dateLine = computed(() => {
  try {
    return new Intl.DateTimeFormat('id-ID', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      timeZone: 'Asia/Jakarta',
    }).format(now.value)
  } catch {
    return ''
  }
})
const terminalId = computed(() => {
  if (deviceId.value) {
    const k = kiosks.value.find((x) => x.device_id === deviceId.value)
    const base = (k?.display_name ?? deviceId.value)
      .toUpperCase()
      .replace(/[^A-Z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .replace(/^KIOSK-/, '')
      .slice(0, 24)
    return `KIOSK-${base || 'LAB-01'}`
  }
  const lab = labs.value.find((l) => l.id === labId.value)
  const code = (lab?.code ?? 'LAB').toUpperCase().replace(/[^A-Z0-9]+/g, '-')
  return `KIOSK-${code || 'LAB'}-01`
})
const waitingCount = computed(
  () =>
    (display.value?.students ?? []).filter((s) => s.status !== 'present' && s.status !== 'late')
      .length,
)

const boardTitle = computed(() => display.value?.laboratory_name ?? 'Layar presensi')

const spotlight = computed(() => {
  const rows = (display.value?.students ?? []).filter(
    (s) => (s.status === 'present' || s.status === 'late') && s.recorded_at,
  )
  if (!rows.length) return null
  const sorted = [...rows].sort((a, b) =>
    String(b.recorded_at).localeCompare(String(a.recorded_at)),
  )
  return sorted[0]
})

function formatRecordedTime(value: string | null | undefined): string {
  if (!value) return '-'
  try {
    return timeFormatterFor('Asia/Jakarta').format(new Date(value))
  } catch {
    return '-'
  }
}

function resetSession(): void {
  stopPolling()
  displayToken.value = ''
  display.value = null
}

watch(labId, () => {
  resetSession()
  void loadKiosks()
})
watch(deviceId, () => resetSession())

onMounted(() => {
  void loadLabs()
  clockTimer = setInterval(() => {
    now.value = new Date()
  }, 1000)
})
onBeforeUnmount(() => {
  stopPolling()
  if (clockTimer) clearInterval(clockTimer)
})
</script>

<template>
  <section class="display-view kiosk" aria-label="Layar presensi publik">
    <header class="kiosk__top">
      <div class="kiosk__brand">
        <img
          class="kiosk__logo"
          src="/logo-sekolah.png"
          alt="Logo SMA Cimahi"
          width="56"
          height="56"
        />
        <span class="kiosk__brand-text">
          <strong>Presensi Praktikum</strong>
          <small>Layar Kiosk Siswa · SMA Taruna Nusantara Kampus Cimahi</small>
        </span>
      </div>
      <p class="kiosk__session-pill" data-testid="display-session-pill">
        <span
          class="kiosk__dot"
          :class="{ 'kiosk__dot--live': !!display, 'kiosk__dot--idle': !display }"
          aria-hidden="true"
        />
        <span v-if="!display">Menunggu Aktivasi Petugas</span>
        <span v-else>{{
          display.subject
            ? `${display.subject} · ${display.laboratory_name}`
            : display.laboratory_name
        }}</span>
      </p>
      <div class="kiosk__clock">
        <strong>{{ clockWib }} <small>WIB</small></strong>
        <small>{{ dateLine }}</small>
      </div>
    </header>

    <main v-if="!display" class="kiosk__activate-wrap">
      <div class="kiosk__activate-info">
        <p class="kiosk__eyebrow">Kiosk mandiri · tanpa login staf</p>
        <h1>Aktivasi Layar Presensi Kiosk</h1>
        <p class="kiosk__desc">
          Pilih alokasi ruangan laboratorium dan pasangkan kamera sebelum siswa melakukan presensi.
        </p>
        <ol class="kiosk__steps">
          <li>Pilih laboratorium penempatan layar ini.</li>
          <li>Pilih kamera yang diizinkan untuk lab tersebut.</li>
          <li>Masukkan PIN petugas 6 digit, lalu mulai layar.</li>
        </ol>
        <p class="kiosk__note">
          Layar ini berjalan mandiri tanpa login staf. PIN hanya dimasukkan saat aktivasi awal atau
          pergantian perangkat. Hubungi Administrator bila PIN belum diterbitkan.
        </p>
      </div>
      <div class="kiosk__activate-card" data-testid="display-activate-card">
        <h2>Aktivasi petugas</h2>
        <form @submit.prevent="submit">
          <fieldset class="kiosk__field">
            <legend>Laboratorium Penempatan <span aria-hidden="true">*</span></legend>
            <div class="kiosk__radios" data-testid="display-lab-select">
              <label
                v-for="lab in labs"
                :key="lab.id"
                class="kiosk__radio"
                :class="{ 'kiosk__radio--active': labId === lab.id }"
              >
                <input v-model="labId" type="radio" :value="lab.id" name="kiosk-lab" required />
                <span
                  ><strong>{{ lab.code }}</strong
                  ><small>{{ lab.name }}</small></span
                >
              </label>
            </div>
            <p v-if="isLoadingLabs" class="kiosk__muted">Memuat laboratorium…</p>
          </fieldset>
          <fieldset class="kiosk__field">
            <legend>Kamera yang Diizinkan <span aria-hidden="true">*</span></legend>
            <div class="kiosk__radios">
              <label class="kiosk__radio" :class="{ 'kiosk__radio--active': deviceId === '' }">
                <input v-model="deviceId" type="radio" value="" name="kiosk-cam" />
                <span><strong>Otomatis</strong><small>Sesi lab · kamera default</small></span>
              </label>
              <label
                v-for="k in kiosks"
                :key="k.device_id"
                class="kiosk__radio"
                :class="{ 'kiosk__radio--active': deviceId === k.device_id }"
              >
                <input v-model="deviceId" type="radio" :value="k.device_id" name="kiosk-cam" />
                <span
                  ><strong>{{ k.display_name }}</strong
                  ><small>{{ k.camera_label ?? 'Pintu Masuk 01' }}</small></span
                >
              </label>
            </div>
            <p v-if="deviceId" class="kiosk__muted" role="note">
              Kamera kiosk dipilih otomatis - gunakan PIN kiosk layar ini, bukan PIN lab.
            </p>
          </fieldset>
          <label class="kiosk__field kiosk__pin">
            <span>PIN Petugas (6 Digit) <span aria-hidden="true">*</span></span>
            <small class="kiosk__muted">Otorisasi Laboran/Admin</small>
            <UiInput
              v-model="pin"
              type="password"
              inputmode="numeric"
              minlength="4"
              maxlength="32"
              placeholder="••••••"
              autocomplete="one-time-code"
              data-testid="display-pin-input"
              required
            />
          </label>
          <p v-if="error" class="kiosk__error" role="alert">{{ error }}</p>
          <UiButton variant="primary" type="submit" :disabled="isLoadingDisplay" class="kiosk__cta">
            {{ isLoadingDisplay ? 'Memuat…' : 'Mulai Layar Presensi' }}
          </UiButton>
        </form>
        <footer class="kiosk__terminal">
          <span
            >Terminal ID: <strong>{{ terminalId }}</strong></span
          >
          <span>Core API Handshake Terhubung</span>
          <span>Keamanan Kiosk: Token Tanpa Akses Roster / Read-Only Biometrik</span>
        </footer>
      </div>
    </main>

    <main v-else class="kiosk__board" data-testid="display-board">
      <div class="kiosk__stage">
        <div class="kiosk__camera" aria-label="Bingkai kamera">
          <p class="kiosk__camera-badge">
            <span class="kiosk__dot kiosk__dot--live" aria-hidden="true" /> Kamera Siap
          </p>
          <div class="kiosk__frame" aria-hidden="true">
            <span class="kiosk__frame-corner kiosk__frame-corner--tl" />
            <span class="kiosk__frame-corner kiosk__frame-corner--tr" />
            <span class="kiosk__frame-corner kiosk__frame-corner--bl" />
            <span class="kiosk__frame-corner kiosk__frame-corner--br" />
            <span class="kiosk__silhouette">Berdiri di dalam bingkai</span>
          </div>
          <p class="kiosk__camera-meta">
            {{ boardTitle }} · Hadir {{ display.present_count }} · Terlambat
            {{ display.late_count }} / {{ display.total_roster }} · Menunggu {{ waitingCount }}
          </p>
          <div class="kiosk__board-actions">
            <UiButton variant="secondary" type="button" @click="toggleFullscreen">
              {{ isFullscreen ? 'Keluar fullscreen' : 'Fullscreen' }}
            </UiButton>
            <UiButton variant="text" type="button" @click="resetSession">Ganti layar</UiButton>
          </div>
        </div>
        <div class="kiosk__result">
          <div v-if="spotlight" class="kiosk__result-card" data-testid="display-spotlight">
            <p class="kiosk__eyebrow">
              Hasil Dikonfirmasi · {{ formatRecordedTime(spotlight.recorded_at) }} WIB
            </p>
            <p class="kiosk__date">{{ dateLine }}</p>
            <p class="kiosk__avatar" aria-hidden="true">
              {{
                shortDisplayName(spotlight.full_name)
                  .split(' ')
                  .map((w) => w[0])
                  .join('')
                  .slice(0, 2)
                  .toUpperCase()
              }}
            </p>
            <p class="kiosk__name">{{ shortDisplayName(spotlight.full_name) }}</p>
            <UiBadge :tone="spotlight.status === 'late' ? 'late' : 'present'">
              {{ spotlight.status === 'late' ? 'TERLAMBAT' : 'HADIR' }}
            </UiBadge>
            <dl v-if="spotlight.status === 'late'" class="kiosk__facts">
              <div>
                <dt>Waktu Kedatangan</dt>
                <dd>{{ formatRecordedTime(spotlight.recorded_at) }} WIB</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>Terlambat</dd>
              </div>
            </dl>
            <p v-if="spotlight.status === 'late'" class="kiosk__muted">
              Presensi tercatat dengan catatan keterlambatan melewati batas toleransi 15 menit.
            </p>
            <p v-else class="kiosk__muted">Kehadiran Anda tercatat pada roster praktikum.</p>
            <p class="kiosk__countdown">Layar kembali ke daftar menunggu otomatis.</p>
          </div>
          <div v-else class="kiosk__result-card kiosk__result-card--waiting">
            <p class="kiosk__eyebrow">Menunggu hasil pindaian</p>
            <h2 v-if="display.subject">{{ display.subject }}</h2>
            <UiEmptyState v-else title="Presensi belum dibuka. Tunggu petugas membuka sesi." />
            <p v-if="display.subject" class="kiosk__muted">
              {{ display.status }} · Hadir {{ display.present_count }} · Terlambat
              {{ display.late_count }} / {{ display.total_roster }}
            </p>
            <p class="kiosk__muted">Silakan berdiri di dalam bingkai kamera.</p>
          </div>
          <details class="kiosk__roster" open>
            <summary>Daftar tunggu · {{ waitingCount }} belum masuk</summary>
            <ul v-if="display.students.length" class="kiosk__chips">
              <li
                v-for="s in display.students"
                :key="s.student_number"
                class="kiosk__chip"
                :class="{
                  'kiosk__chip--present': s.status === 'present',
                  'kiosk__chip--late': s.status === 'late',
                }"
                data-testid="display-student"
                :title="
                  s.status === 'present' || s.status === 'late'
                    ? `Tercatat ${formatRecordedTime(s.recorded_at)}`
                    : undefined
                "
              >
                <strong>{{ shortDisplayName(s.full_name) }}</strong>
                <UiBadge
                  :tone="
                    s.status === 'present'
                      ? 'present'
                      : s.status === 'late'
                        ? 'late'
                        : s.status === 'excused'
                          ? 'excused'
                          : 'neutral'
                  "
                  >{{
                    s.status === 'present'
                      ? 'SUDAH MASUK'
                      : s.status === 'late'
                        ? 'TERLAMBAT'
                        : s.status === 'excused'
                          ? 'IZIN'
                          : 'BELUM MASUK'
                  }}</UiBadge
                >
              </li>
            </ul>
          </details>
          <details class="kiosk__guide">
            <summary>Panduan status layar</summary>
            <ul>
              <li v-for="g in STATUS_GUIDE" :key="g.key">
                <strong>{{ g.label }}</strong> - {{ g.hint }}
              </li>
            </ul>
          </details>
        </div>
      </div>
    </main>
  </section>
</template>

<style scoped>
.display-view.kiosk {
  min-height: 100vh;
  background: #0b2036;
  color: #f1f5f9;
  font-family: var(--st-font);
  padding: 0 0 32px;
}
.kiosk__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
  flex-wrap: wrap;
  min-height: 88px;
  padding: 12px 32px;
  background: var(--st-primary-container);
  border-bottom: 1px solid #1e3a52;
}
.kiosk__brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.kiosk__logo {
  width: 56px;
  height: 56px;
  border-radius: 0;
  box-shadow: none;
  background: none;
  object-fit: contain;
  flex-shrink: 0;
}
.kiosk__brand-text {
  display: grid;
  line-height: 1.25;
}
.kiosk__brand-text strong {
  font-size: 1rem;
}
.kiosk__brand-text small {
  color: #a9bccd;
  font-size: 0.72rem;
}
.kiosk__session-pill {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  padding: 8px 16px;
  border-radius: 12px;
  background: #0b2036;
  border: 1px solid #1e3a52;
  font-size: 0.82rem;
  font-weight: 600;
  max-width: 100%;
}
.kiosk__dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: #a9bccd;
  flex-shrink: 0;
}
.kiosk__dot--live {
  background: #22c55e;
}
.kiosk__dot--idle {
  background: #fbbf24;
}
.kiosk__clock {
  text-align: right;
  padding-left: 16px;
  border-left: 1px solid #1e3a52;
}
.kiosk__clock strong {
  display: block;
  font-family: monospace;
  font-size: 1.4rem;
}
.kiosk__clock strong small {
  font-size: 0.7rem;
  color: #a9bccd;
}
.kiosk__clock > small {
  color: #a9bccd;
  font-size: 0.75rem;
}
.kiosk__activate-wrap {
  display: grid;
  grid-template-columns: minmax(280px, 5fr) minmax(320px, 7fr);
  gap: 24px;
  align-items: start;
  max-width: 1060px;
  margin: 32px auto 0;
  padding: 0 24px;
}
.kiosk__activate-info h1 {
  margin: 8px 0;
  font-size: 1.6rem;
  letter-spacing: -0.01em;
}
.kiosk__eyebrow {
  margin: 0;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--st-gold);
}
.kiosk__desc {
  color: #c6d4d3;
}
.kiosk__steps {
  display: grid;
  gap: 8px;
  padding-left: 20px;
  color: #c6d4d3;
}
.kiosk__note {
  color: #a9bccd;
  font-size: 0.8rem;
}
.kiosk__activate-card {
  background: var(--st-primary-container);
  border: 1px solid #1e3a52;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 8px 24px rgb(0 0 0 / 0.35);
}
.kiosk__activate-card h2 {
  margin: 0 0 12px;
  font-size: 1.1rem;
}
.kiosk__activate-card form {
  display: grid;
  gap: 16px;
}
.kiosk__field {
  border: 0;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 8px;
}
.kiosk__field legend,
.kiosk__pin > span {
  font-size: 0.82rem;
  font-weight: 700;
}
.kiosk__radios {
  display: grid;
  gap: 8px;
}
.kiosk__radio {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid #1e3a52;
  border-radius: 12px;
  padding: 10px 12px;
  cursor: pointer;
  min-height: 44px;
  background: #0b2036;
}
.kiosk__radio input {
  accent-color: var(--st-gold);
  width: 18px;
  height: 18px;
}
.kiosk__radio span {
  display: grid;
}
.kiosk__radio strong {
  font-size: 0.88rem;
}
.kiosk__radio small {
  color: #a9bccd;
  font-size: 0.75rem;
}
.kiosk__radio--active {
  border-color: var(--st-gold);
}
.kiosk__pin {
  display: grid;
  gap: 6px;
}
.kiosk__muted {
  color: #a9bccd;
  font-size: 0.78rem;
  margin: 0;
}
.kiosk__error {
  margin: 0;
  border-radius: 8px;
  padding: 10px 14px;
  background: #3f1d20;
  color: #ffb4ab;
  font-size: 0.85rem;
}
.kiosk__cta {
  width: 100%;
  min-height: 48px;
  font-size: 0.95rem;
}
.kiosk__terminal {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #1e3a52;
  color: #a9bccd;
  font-size: 0.72rem;
}
.kiosk__terminal strong {
  color: #f1f5f9;
}
.kiosk__board {
  max-width: 1180px;
  margin: 24px auto 0;
  padding: 0 24px;
}
.kiosk__stage {
  display: grid;
  grid-template-columns: minmax(0, 7fr) minmax(300px, 5fr);
  gap: 20px;
  align-items: start;
}
.kiosk__camera {
  background: #152223;
  border: 1px solid #1e3a52;
  border-radius: 24px;
  padding: 20px;
  display: grid;
  gap: 12px;
  justify-items: center;
}
.kiosk__camera-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 6px 12px;
  border-radius: 8px;
  background: rgb(16 27 28 / 0.8);
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--st-gold);
  align-self: start;
}
.kiosk__frame {
  position: relative;
  width: min(360px, 100%);
  height: 440px;
  border-radius: 180px;
  border: 2px solid var(--st-gold);
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(circle at 50% 35%, #14324a 0%, #0b2036 70%);
}
.kiosk__frame-corner {
  position: absolute;
  width: 32px;
  height: 32px;
  border: 4px solid #fbbf24;
}
.kiosk__frame-corner--tl {
  top: -2px;
  left: -2px;
  border-right: 0;
  border-bottom: 0;
  border-top-left-radius: 12px;
}
.kiosk__frame-corner--tr {
  top: -2px;
  right: -2px;
  border-left: 0;
  border-bottom: 0;
  border-top-right-radius: 12px;
}
.kiosk__frame-corner--bl {
  bottom: -2px;
  left: -2px;
  border-right: 0;
  border-top: 0;
  border-bottom-left-radius: 12px;
}
.kiosk__frame-corner--br {
  bottom: -2px;
  right: -2px;
  border-left: 0;
  border-top: 0;
  border-bottom-right-radius: 12px;
}
.kiosk__silhouette {
  color: #a9bccd;
  font-size: 0.85rem;
}
.kiosk__camera-meta {
  margin: 0;
  color: #a9bccd;
  font-size: 0.8rem;
  text-align: center;
}
.kiosk__board-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  justify-content: center;
}
.kiosk__result {
  display: grid;
  gap: 12px;
  align-content: start;
}
.kiosk__result-card {
  background: var(--st-primary-container);
  border: 1px solid #1e3a52;
  border-radius: 16px;
  padding: 24px;
  text-align: center;
  display: grid;
  gap: 8px;
  justify-items: center;
}
.kiosk__result-card .kiosk__eyebrow {
  color: var(--st-gold);
}
.kiosk__date {
  margin: 0;
  color: #a9bccd;
  font-size: 0.8rem;
}
.kiosk__avatar {
  width: 80px;
  height: 80px;
  border-radius: 999px;
  margin: 8px 0 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  font-weight: 800;
  background: #0f2a28;
  border: 2px solid var(--st-gold);
  color: #f1f5f9;
}
.kiosk__name {
  margin: 0;
  font-size: 1.4rem;
  font-weight: 800;
}
.kiosk__facts {
  display: grid;
  gap: 8px;
  margin: 8px 0 0;
  width: 100%;
}
.kiosk__facts > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: #0b2036;
  border: 1px solid #1e3a52;
  border-radius: 8px;
  padding: 8px 12px;
}
.kiosk__facts dt {
  color: #a9bccd;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.kiosk__facts dd {
  margin: 0;
  font-weight: 700;
}
.kiosk__countdown {
  color: #fbbf24;
  font-size: 0.8rem;
  margin: 4px 0 0;
}
.kiosk__result-card--waiting h2 {
  margin: 4px 0;
}
.kiosk__roster,
.kiosk__guide {
  background: var(--st-primary-container);
  border: 1px solid #1e3a52;
  border-radius: 12px;
  padding: 12px 16px;
  color: #c6d4d3;
}
.kiosk__roster summary,
.kiosk__guide summary {
  cursor: pointer;
  font-weight: 700;
  font-size: 0.85rem;
}
.kiosk__chips {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
}
.kiosk__chip {
  background: #0b2036;
  border: 1px solid #1e3a52;
  border-radius: 12px;
  padding: 10px;
  display: grid;
  gap: 6px;
  justify-items: center;
  text-align: center;
  font-size: 0.82rem;
}
.kiosk__chip--present {
  border-color: var(--st-gold);
}
.kiosk__chip--late {
  border-color: #fbbf24;
}
.kiosk__guide ul {
  margin: 8px 0 0;
  padding-left: 18px;
  display: grid;
  gap: 4px;
  font-size: 0.8rem;
}
.kiosk :deep(.st-empty__title) {
  color: #f1f5f9;
}
.kiosk :deep(.st-empty__desc) {
  color: #c6d4d3;
}
.kiosk :deep(.st-empty__icon) {
  color: var(--st-gold);
}
.kiosk .st-btn--text {
  color: #8bd4c6;
}
.kiosk .st-btn--secondary {
  background: #e6f7f6;
  border-color: #e6f7f6;
  color: #0f2a28;
}
@media (max-width: 960px) {
  .kiosk__activate-wrap,
  .kiosk__stage {
    grid-template-columns: minmax(0, 1fr);
  }
  .kiosk__top {
    padding: 12px 16px;
  }
  .kiosk__clock {
    border-left: 0;
    padding-left: 0;
    text-align: left;
  }
  .kiosk__board,
  .kiosk__activate-wrap {
    padding: 0 16px;
  }
}
</style>
