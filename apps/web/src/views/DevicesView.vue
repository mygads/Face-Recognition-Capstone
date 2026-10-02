<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import PageHeader from '../components/PageHeader.vue'
import {
  buildDeviceSetupCommand,
  type DeviceConnectionMode,
  type DeviceSetupPlatform,
} from '../devices/deviceSetup'
import {
  ApiError,
  createDevice,
  deleteDevice,
  getAiReadiness,
  listDevices,
  listLaboratories,
  provisionDeviceCredential,
  rotateDeviceCredential,
  setDeviceCameraEnabled,
  updateDevice,
  type Device,
  type DeviceCredential,
  type Laboratory,
  type AiReadiness,
} from '../api/client'

type DeviceForm = {
  name: string
  laboratory_id: string
  deployment_profile: 'AI_EDGE' | 'STB_GATEWAY'
  is_active: boolean
}

type DeviceSetupDefaults = {
  coreApiUrl: string
  centralAiUrl: string
  connectionMode: DeviceConnectionMode
  modelVersion: string
}

const DEVICE_SETUP_DEFAULTS_KEY = 'presensi.device-setup-defaults.v1'
const FALLBACK_MODEL_VERSION = 'opencv-zoo-sface-2021dec'

const auth = useAuthStore()
const canManage = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
const devices = ref<Device[]>([])
const laboratories = ref<Laboratory[]>([])
const aiReadiness = ref<AiReadiness | null>(null)
const isProfileLoading = ref(true)
const hasResolvedInitialProfile = ref(false)
const edgeDeviceCount = ref(0)
const total = ref(0)
const page = ref(0)
const pageSize = 10
const searchText = ref('')
const search = ref('')
const statusFilter = ref<'all' | 'online' | 'offline' | 'warning'>('all')
const includeInactive = ref(false)
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
const installPlatform = ref<DeviceSetupPlatform>('windows')
const connectionMode = ref<DeviceConnectionMode>('same-host')
const setupDefaults = ref<DeviceSetupDefaults>(loadSetupDefaults())
const setupDefaultsMessage = ref<string | null>(null)
const installCommandMessage = ref<string | null>(null)
const bundleMessage = ref<string | null>(null)
const isCredentialLoading = ref(false)
const isRotationOpen = ref(false)
const devicePendingDeletion = ref<Device | null>(null)
const isDeletingDevice = ref(false)
const deleteError = ref<string | null>(null)
const cameraControlTarget = ref<Device | null>(null)
const isCameraControlSaving = ref(false)
let refreshTimer: ReturnType<typeof setInterval> | undefined

const activeProfile = computed(() => aiReadiness.value?.deployment_profile ?? null)
const enrollmentModelVersion = computed(
  () => aiReadiness.value?.enrollment_model_version?.trim() || '',
)
const canRegisterDevice = computed(() => {
  if (!canManage.value || isProfileLoading.value || !activeProfile.value) return false
  return (
    activeProfile.value === 'AI_CENTRAL' ||
    (edgeDeviceCount.value === 0 && enrollmentModelVersion.value.length > 0)
  )
})
const deviceConnectionMode = computed<DeviceConnectionMode>(() => {
  if (credentialDevice.value?.deployment_profile === 'AI_EDGE') {
    return isLoopbackOrigin(coreApiUrl.value) ? 'same-host' : 'private-network'
  }
  return connectionMode.value
})

function emptyForm(profile: Device['deployment_profile'] = 'AI_EDGE'): DeviceForm {
  return {
    name: '',
    laboratory_id: '',
    deployment_profile: profile,
    is_active: true,
  }
}

function loadSetupDefaults(): DeviceSetupDefaults {
  const localBrowser = ['127.0.0.1', 'localhost'].includes(window.location.hostname)
  const empty: DeviceSetupDefaults = {
    coreApiUrl: defaultCoreApiUrl(),
    centralAiUrl: localBrowser ? 'http://127.0.0.1:8001' : '',
    connectionMode: localBrowser ? 'same-host' : 'private-network',
    modelVersion: FALLBACK_MODEL_VERSION,
  }
  try {
    const raw = window.localStorage.getItem(DEVICE_SETUP_DEFAULTS_KEY)
    if (!raw) return empty
    const stored = JSON.parse(raw) as Partial<DeviceSetupDefaults>
    const mode = stored.connectionMode
    return {
      coreApiUrl:
        typeof stored.coreApiUrl === 'string' && stored.coreApiUrl.trim()
          ? stored.coreApiUrl
          : empty.coreApiUrl,
      centralAiUrl:
        typeof stored.centralAiUrl === 'string' ? stored.centralAiUrl : empty.centralAiUrl,
      connectionMode:
        mode === 'same-host' || mode === 'private-network' ? mode : empty.connectionMode,
      modelVersion: empty.modelVersion,
    }
  } catch {
    return empty
  }
}

function saveSetupDefaults(): void {
  setupDefaultsMessage.value = null
  try {
    const coreOrigin = normalizeServerOrigin(setupDefaults.value.coreApiUrl, 'URL Core API')
    const mode =
      activeProfile.value === 'AI_EDGE'
        ? isLoopbackOrigin(coreOrigin)
          ? 'same-host'
          : 'private-network'
        : setupDefaults.value.connectionMode
    validateConnectionOrigin(mode, coreOrigin, 'URL Core API')
    const centralOrigin =
      activeProfile.value === 'AI_CENTRAL' && setupDefaults.value.centralAiUrl.trim()
        ? normalizeServerOrigin(setupDefaults.value.centralAiUrl, 'URL AI Central')
        : ''
    if (centralOrigin) {
      validateConnectionOrigin(mode, centralOrigin, 'URL AI Central')
    }
    const next: DeviceSetupDefaults = {
      ...setupDefaults.value,
      coreApiUrl: coreOrigin,
      centralAiUrl: centralOrigin,
      connectionMode: mode,
      modelVersion: enrollmentModelVersion.value,
    }
    window.localStorage.setItem(DEVICE_SETUP_DEFAULTS_KEY, JSON.stringify(next))
    setupDefaults.value = next
    setupDefaultsMessage.value =
      'Default disimpan di browser ini. URL akan terisi untuk setup device berikutnya; token tidak disimpan.'
  } catch (error) {
    setupDefaultsMessage.value =
      error instanceof Error ? error.message : 'Default setup tidak dapat disimpan.'
  }
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const setupCommandState = computed(() => {
  const device = credentialDevice.value
  if (!device || !issuedCredential.value) return { command: '', error: null }
  try {
    const coreOrigin = normalizeServerOrigin(coreApiUrl.value, 'URL Core API')
    validateConnectionOrigin(deviceConnectionMode.value, coreOrigin, 'URL Core API')
    const centralOrigin =
      device.deployment_profile === 'STB_GATEWAY'
        ? normalizeServerOrigin(centralAiUrl.value, 'URL AI Central')
        : undefined
    if (centralOrigin) {
      validateConnectionOrigin(deviceConnectionMode.value, centralOrigin, 'URL AI Central')
    }
    return {
      command: buildDeviceSetupCommand({
        profile: device.deployment_profile,
        platform: installPlatform.value,
        connectionMode: deviceConnectionMode.value,
        coreApiUrl: coreOrigin,
        centralAiUrl: centralOrigin,
        deviceId: device.device_id,
        modelVersion: modelVersion.value.trim(),
        useWorkingCopy: deviceConnectionMode.value === 'same-host',
      }),
      error: null,
    }
  } catch (error) {
    return {
      command: '',
      error: error instanceof Error ? error.message : 'Perintah setup belum siap.',
    }
  }
})

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

function defaultCentralAiUrl(): string {
  if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
    return 'http://127.0.0.1:8001'
  }
  return ''
}

function healthLabel(status: Device['health_status']): string {
  return { online: 'Online', offline: 'Offline', warning: 'Warning' }[status]
}

function profileLabel(profile: Device['deployment_profile']): string {
  return profile === 'AI_EDGE' ? 'AI di Edge PC' : 'STB Gateway · AI central'
}

function cameraLabel(device: Device): string {
  if (!device.camera_enabled) {
    return device.camera_status === 'disabled' ? 'Dijeda admin' : 'Menunggu agent dijeda'
  }
  if (device.camera_status === 'disabled') return 'Menunggu agent aktif'
  return {
    unknown: 'Belum dilaporkan',
    online: 'Aktif',
    offline: 'Tidak aktif',
    error: 'Gangguan',
    disabled: 'Dijeda admin',
  }[device.camera_status]
}

function requestCameraToggle(device: Device): void {
  cameraControlTarget.value = device
}

async function confirmCameraToggle(): Promise<void> {
  const target = cameraControlTarget.value
  if (!target) return
  isCameraControlSaving.value = true
  errorMessage.value = null
  try {
    const updated = await setDeviceCameraEnabled(target.device_id, !target.camera_enabled)
    devices.value = devices.value.map((item) =>
      item.device_id === updated.device_id ? updated : item,
    )
    cameraControlTarget.value = null
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isCameraControlSaving.value = false
  }
}

async function loadDevices(): Promise<void> {
  isLoading.value = true
  errorMessage.value = null
  try {
    const result = await listDevices({
      limit: pageSize,
      offset: page.value * pageSize,
      search: search.value || undefined,
      deployment_profile: activeProfile.value
        ? activeProfile.value === 'AI_CENTRAL'
          ? 'STB_GATEWAY'
          : 'AI_EDGE'
        : undefined,
      is_active: includeInactive.value ? undefined : true,
      health_status: statusFilter.value === 'all' ? undefined : statusFilter.value,
    })
    devices.value = result.items
    total.value = result.pagination.total
    if (activeProfile.value === 'AI_EDGE') {
      const edgeDevices = await listDevices({
        limit: 1,
        offset: 0,
        deployment_profile: 'AI_EDGE',
        is_active: true,
      })
      edgeDeviceCount.value = edgeDevices.pagination.total
    } else {
      edgeDeviceCount.value = 0
    }
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

async function loadAiReadiness(): Promise<void> {
  if (!canManage.value) {
    isProfileLoading.value = false
    hasResolvedInitialProfile.value = true
    return
  }
  isProfileLoading.value = !hasResolvedInitialProfile.value
  try {
    aiReadiness.value = await getAiReadiness()
    setupDefaults.value.modelVersion = enrollmentModelVersion.value
    if (activeProfile.value === 'AI_EDGE') {
      setupDefaults.value.centralAiUrl = ''
      setupDefaults.value.connectionMode = isLoopbackOrigin(setupDefaults.value.coreApiUrl)
        ? 'same-host'
        : 'private-network'
    } else if (!setupDefaults.value.centralAiUrl) {
      setupDefaults.value.centralAiUrl = defaultCentralAiUrl()
    }
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isProfileLoading.value = false
    hasResolvedInitialProfile.value = true
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
  if (!canRegisterDevice.value || !activeProfile.value) return
  editingDeviceId.value = null
  form.value = emptyForm(activeProfile.value === 'AI_CENTRAL' ? 'STB_GATEWAY' : 'AI_EDGE')
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
  if (!activeProfile.value) {
    formError.value = 'Profil server belum dapat dipastikan. Muat ulang halaman lalu coba lagi.'
    return
  }
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
        deployment_profile: activeProfile.value === 'AI_CENTRAL' ? 'STB_GATEWAY' : 'AI_EDGE',
        device_type: activeProfile.value === 'AI_CENTRAL' ? 'camera_gateway' : 'edge_pc',
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
  const browserIsLocal = ['127.0.0.1', 'localhost'].includes(window.location.hostname)
  const savedCore = setupDefaults.value.coreApiUrl
  const savedCentral = setupDefaults.value.centralAiUrl
  coreApiUrl.value = savedCore || defaultCoreApiUrl()
  centralAiUrl.value =
    device.deployment_profile === 'STB_GATEWAY'
      ? savedCentral || (browserIsLocal ? defaultCentralAiUrl() : '')
      : ''
  modelVersion.value = enrollmentModelVersion.value
  installPlatform.value = device.deployment_profile === 'STB_GATEWAY' ? 'armbian' : 'windows'
  connectionMode.value =
    device.deployment_profile === 'AI_EDGE'
      ? isLoopbackOrigin(coreApiUrl.value)
        ? 'same-host'
        : 'private-network'
      : setupDefaults.value.connectionMode
  installCommandMessage.value = null
  bundleMessage.value = null
  isRotationOpen.value = false
}

function closeCredential(): void {
  if (isCredentialLoading.value) return
  issuedCredential.value = null
  credentialDevice.value = null
  credentialError.value = null
  credentialCopyMessage.value = null
  installCommandMessage.value = null
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
  const isLoopback = ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname)
  if (parsed.protocol === 'http:' && !isLoopback) {
    throw new Error(
      `${label} wajib memakai HTTPS di jaringan; HTTP hanya diizinkan untuk localhost.`,
    )
  }
  return parsed.origin
}

function validateConnectionOrigin(mode: DeviceConnectionMode, origin: string, label: string): void {
  const parsed = new URL(origin)
  const isLoopback = ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname)
  if (mode === 'same-host' && !isLoopback) {
    throw new Error(`${label} harus localhost karena pilihan koneksi adalah satu komputer.`)
  }
  if (mode === 'private-network' && parsed.protocol !== 'https:') {
    throw new Error(`${label} pada LAN/VPN harus HTTPS dengan sertifikat yang dipercaya.`)
  }
}

function isLoopbackOrigin(value: string): boolean {
  try {
    return ['localhost', '127.0.0.1', '[::1]'].includes(new URL(value).hostname)
  } catch {
    return false
  }
}

function selectConnectionMode(mode: DeviceConnectionMode): void {
  connectionMode.value = mode
  installCommandMessage.value = null
  bundleMessage.value = null
  if (mode === 'same-host') {
    coreApiUrl.value = 'http://127.0.0.1:8000'
    if (credentialDevice.value?.deployment_profile === 'STB_GATEWAY') {
      centralAiUrl.value = 'http://127.0.0.1:8001'
    }
    return
  }
  if (isLoopbackOrigin(coreApiUrl.value)) {
    coreApiUrl.value = ''
  }
  if (isLoopbackOrigin(centralAiUrl.value)) {
    centralAiUrl.value = ''
  }
}

function onDefaultConnectionModeChange(event: Event): void {
  const mode = (event.currentTarget as HTMLSelectElement).value
  if (mode !== 'same-host' && mode !== 'private-network') return
  setupDefaults.value.connectionMode = mode
  if (mode === 'same-host') {
    setupDefaults.value.coreApiUrl = 'http://127.0.0.1:8000'
    if (activeProfile.value === 'AI_CENTRAL') {
      setupDefaults.value.centralAiUrl = 'http://127.0.0.1:8001'
    }
    return
  }
  if (isLoopbackOrigin(setupDefaults.value.coreApiUrl)) setupDefaults.value.coreApiUrl = ''
  if (isLoopbackOrigin(setupDefaults.value.centralAiUrl)) setupDefaults.value.centralAiUrl = ''
}

function onConnectionModeChange(event: Event): void {
  const mode = (event.currentTarget as HTMLSelectElement).value
  if (
    mode === 'same-host' ||
    mode === 'private-network' ||
    mode === 'public-domain' ||
    mode === 'cloudflare-tunnel'
  ) {
    selectConnectionMode(mode)
  }
}

function requestDeviceDeletion(device: Device): void {
  devicePendingDeletion.value = device
  deleteError.value = null
}

function closeDeviceDeletion(): void {
  if (isDeletingDevice.value) return
  devicePendingDeletion.value = null
  deleteError.value = null
}

async function confirmDeviceDeletion(): Promise<void> {
  const device = devicePendingDeletion.value
  if (!device || isDeletingDevice.value) return
  isDeletingDevice.value = true
  deleteError.value = null
  try {
    await deleteDevice(device.device_id)
    devicePendingDeletion.value = null
    if (device.deployment_profile === 'AI_EDGE') {
      edgeDeviceCount.value = Math.max(0, edgeDeviceCount.value - 1)
    }
    if (devices.value.length === 1 && page.value > 0) page.value -= 1
    await loadDevices()
  } catch (error) {
    deleteError.value = formatError(error)
  } finally {
    isDeletingDevice.value = false
  }
}

async function copyInstallCommand(): Promise<void> {
  installCommandMessage.value = null
  if (!bundleMessage.value?.startsWith('Paket setup diunduh')) {
    installCommandMessage.value = 'Unduh paket setup perangkat dulu sebelum menyalin command.'
    return
  }
  if (!setupCommandState.value.command) {
    installCommandMessage.value = setupCommandState.value.error ?? 'Perintah setup belum siap.'
    return
  }
  try {
    await navigator.clipboard.writeText(setupCommandState.value.command)
    installCommandMessage.value =
      'Perintah disalin. Pastikan file bundle berada di folder Downloads pada host yang menjalankan command.'
  } catch {
    installCommandMessage.value = 'Clipboard tidak tersedia. Salin perintah yang ditampilkan.'
  }
}

function downloadSetupBundle(): void {
  const device = credentialDevice.value
  const credential = issuedCredential.value
  if (!device || !credential) return
  bundleMessage.value = null
  try {
    if (
      deviceConnectionMode.value === 'public-domain' ||
      deviceConnectionMode.value === 'cloudflare-tunnel'
    ) {
      throw new Error(
        'Jalur publik belum diaktifkan karena perangkat mengambil gallery template biometrik dari Core API. Gunakan LAN/VPN privat.',
      )
    }
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
    validateConnectionOrigin(deviceConnectionMode.value, bundle.core_api_url, 'URL Core API')
    if (bundle.central_ai_url) {
      validateConnectionOrigin(deviceConnectionMode.value, bundle.central_ai_url, 'URL AI Central')
    }
    const file = new Blob([`${JSON.stringify(bundle, null, 2)}\n`], {
      type: 'application/json;charset=utf-8',
    })
    const url = URL.createObjectURL(file)
    const link = document.createElement('a')
    link.href = url
    link.download = `presensi-device-${device.device_id}-setup.json`
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
    bundleMessage.value =
      'Paket setup diunduh. Paket ini memuat secret; pindahkan secara aman ke host kamera dan hapus setelah agent berhasil dipasang.'
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

watch([page, statusFilter, includeInactive], () => void loadDevices())
watch([coreApiUrl, centralAiUrl, connectionMode], () => {
  bundleMessage.value = null
  installCommandMessage.value = null
})
onMounted(() => {
  void (async () => {
    await loadAiReadiness()
    await Promise.all([loadDevices(), loadLaboratories()])
  })()
  refreshTimer = setInterval(() => {
    void (async () => {
      await loadAiReadiness()
      await loadDevices()
    })()
  }, 15_000)
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
        <RouterLink
          v-if="activeProfile === 'AI_EDGE'"
          class="button button--secondary"
          to="/app/camera-preview"
        >
          Preview kamera
        </RouterLink>
        <button
          v-if="canRegisterDevice"
          class="button button--primary"
          type="button"
          @click="openCreate"
        >
          Daftarkan perangkat
        </button>
      </template>
    </PageHeader>

    <p v-if="errorMessage" class="master-data__alert" role="alert">{{ errorMessage }}</p>
    <p
      v-if="canManage && activeProfile === 'AI_EDGE' && edgeDeviceCount > 0"
      class="devices-view__profile-note"
      role="status"
    >
      Profil AI_EDGE pada setup ini memakai satu PC kamera. Nonaktifkan perangkat lama sebelum
      mendaftarkan penggantinya.
    </p>

    <section v-if="canManage" class="master-data__panel devices-view__form-panel">
      <div class="master-data__panel-heading">
        <div>
          <h2>Default koneksi untuk installer kamera</h2>
          <p>
            Isi sekali untuk mempercepat paket device berikutnya. Nilai ini disimpan hanya di
            browser admin ini, bukan di server; tidak ada token di sini. Ubah default per device
            bila lab memakai jaringan berbeda.
          </p>
        </div>
      </div>
      <div v-if="isProfileLoading" class="master-data__form">
        <p role="status">Memuat profil instalasi…</p>
      </div>
      <div v-else class="master-data__form">
        <label v-if="activeProfile === 'AI_CENTRAL'">
          Jaringan dari host kamera ke server
          <select
            :value="setupDefaults.connectionMode"
            aria-label="Default jaringan device"
            @change="onDefaultConnectionModeChange"
          >
            <option value="same-host">Komputer yang sama — localhost</option>
            <option value="private-network">LAN/VPN sekolah — HTTPS</option>
          </select>
        </label>
        <p v-else-if="activeProfile === 'AI_EDGE'" class="devices-view__profile-note">
          AI_EDGE memakai alamat Core API di bawah. Koneksi otomatis diperlakukan sebagai localhost
          untuk komputer yang sama atau HTTPS untuk host lain.
        </p>
        <label>
          Default URL Core API
          <input
            v-model="setupDefaults.coreApiUrl"
            type="url"
            autocomplete="url"
            placeholder="http://127.0.0.1:8000 atau https://presensi.sekolah.id"
          />
        </label>
        <label v-if="activeProfile === 'AI_CENTRAL'">
          Default URL AI Central (STB_GATEWAY)
          <input
            v-model="setupDefaults.centralAiUrl"
            type="url"
            autocomplete="url"
            placeholder="https://ai.sekolah.id"
          />
        </label>
        <label v-if="activeProfile === 'AI_EDGE'">
          Versi model enrollment (terkunci)
          <input
            id="device-default-model-version"
            :value="enrollmentModelVersion"
            readonly
            aria-readonly="true"
          />
        </label>
        <p v-if="activeProfile === 'AI_EDGE'" class="devices-view__profile-note">
          Hanya versi model yang dikonfigurasi pada server enrollment yang didukung. Model baru
          perlu dipasang dan diverifikasi sebelum dapat dipilih.
        </p>
        <p
          v-if="activeProfile === 'AI_EDGE' && !enrollmentModelVersion"
          class="master-data__alert"
          role="alert"
        >
          Versi model belum dilaporkan oleh Core API. Atur versi model saat provisioning server
          sebelum mendaftarkan kamera AI_EDGE.
        </p>
        <p v-if="setupDefaultsMessage" class="master-data__alert" role="status">
          {{ setupDefaultsMessage }}
        </p>
        <div class="master-data__form-actions">
          <button class="button button--primary" type="button" @click="saveSetupDefaults">
            Simpan default di browser ini
          </button>
        </div>
      </div>
    </section>

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
      <label v-if="canManage" class="master-data__checkbox">
        <input v-model="includeInactive" type="checkbox" /> Tampilkan perangkat nonaktif
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
        <p class="devices-view__profile-note">
          Profil instalasi: {{ profileLabel(form.deployment_profile) }}
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
            <td data-label="Kamera">{{ cameraLabel(device) }}</td>
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
                <button class="button button--text" type="button" @click="openEdit(device)">
                  Ubah
                </button>
                <button
                  class="button button--secondary"
                  type="button"
                  :disabled="!device.is_active"
                  :aria-label="device.camera_enabled ? 'Jeda kamera' : 'Aktifkan kamera'"
                  @click="requestCameraToggle(device)"
                >
                  {{ device.camera_enabled ? 'Jeda kamera' : 'Aktifkan kamera' }}
                </button>
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
                <button
                  class="button button--danger"
                  type="button"
                  :disabled="!device.is_active"
                  @click="requestDeviceDeletion(device)"
                >
                  Hapus
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-if="cameraControlTarget"
      class="devices-view__modal-backdrop"
      role="presentation"
      @click.self="cameraControlTarget = null"
    >
      <section
        class="devices-view__confirm-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="camera-control-title"
      >
        <p class="master-data__eyebrow">Kontrol kamera</p>
        <h2 id="camera-control-title">
          {{ cameraControlTarget.camera_enabled ? 'Jeda kamera?' : 'Aktifkan kamera?' }}
        </h2>
        <p>
          <strong>{{ cameraControlTarget.name }}</strong>
          <template v-if="cameraControlTarget.camera_enabled">
            akan berhenti mengambil frame dan mengirim presensi. Perangkat tetap terdaftar dan dapat
            diaktifkan kembali dari halaman ini.
          </template>
          <template v-else>
            akan mulai mengambil frame kembali saat agent menerima pengaturan ini.
          </template>
        </p>
        <div class="master-data__form-actions">
          <button
            class="button button--secondary"
            type="button"
            :disabled="isCameraControlSaving"
            @click="cameraControlTarget = null"
          >
            Batal
          </button>
          <button
            class="button"
            :class="cameraControlTarget.camera_enabled ? 'button--danger' : 'button--primary'"
            type="button"
            :disabled="isCameraControlSaving"
            @click="confirmCameraToggle"
          >
            {{
              isCameraControlSaving
                ? 'Menerapkan…'
                : cameraControlTarget.camera_enabled
                  ? 'Jeda kamera'
                  : 'Aktifkan kamera'
            }}
          </button>
        </div>
      </section>
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
            <p>
              Isi alamat server yang dapat dijangkau kamera untuk paket ini, lalu unduh paket setup.
              Bootstrap membaca URL, profile, UUID, dan token dari file; token tidak diketik atau
              ditaruh pada command.
            </p>
            <label for="device-install-platform">Sistem operasi perangkat</label>
            <select id="device-install-platform" v-model="installPlatform">
              <option
                value="windows"
                :disabled="credentialDevice.deployment_profile === 'STB_GATEWAY'"
              >
                Windows (AI_EDGE)
              </option>
              <option
                value="ubuntu"
                :disabled="credentialDevice.deployment_profile === 'STB_GATEWAY'"
              >
                Ubuntu Linux (AI_EDGE)
              </option>
              <option value="armbian" :disabled="credentialDevice.deployment_profile === 'AI_EDGE'">
                Armbian Linux (STB_GATEWAY)
              </option>
            </select>
            <label
              v-if="credentialDevice.deployment_profile === 'STB_GATEWAY'"
              for="device-connection-mode"
            >
              Jaringan dari STB ke server
              <select
                id="device-connection-mode"
                :value="connectionMode"
                @change="onConnectionModeChange"
              >
                <option value="same-host">Komputer yang sama — localhost</option>
                <option value="private-network">LAN/VPN sekolah — HTTPS privat</option>
                <option value="public-domain">Domain publik — belum diaktifkan</option>
                <option value="cloudflare-tunnel">Cloudflare Tunnel — belum diaktifkan</option>
              </select>
            </label>
            <p v-else class="devices-view__profile-note">
              AI_EDGE mendeteksi mode koneksi dari URL Core API: localhost untuk host yang sama atau
              HTTPS untuk host lain.
            </p>
            <p v-if="deviceConnectionMode === 'same-host'">
              Pilih ini hanya jika kamera, API, dan checkout project berada di komputer yang sama.
              Command akan memakai repo lokal dan tidak mengunduh repo ulang.
            </p>
            <p v-else-if="deviceConnectionMode === 'private-network'">
              Gunakan HTTPS internal yang hanya bisa dijangkau melalui LAN/VPN sekolah. STB baru
              mengunduh source bootstrap, tanpa perlu clone manual.
            </p>
            <p v-else class="devices-view__credential-warning" role="alert">
              Jalur publik belum diaktifkan. AI_EDGE mengambil gallery template wajah dari Core API;
              Cloudflare Access service identity belum didukung agent. Gunakan LAN/VPN privat.
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
              <label for="device-model-version">Versi model (terkunci)</label>
              <input
                id="device-model-version"
                :value="enrollmentModelVersion"
                readonly
                aria-readonly="true"
              />
              <p>
                Harus sama dengan versi YuNet/SFace yang digunakan saat enrollment template siswa.
              </p>
            </template>
            <p v-if="bundleMessage" class="devices-view__credential-status" role="status">
              {{ bundleMessage }}
            </p>
            <pre v-if="setupCommandState.command" data-testid="device-install-command"><code>{{
              setupCommandState.command
            }}</code></pre>
            <p v-if="setupCommandState.error" class="devices-view__credential-warning" role="alert">
              {{ setupCommandState.error }}
            </p>
            <p v-if="installCommandMessage" class="devices-view__credential-status" role="status">
              {{ installCommandMessage }}
            </p>
            <p>
              File bundle bernama
              <code>presensi-device-{{ credentialDevice.device_id }}-setup.json</code>. Jika kamera
              ada di host lain, pindahkan file itu lewat USB atau SCP ke folder Downloads pada host
              kamera. Jika browser menambahkan akhiran karena file lama sudah ada, pulihkan nama
              persis seperti di atas. File bundle adalah rahasia dan berlaku untuk satu device.
            </p>
            <button
              class="button button--secondary"
              type="button"
              :disabled="
                !setupCommandState.command || !bundleMessage?.startsWith('Paket setup diunduh')
              "
              @click="copyInstallCommand"
            >
              Salin perintah instalasi perangkat
            </button>
            <button
              class="button button--primary"
              type="button"
              :disabled="!setupCommandState.command"
              @click="downloadSetupBundle"
            >
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
          <p class="devices-view__credential-instructions">
            Command mengunduh source untuk host baru atau memakai checkout ini untuk kamera pada
            komputer yang sama. Ia membaca bundle lokal dan memvalidasi profile ke Core API;
            kredensial tidak muncul di riwayat terminal. Installer lalu menawarkan pilihan kamera,
            resolusi, dan FPS. Pemasangan service setelah reboot mengikuti runbook production.
          </p>
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

    <div
      v-if="devicePendingDeletion"
      class="devices-view__modal-backdrop"
      role="presentation"
      @click.self="closeDeviceDeletion"
    >
      <section
        class="devices-view__credential-modal devices-view__delete-modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="device-delete-title"
        aria-describedby="device-delete-description"
        data-testid="device-delete-dialog"
      >
        <header class="devices-view__credential-heading">
          <div>
            <p class="master-data__eyebrow">Konfirmasi penghapusan</p>
            <h2 id="device-delete-title">Hapus {{ devicePendingDeletion.name }}?</h2>
          </div>
        </header>
        <p id="device-delete-description" class="devices-view__credential-warning">
          Perangkat akan dinonaktifkan dan kredensialnya dicabut. Data presensi dan audit lama tetap
          tersimpan. Anda dapat melihatnya kembali dengan filter perangkat nonaktif.
        </p>
        <p v-if="deleteError" class="master-data__alert" role="alert">{{ deleteError }}</p>
        <div class="master-data__form-actions">
          <button
            class="button button--secondary"
            type="button"
            :disabled="isDeletingDevice"
            @click="closeDeviceDeletion"
          >
            Batal
          </button>
          <button
            class="button button--danger"
            type="button"
            :disabled="isDeletingDevice"
            @click="confirmDeviceDeletion"
          >
            {{ isDeletingDevice ? 'Menonaktifkan…' : 'Ya, hapus perangkat' }}
          </button>
        </div>
      </section>
    </div>
  </section>
</template>
