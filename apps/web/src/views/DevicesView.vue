<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import PageHeader from '../components/PageHeader.vue'
import {
  ApiError,
  createDevice,
  listDevices,
  listLaboratories,
  provisionDeviceCredential,
  rotateDeviceCredential,
  updateDevice,
  type Device,
  type DeviceCredential,
  type Laboratory,
} from '../api/client'

type DeviceForm = {
  name: string
  laboratory_id: string
  deployment_profile: 'AI_EDGE' | 'STB_GATEWAY'
  is_active: boolean
}

const auth = useAuthStore()
const canManage = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
const devices = ref<Device[]>([])
const laboratories = ref<Laboratory[]>([])
const total = ref(0)
const page = ref(0)
const pageSize = 10
const searchText = ref('')
const search = ref('')
const statusFilter = ref<'all' | 'online' | 'offline' | 'warning'>('all')
const isLoading = ref(false)
const errorMessage = ref<string | null>(null)
const formError = ref<string | null>(null)
const isFormOpen = ref(false)
const isSaving = ref(false)
const editingDeviceId = ref<string | null>(null)
const form = ref<DeviceForm>(emptyForm())
const credentialDevice = ref<Device | null>(null)
const issuedCredential = ref<DeviceCredential | null>(null)
const credentialError = ref<string | null>(null)
const credentialCopyMessage = ref<string | null>(null)
const rotationReason = ref('')
const coreApiUrl = ref('')
const centralAiUrl = ref('')
const modelVersion = ref('opencv-zoo-sface-2021dec')
const bundleMessage = ref<string | null>(null)
const isCredentialLoading = ref(false)
const isRotationOpen = ref(false)
let refreshTimer: ReturnType<typeof setInterval> | undefined

function emptyForm(): DeviceForm {
  return {
    name: '',
    laboratory_id: '',
    deployment_profile: 'AI_EDGE',
    is_active: true,
  }
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details?.map((item) => `${item.field}: ${item.message}`)
    return details?.length ? details.join(' · ') : error.message
  }
  return 'Permintaan tidak dapat diproses. Coba lagi.'
}

function formatLastSeen(value: string | null): string {
  if (!value) return 'Belum pernah'
  return new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(value),
  )
}

function formatCredentialExpiry(value: string): string {
  return new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(value),
  )
}

function defaultCoreApiUrl(): string {
  if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
    return 'http://127.0.0.1:8000'
  }
  return window.location.origin
}

function healthLabel(status: Device['health_status']): string {
  return { online: 'Online', offline: 'Offline', warning: 'Warning' }[status]
}

function profileLabel(profile: Device['deployment_profile']): string {
  return profile === 'AI_EDGE' ? 'AI di Edge PC' : 'STB Gateway · AI central'
}

function cameraLabel(status: Device['camera_status']): string {
  return {
    unknown: 'Belum dilaporkan',
    online: 'Aktif',
    offline: 'Tidak aktif',
    error: 'Gangguan',
  }[status]
}

async function loadDevices(): Promise<void> {
  isLoading.value = true
  errorMessage.value = null
  try {
    const result = await listDevices({
      limit: pageSize,
      offset: page.value * pageSize,
      search: search.value || undefined,
      health_status: statusFilter.value === 'all' ? undefined : statusFilter.value,
    })
    devices.value = result.items
    total.value = result.pagination.total
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

async function loadLaboratories(): Promise<void> {
  try {
    const result = await listLaboratories({ limit: 100, offset: 0, is_active: true })
    laboratories.value = result.items
    if (!form.value.laboratory_id && result.items.length > 0) {
      form.value.laboratory_id = result.items[0].id
    }
  } catch (error) {
    errorMessage.value = formatError(error)
  }
}

function submitSearch(): void {
  search.value = searchText.value.trim()
  page.value = 0
  void loadDevices()
}

function openCreate(): void {
  editingDeviceId.value = null
  form.value = emptyForm()
  formError.value = null
  isFormOpen.value = true
  void loadLaboratories()
}

function openEdit(device: Device): void {
  editingDeviceId.value = device.device_id
  form.value = {
    name: device.name,
    laboratory_id: device.laboratory_id,
    deployment_profile: device.deployment_profile,
    is_active: device.is_active,
  }
  formError.value = null
  isFormOpen.value = true
  void loadLaboratories()
}

async function submitForm(): Promise<void> {
  formError.value = null
  isSaving.value = true
  try {
    if (editingDeviceId.value) {
      await updateDevice(editingDeviceId.value, {
        name: form.value.name.trim(),
        laboratory_id: form.value.laboratory_id,
        is_active: form.value.is_active,
      })
    } else {
      await createDevice({
        name: form.value.name.trim(),
        laboratory_id: form.value.laboratory_id,
        deployment_profile: form.value.deployment_profile,
        device_type: form.value.deployment_profile === 'AI_EDGE' ? 'edge_pc' : 'camera_gateway',
      })
    }
    isFormOpen.value = false
    await loadDevices()
  } catch (error) {
    formError.value = formatError(error)
  } finally {
    isSaving.value = false
  }
}

function openCredential(device: Device): void {
  credentialDevice.value = device
  issuedCredential.value = null
  credentialError.value = null
  credentialCopyMessage.value = null
  rotationReason.value = ''
  coreApiUrl.value = defaultCoreApiUrl()
  centralAiUrl.value = ''
  modelVersion.value = 'opencv-zoo-sface-2021dec'
  bundleMessage.value = null
  isRotationOpen.value = false
}

function closeCredential(): void {
  if (isCredentialLoading.value) return
  issuedCredential.value = null
  credentialDevice.value = null
  credentialError.value = null
  credentialCopyMessage.value = null
  bundleMessage.value = null
  rotationReason.value = ''
  isRotationOpen.value = false
}

function handleCredentialBackdropClick(): void {
  if (!issuedCredential.value) closeCredential()
}

function handleCredentialKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && !issuedCredential.value) closeCredential()
}

async function issueCredential(action: 'provision' | 'rotate'): Promise<void> {
  const device = credentialDevice.value
  if (!device || isCredentialLoading.value) return
  credentialError.value = null
  credentialCopyMessage.value = null
  if (action === 'rotate' && !rotationReason.value.trim()) {
    credentialError.value = 'Isi alasan rotasi agar perubahan tercatat di audit.'
    isRotationOpen.value = true
    return
  }

  isCredentialLoading.value = true
  try {
    issuedCredential.value =
      action === 'provision'
        ? await provisionDeviceCredential(device.device_id)
        : await rotateDeviceCredential(device.device_id, rotationReason.value.trim())
    isRotationOpen.value = false
  } catch (error) {
    if (error instanceof ApiError && error.code === 'device_credential_exists') {
      credentialError.value =
        'Kredensial pernah dibuat dan tidak dapat ditampilkan ulang. Jika file token hilang, rotasi kredensial untuk membuat token baru.'
      isRotationOpen.value = true
    } else {
      credentialError.value = formatError(error)
    }
  } finally {
    isCredentialLoading.value = false
  }
}

async function copyCredential(): Promise<void> {
  if (!issuedCredential.value) return
  try {
    await navigator.clipboard.writeText(issuedCredential.value.token)
    credentialCopyMessage.value = 'Token disalin. Simpan segera ke file token perangkat.'
  } catch {
    credentialCopyMessage.value = 'Salin token dari kotak secara manual sebelum menutup panel.'
  }
}

async function copyBootstrapCredential(): Promise<void> {
  const device = credentialDevice.value
  const credential = issuedCredential.value
  if (!device || !credential) return
  try {
    await navigator.clipboard.writeText(`${device.device_id}:${credential.token}`)
    credentialCopyMessage.value =
      'ID dan token disalin untuk installer. Tempelkan hanya pada prompt tersembunyi installer; isi clipboard ini tetap rahasia.'
  } catch {
    credentialCopyMessage.value =
      'Clipboard tidak tersedia. Gunakan ID perangkat dan token secara terpisah pada prompt installer.'
  }
}

function downloadCredential(): void {
  if (!issuedCredential.value) return
  const file = new Blob([`${issuedCredential.value.token}\n`], {
    type: 'text/plain;charset=utf-8',
  })
  const url = URL.createObjectURL(file)
  const link = document.createElement('a')
  link.href = url
  link.download = 'device.token'
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
  credentialCopyMessage.value =
    'File device.token diunduh. Pindahkan ke folder token agent pada komputer perangkat.'
}

function normalizeServerOrigin(value: string, label: string): string {
  let parsed: URL
  try {
    parsed = new URL(value.trim())
  } catch {
    throw new Error(`${label} harus berupa URL lengkap, misalnya https://server.sekolah.id.`)
  }
  if (
    !['http:', 'https:'].includes(parsed.protocol) ||
    !parsed.hostname ||
    parsed.username ||
    parsed.password ||
    !['', '/'].includes(parsed.pathname) ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error(`${label} harus berupa alamat origin HTTP(S) tanpa path atau secret.`)
  }
  return parsed.origin
}

function downloadSetupBundle(): void {
  const device = credentialDevice.value
  const credential = issuedCredential.value
  if (!device || !credential) return
  bundleMessage.value = null
  try {
    const bundle = {
      schema_version: 1,
      device_id: device.device_id,
      device_name: device.name,
      laboratory_id: device.laboratory_id,
      deployment_profile: device.deployment_profile,
      core_api_url: normalizeServerOrigin(coreApiUrl.value, 'URL Core API'),
      central_ai_url:
        device.deployment_profile === 'STB_GATEWAY'
          ? normalizeServerOrigin(centralAiUrl.value, 'URL AI Central')
          : null,
      model_version: device.deployment_profile === 'AI_EDGE' ? modelVersion.value.trim() : null,
      token: credential.token,
    }
    if (device.deployment_profile === 'AI_EDGE' && !bundle.model_version) {
      throw new Error('Versi model diperlukan untuk profil AI_EDGE.')
    }
    const file = new Blob([`${JSON.stringify(bundle, null, 2)}\n`], {
      type: 'application/json;charset=utf-8',
    })
    const url = URL.createObjectURL(file)
    const link = document.createElement('a')
    link.href = url
    link.download = 'presensi-device-setup.json'
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
    bundleMessage.value =
      'Paket setup diunduh. Paket ini memuat secret; pindahkan secara aman dan hapus setelah agent berhasil dipasang.'
  } catch (error) {
    bundleMessage.value = error instanceof Error ? error.message : 'Paket setup tidak dapat dibuat.'
  }
}

function onRotationToggle(event: Event): void {
  isRotationOpen.value = (event.currentTarget as HTMLDetailsElement).open
}

function goToPage(nextPage: number): void {
  if (nextPage < 0 || nextPage >= totalPages.value || nextPage === page.value) return
  page.value = nextPage
}

watch([page, statusFilter], () => void loadDevices())
onMounted(() => {
  void loadDevices()
  void loadLaboratories()
  refreshTimer = setInterval(() => void loadDevices(), 15_000)
})
onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  issuedCredential.value = null
})
</script>

<template>
  <section class="devices-view" aria-label="Registry perangkat">
    <PageHeader
      eyebrow="Operasional"
      title="Registry perangkat"
      description="Pantau koneksi kamera dan versi agent. Status diperbarui otomatis setiap 15 detik."
    >
      <template #actions>
        <button v-if="canManage" class="button button--primary" @click="openCreate">
          Daftarkan perangkat
        </button>
      </template>
    </PageHeader>

    <p v-if="errorMessage" class="master-data__alert" role="alert">{{ errorMessage }}</p>

    <div class="devices-view__toolbar">
      <form class="master-data__search" role="search" @submit.prevent="submitSearch">
        <label class="visually-hidden" for="device-search">Cari perangkat atau laboratorium</label>
        <input
          id="device-search"
          v-model="searchText"
          type="search"
          placeholder="Cari perangkat atau laboratorium…"
        />
        <button class="button button--secondary" type="submit">Cari</button>
      </form>
      <label class="enrollment-view__class-picker">
        Status
        <select v-model="statusFilter" aria-label="Filter status perangkat">
          <option value="all">Semua status</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
          <option value="warning">Warning</option>
        </select>
      </label>
    </div>

    <section v-if="isFormOpen" class="master-data__panel devices-view__form-panel">
      <div class="master-data__panel-heading">
        <h2>{{ editingDeviceId ? 'Ubah perangkat' : 'Daftarkan perangkat' }}</h2>
        <button class="button button--text" type="button" @click="isFormOpen = false">Tutup</button>
      </div>
      <form class="master-data__form" @submit.prevent="submitForm">
        <label>
          Nama perangkat
          <input v-model="form.name" required maxlength="120" autocomplete="off" />
        </label>
        <label>
          Laboratorium
          <select v-model="form.laboratory_id" required>
            <option value="" disabled>Pilih laboratorium</option>
            <option v-for="lab in laboratories" :key="lab.id" :value="lab.id">
              {{ lab.code }} · {{ lab.name }}
            </option>
          </select>
        </label>
        <label v-if="!editingDeviceId">
          Profil deployment
          <select v-model="form.deployment_profile">
            <option value="AI_EDGE">AI di Edge PC</option>
            <option value="STB_GATEWAY">STB Gateway · AI central</option>
          </select>
        </label>
        <p v-else class="devices-view__profile-note">
          {{ profileLabel(form.deployment_profile) }}
        </p>
        <label v-if="editingDeviceId" class="master-data__checkbox">
          <input v-model="form.is_active" type="checkbox" /> Perangkat aktif
        </label>
        <p v-if="formError" class="master-data__alert master-data__alert--form" role="alert">
          {{ formError }}
        </p>
        <div class="master-data__form-actions">
          <button class="button button--secondary" type="button" @click="isFormOpen = false">
            Batal
          </button>
          <button class="button button--primary" type="submit" :disabled="isSaving">
            {{ isSaving ? 'Menyimpan…' : editingDeviceId ? 'Simpan perubahan' : 'Daftarkan' }}
          </button>
        </div>
      </form>
    </section>

    <div class="master-data__table-wrap">
      <table class="master-data__table devices-view__table">
        <thead>
          <tr>
            <th scope="col">Perangkat</th>
            <th scope="col">Laboratorium</th>
            <th scope="col">Deployment</th>
            <th scope="col">Versi app / model</th>
            <th scope="col">Kamera</th>
            <th scope="col">Heartbeat</th>
            <th scope="col">Latency p50 / p95</th>
            <th scope="col">Status</th>
            <th v-if="canManage" scope="col">Aksi</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="isLoading">
            <td :colspan="canManage ? 9 : 8" class="master-data__empty">Memuat perangkat…</td>
          </tr>
          <tr v-else-if="devices.length === 0">
            <td :colspan="canManage ? 9 : 8" class="master-data__empty">
              Belum ada perangkat yang cocok.
            </td>
          </tr>
          <tr v-for="device in devices" v-else :key="device.device_id">
            <td data-label="Perangkat">
              <strong>{{ device.name }}</strong>
              <small>{{ device.device_id }}</small>
            </td>
            <td data-label="Laboratorium">
              <strong>{{ device.laboratory_code }}</strong>
              <small>{{ device.laboratory_name }}</small>
            </td>
            <td data-label="Deployment">{{ profileLabel(device.deployment_profile) }}</td>
            <td data-label="Versi app / model">
              <strong>{{ device.app_version ?? 'Belum dilaporkan' }}</strong>
              <small>Model: {{ device.model_version ?? '—' }}</small>
            </td>
            <td data-label="Kamera">{{ cameraLabel(device.camera_status) }}</td>
            <td data-label="Heartbeat">
              {{ formatLastSeen(device.last_seen_at) }}
              <small>Timeout {{ device.heartbeat_timeout_seconds }} detik</small>
            </td>
            <td data-label="Latency p50 / p95">
              {{ device.latency_summary?.p50_ms ?? '—' }} /
              {{ device.latency_summary?.p95_ms ?? '—' }} ms
            </td>
            <td data-label="Status">
              <span
                class="status-badge"
                :class="`status-badge--${device.health_status}`"
                :aria-label="`Status ${healthLabel(device.health_status)}`"
              >
                {{ healthLabel(device.health_status) }}
              </span>
            </td>
            <td v-if="canManage" data-label="Aksi">
              <div class="devices-view__actions">
                <button class="button button--text" @click="openEdit(device)">Ubah</button>
                <button
                  class="button button--secondary"
                  type="button"
                  :disabled="!device.is_active"
                  :title="
                    device.is_active
                      ? 'Buat atau rotasi token agent'
                      : 'Aktifkan perangkat lebih dulu'
                  "
                  @click="openCredential(device)"
                >
                  Kredensial
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="master-data__pagination">
      <span>{{ total }} perangkat</span>
      <div>
        <button class="button button--secondary" :disabled="page === 0" @click="goToPage(page - 1)">
          Sebelumnya
        </button>
        <span>Halaman {{ page + 1 }} dari {{ totalPages }}</span>
        <button
          class="button button--secondary"
          :disabled="page + 1 >= totalPages"
          @click="goToPage(page + 1)"
        >
          Berikutnya
        </button>
      </div>
    </footer>

    <div
      v-if="credentialDevice"
      class="devices-view__modal-backdrop"
      role="presentation"
      @click.self="handleCredentialBackdropClick"
      @keydown="handleCredentialKeydown"
    >
      <section
        class="devices-view__credential-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="device-credential-title"
        tabindex="-1"
        data-testid="device-credential-dialog"
      >
        <header class="devices-view__credential-heading">
          <div>
            <p class="master-data__eyebrow">Akses agent perangkat</p>
            <h2 id="device-credential-title">{{ credentialDevice.name }}</h2>
            <small>{{ credentialDevice.device_id }}</small>
          </div>
          <button
            v-if="!issuedCredential"
            class="button button--text"
            type="button"
            aria-label="Tutup kredensial"
            :disabled="isCredentialLoading"
            @click="closeCredential"
          >
            Tutup
          </button>
        </header>

        <template v-if="issuedCredential">
          <p class="devices-view__credential-warning" role="alert">
            Token ini hanya ditampilkan sekarang. Salin atau unduh sebelum menutup panel. Sistem
            hanya menyimpan verifier token dan tidak dapat menampilkan token lama kembali.
          </p>
          <label class="devices-view__token-label" for="device-token">Token perangkat</label>
          <div class="devices-view__token-row">
            <input
              id="device-token"
              :value="issuedCredential.token"
              type="text"
              readonly
              autocomplete="off"
              spellcheck="false"
              aria-label="Token perangkat, hanya ditampilkan setelah dibuat"
              data-testid="device-token-value"
            />
            <button class="button button--secondary" type="button" @click="copyCredential">
              Salin
            </button>
            <button class="button button--secondary" type="button" @click="downloadCredential">
              Unduh device.token
            </button>
          </div>
          <p v-if="credentialCopyMessage" class="devices-view__credential-status" role="status">
            {{ credentialCopyMessage }}
          </p>
          <section class="devices-view__bundle-form" aria-label="Paket instalasi perangkat">
            <h3>Siapkan instalasi perangkat</h3>
            <button class="button button--secondary" type="button" @click="copyBootstrapCredential">
              Salin kredensial untuk installer satu-perintah
            </button>
            <p>
              Installer meminta URL Core API dan kredensial ID:token ini secara tersembunyi,
              mendeteksi profile dari registry, lalu mengunduh source dan memasang agent. Jangan
              tempelkan kredensial ke perintah terminal.
            </p>
            <label for="device-core-api-url">URL Core API yang bisa dijangkau kamera</label>
            <input
              id="device-core-api-url"
              v-model="coreApiUrl"
              type="url"
              required
              autocomplete="url"
              placeholder="https://presensi.sekolah.id"
            />
            <p>
              Gunakan alamat server/LAN yang dapat diakses perangkat kamera. Untuk laptop yang
              menjalankan server lokal, gunakan http://127.0.0.1:8000. Jangan isi localhost jika
              kamera ada di komputer lain.
            </p>
            <p>
              Stack development hanya membuka API pada komputer lokal. Kamera di komputer lain
              membutuhkan server LAN/production dan HTTPS melalui reverse proxy; jangan membuka port
              API development langsung ke internet.
            </p>
            <label
              v-if="credentialDevice.deployment_profile === 'STB_GATEWAY'"
              for="device-central-ai-url"
            >
              URL AI Central
            </label>
            <input
              v-if="credentialDevice.deployment_profile === 'STB_GATEWAY'"
              id="device-central-ai-url"
              v-model="centralAiUrl"
              type="url"
              required
              autocomplete="url"
              placeholder="https://ai.sekolah.id"
            />
            <template v-if="credentialDevice.deployment_profile === 'AI_EDGE'">
              <label for="device-model-version">Versi model</label>
              <input
                id="device-model-version"
                v-model="modelVersion"
                required
                maxlength="128"
                autocomplete="off"
              />
              <p>
                Harus sama dengan versi YuNet/SFace yang digunakan saat enrollment template siswa.
              </p>
            </template>
            <p v-if="bundleMessage" class="devices-view__credential-status" role="status">
              {{ bundleMessage }}
            </p>
            <button class="button button--primary" type="button" @click="downloadSetupBundle">
              Unduh paket setup perangkat
            </button>
          </section>
          <p class="devices-view__credential-instructions">
            Installer menyimpan token ke folder lokal terlindungi:
            <code>%LOCALAPPDATA%\Presensi\device.token</code> di Windows atau
            <code>~/.local/share/presensi-edge-agent/device.token</code> di Linux. Jangan masukkan
            token ke chat, screenshot, atau perintah shell.
          </p>
          <div class="devices-view__credential-meta">
            <span>Berlaku sampai {{ formatCredentialExpiry(issuedCredential.expires_at) }}</span>
            <span v-if="issuedCredential.previous_token_valid_until">
              Token lama masih berlaku sementara sampai
              {{ formatCredentialExpiry(issuedCredential.previous_token_valid_until) }}.
            </span>
          </div>
          <div
            class="devices-view__credential-commands"
            aria-label="Variabel konfigurasi perangkat"
          >
            <p>Untuk bootstrap tanpa clone manual, jalankan command sesuai OS pada host kamera:</p>
            <pre
              v-if="credentialDevice.deployment_profile === 'AI_EDGE'"
            ><code>Windows: irm https://raw.githubusercontent.com/mygads/Face-Recognition-Capstone/main/scripts/bootstrap-camera-device.ps1 | iex
Linux:   curl -fsSL https://raw.githubusercontent.com/mygads/Face-Recognition-Capstone/main/scripts/bootstrap-camera-device.sh | bash</code></pre>
            <pre
              v-else
            ><code>Armbian: curl -fsSL https://raw.githubusercontent.com/mygads/Face-Recognition-Capstone/main/scripts/bootstrap-camera-device.sh | bash</code></pre>
            <p>
              Profile dideteksi dari Core API. Untuk STB, installer juga meminta URL AI Central.
              Instalasi produksi tetap memerlukan langkah systemd pada runbook.
            </p>
          </div>
          <div class="master-data__form-actions">
            <button class="button button--primary" type="button" @click="closeCredential">
              Saya sudah menyimpan token
            </button>
          </div>
        </template>

        <template v-else>
          <p class="devices-view__credential-instructions">
            Buat token untuk pemasangan pertama agent. Token tidak bisa dibuka ulang setelah panel
            ditutup. Jika token lama hilang, gunakan rotasi untuk menerbitkan token pengganti.
          </p>
          <p v-if="credentialError" class="master-data__alert" role="alert">
            {{ credentialError }}
          </p>
          <div class="devices-view__credential-actions">
            <button
              class="button button--primary"
              type="button"
              :disabled="isCredentialLoading"
              @click="issueCredential('provision')"
            >
              {{ isCredentialLoading ? 'Membuat token…' : 'Buat token pertama' }}
            </button>
          </div>
          <details :open="isRotationOpen" class="devices-view__rotation" @toggle="onRotationToggle">
            <summary>Token pernah dibuat, hilang, atau perlu diganti?</summary>
            <form class="devices-view__rotation-form" @submit.prevent="issueCredential('rotate')">
              <label for="credential-rotation-reason">Alasan rotasi</label>
              <input
                id="credential-rotation-reason"
                v-model="rotationReason"
                required
                maxlength="200"
                placeholder="Contoh: token hilang saat pemasangan ulang"
              />
              <p>
                Token lama dan baru memiliki masa tumpang tindih singkat agar agent dapat berpindah
                dengan aman. Pasang file token baru segera.
              </p>
              <button
                class="button button--secondary"
                type="submit"
                :disabled="isCredentialLoading || !rotationReason.trim()"
              >
                {{ isCredentialLoading ? 'Merotasi…' : 'Rotasi dan tampilkan token baru' }}
              </button>
            </form>
          </details>
          <div class="master-data__form-actions">
            <button
              class="button button--text"
              type="button"
              :disabled="isCredentialLoading"
              @click="closeCredential"
            >
              Batal
            </button>
          </div>
        </template>
      </section>
    </div>
  </section>
</template>
