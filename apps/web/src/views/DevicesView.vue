<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import PageHeader from '../components/PageHeader.vue'
import {
  ApiError,
  createDevice,
  listDevices,
  listLaboratories,
  updateDevice,
  type Device,
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
              <button class="button button--text" @click="openEdit(device)">Ubah</button>
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
  </section>
</template>
