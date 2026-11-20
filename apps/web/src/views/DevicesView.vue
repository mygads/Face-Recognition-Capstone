<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { shouldPausePolling } from '../utils/visibility'
import { useAuthStore } from '../stores/auth'
import {
  UiButton,
  UiCard,
  UiInput,
  UiModal,
  UiPageHeader,
  UiSelect,
  UiStat,
} from '../components/ui'
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
  getDeviceRuntimeConfiguration,
  listDevices,
  listLaboratories,
  provisionDeviceCredential,
  rotateDeviceCredential,
  setDeviceCameraEnabled,
  updateDevice,
  type Device,
  type DeviceCredential,
  type DeviceRuntimeConfiguration,
  type Laboratory,
  type AiReadiness,
} from '../api/client'
import { triggerDownload } from '../utils/download'
import { formatDateTimeLocal } from '../utils/dateFormat'
import { createRefreshEpoch } from '../utils/refresh'
import { isFactoryDefaultReference } from '../utils/recognitionConfig'

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
const edgeSetupDevice = ref<Device | null>(null)
const edgeSetupRuntime = ref<DeviceRuntimeConfiguration | null>(null)
const isProfileLoading = ref(true)
const hasResolvedInitialProfile = ref(false)
const edgeDeviceCount = ref(0)
const total = ref(0)
const page = ref(0)
const pageSize = 10
const searchText = ref('')
const search = ref('')
const statusFilter = ref<'all' | 'online' | 'offline' | 'warning'>('all')
const onlineCount = computed(() => devices.value.filter((d) => d.health_status === 'online').length)
const warnCount = computed(() => devices.value.filter((d) => d.health_status !== 'online').length)
const includeInactive = ref(false)
const isLoading = ref(false)
const errorMessage = ref<string | null>(null)
const formError = ref<string | null>(null)
const isFormOpen = ref(false)
const isSaving = ref(false)
const editingDeviceId = ref<string | null>(null)
const form = ref<DeviceForm>(emptyForm())
const credentialDevice = ref<Device | null>(null)
const isEdgeSetupWizard = ref(false)
const isEdgeSetupMinimized = ref(false)
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
const setupDefaultsDraft = ref<DeviceSetupDefaults>({ ...setupDefaults.value })
const setupDefaultsMessage = ref<string | null>(null)
const isSetupDefaultsOpen = ref(false)
const installCommandMessage = ref<string | null>(null)
const bundleMessage = ref<string | null>(null)
const isCredentialLoading = ref(false)
const isRotationOpen = ref(false)
const devicePendingDeletion = ref<Device | null>(null)
const isDeletingDevice = ref(false)
const deleteError = ref<string | null>(null)
const isCameraControlSaving = ref(false)
let refreshTimer: ReturnType<typeof setInterval> | undefined
let wizardRefreshTimer: ReturnType<typeof setInterval> | undefined

const activeProfile = computed(() => aiReadiness.value?.deployment_profile ?? null)
const enrollmentModelVersion = computed(
  () => aiReadiness.value?.enrollment_model_version?.trim() || '',
)
const setupDefaultsConnectionLabel = computed(() => {
  if (activeProfile.value === 'AI_EDGE') {
    return isLoopbackOrigin(setupDefaults.value.coreApiUrl)
      ? 'Komputer ini · localhost'
      : 'LAN/VPN sekolah · HTTPS'
  }
  return setupDefaults.value.connectionMode === 'same-host'
    ? 'Komputer yang sama · localhost'
    : 'LAN/VPN sekolah · HTTPS'
})
const canRegisterDevice = computed(() => {
  if (!canManage.value || isProfileLoading.value || !activeProfile.value) return false
  return (
    activeProfile.value === 'AI_CENTRAL' ||
    (edgeDeviceCount.value === 0 && enrollmentModelVersion.value.length > 0)
  )
})
const edgeCameraReady = computed(() => {
  const device = edgeSetupDevice.value
  return Boolean(
    device?.is_active &&
    device.camera_enabled &&
    device.camera_status === 'online' &&
    device.last_seen_at,
  )
})
const edgePreviewRoute = computed(() => ({
  path: '/app/camera-preview',
  query: {
    lab: edgeSetupDevice.value?.laboratory_id,
    device: edgeSetupDevice.value?.device_id,
  },
}))
const edgeAiSetupStatus = computed(() => {
  const device = edgeSetupDevice.value
  if (!device) {
    return {
      tone: 'neutral',
      label: 'Menunggu perangkat',
      detail: 'Daftarkan satu PC kamera untuk memulai.',
    }
  }
  if (!aiReadiness.value?.enrollment_models_ready) {
    return {
      tone: 'warning',
      label: 'Model enrollment belum siap',
      detail: 'Model perlu tersedia di Core API untuk mengambil template wajah.',
    }
  }
  if (!device.model_version) {
    return {
      tone: 'neutral',
      label: 'Menunggu agent melaporkan model',
      detail: 'Setelah agent hidup, versi model akan diperiksa otomatis.',
    }
  }
  if (device.model_version !== enrollmentModelVersion.value) {
    return {
      tone: 'danger',
      label: 'Versi model tidak cocok',
      detail: 'Versi model agent harus sama dengan versi template enrollment.',
    }
  }
  if (edgeSetupRuntime.value?.apply_status === 'error') {
    return {
      tone: 'danger',
      label: 'Konfigurasi AI gagal diterapkan',
      detail: 'Buka AI & Kamera untuk melihat alasan dan memperbaiki konfigurasi.',
    }
  }
  if (edgeSetupRuntime.value?.apply_status !== 'applied') {
    return {
      tone: 'warning',
      label: 'Menunggu konfigurasi AI diterapkan',
      detail: 'Agent akan mengambil pengaturan saat tersambung.',
    }
  }
  const settings = edgeSetupRuntime.value.settings as Record<string, unknown>
  if (
    typeof settings.min_top1_similarity !== 'number' ||
    typeof settings.min_top1_top2_margin !== 'number'
  ) {
    return {
      tone: 'warning',
      label: 'Ambang pengenalan belum diatur',
      detail: 'Atur ambang sebelum mencoba pengenalan wajah.',
    }
  }
  if (isFactoryDefaultReference(settings.calibration_reference as string | null | undefined)) {
    return {
      tone: 'warning',
      label: 'Siap untuk smoke test terawasi',
      detail: 'Ambang default sementara wajib dikalibrasi sebelum operasional.',
    }
  }
  return {
    tone: 'success',
    label: 'AI siap menerima sesi',
    detail: 'Presensi baru dicatat jika template siswa tersedia dan sesi aktif.',
  }
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

function openSetupDefaultsEditor(): void {
  setupDefaultsDraft.value = { ...setupDefaults.value }
  setupDefaultsMessage.value = null
  isSetupDefaultsOpen.value = true
}

function closeSetupDefaultsEditor(): void {
  isSetupDefaultsOpen.value = false
  setupDefaultsMessage.value = null
}

function saveSetupDefaults(): boolean {
  setupDefaultsMessage.value = null
  try {
    const coreOrigin = normalizeServerOrigin(setupDefaultsDraft.value.coreApiUrl, 'URL Core API')
    const mode =
      activeProfile.value === 'AI_EDGE'
        ? isLoopbackOrigin(coreOrigin)
          ? 'same-host'
          : 'private-network'
        : setupDefaultsDraft.value.connectionMode
    validateConnectionOrigin(mode, coreOrigin, 'URL Core API')
    const centralOrigin =
      activeProfile.value === 'AI_CENTRAL' && setupDefaultsDraft.value.centralAiUrl.trim()
        ? normalizeServerOrigin(setupDefaultsDraft.value.centralAiUrl, 'URL AI Central')
        : ''
    if (centralOrigin) {
      validateConnectionOrigin(mode, centralOrigin, 'URL AI Central')
    }
    const next: DeviceSetupDefaults = {
      ...setupDefaultsDraft.value,
      coreApiUrl: coreOrigin,
      centralAiUrl: centralOrigin,
      connectionMode: mode,
      modelVersion: enrollmentModelVersion.value,
    }
    window.localStorage.setItem(DEVICE_SETUP_DEFAULTS_KEY, JSON.stringify(next))
    setupDefaults.value = next
    setupDefaultsDraft.value = { ...next }
    setupDefaultsMessage.value =
      'Default disimpan di browser ini. URL akan terisi untuk setup device berikutnya; token tidak disimpan.'
    return true
  } catch (error) {
    setupDefaultsMessage.value =
      error instanceof Error ? error.message : 'Default setup tidak dapat disimpan.'
    return false
  }
}

function saveSetupDefaultsAndClose(): void {
  if (saveSetupDefaults()) isSetupDefaultsOpen.value = false
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
  return formatDateTimeLocal(value)
}

function formatCredentialExpiry(value: string): string {
  return formatDateTimeLocal(value)
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

function defaultAiEdgePlatform(): Extract<DeviceSetupPlatform, 'windows' | 'ubuntu'> {
  const platform = window.navigator.platform.toLowerCase()
  const userAgent = window.navigator.userAgent.toLowerCase()
  return platform.startsWith('win') || userAgent.includes('windows') ? 'windows' : 'ubuntu'
}

function healthLabel(status: Device['health_status']): string {
  return { online: 'Online', offline: 'Offline', warning: 'Warning' }[status]
}

function warningStatusMessage(device: Device): string {
  if (!device.camera_enabled) return 'Kamera dijeda admin.'
  if (device.camera_status === 'disabled') {
    return 'Agent belum menerapkan perintah untuk mengaktifkan kamera.'
  }
  if (device.camera_status === 'error') return 'Agent melaporkan gangguan kamera.'
  if (device.camera_status === 'offline') return 'Kamera belum aktif pada agent.'
  if (device.camera_status === 'unknown') return 'Agent belum melaporkan status kamera.'
  if ((device.dead_letter_events ?? 0) > 0) {
    return `${device.dead_letter_events} event gagal dikirim dan perlu diperiksa.`
  }
  if ((device.pending_events ?? 0) > 0) {
    return `${device.pending_events} event masih menunggu dikirim.`
  }
  return 'Periksa antrean perangkat atau konfigurasi kamera.'
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

function cameraModeLabel(device: Device): string {
  const metrics = device.camera_metrics
  if (!metrics) return 'Belum ada pengukuran kamera'
  const mode =
    metrics.frame_width && metrics.frame_height
      ? `${metrics.frame_width} × ${metrics.frame_height}`
      : 'Resolusi belum dilaporkan'
  const fps =
    typeof metrics.capture_fps === 'number'
      ? `${metrics.capture_fps.toFixed(1)} FPS aktual`
      : 'FPS aktual belum terukur'
  return `${mode} · ${fps}`
}

function cameraQualityLabel(device: Device): string {
  const metrics = device.camera_metrics
  if (!metrics) return 'Belum diperiksa'
  const checkedAt = metrics.quality_checked_at
  if (checkedAt && Date.now() - new Date(checkedAt).getTime() > 120_000) {
    return 'Pengukuran lama · uji ulang di preview'
  }
  return (
    {
      not_checked: 'Belum diperiksa',
      ready: 'Wajah siap diperiksa',
      adjust: 'Perlu atur posisi atau cahaya',
      no_face: 'Wajah belum terdeteksi',
      multiple_faces: 'Lebih dari satu wajah',
      unavailable: 'Pemeriksaan tidak tersedia',
    }[metrics.quality_state] ?? 'Belum diperiksa'
  )
}

function cameraQualitySourceLabel(device: Device): string | null {
  if (device.camera_metrics?.quality_source === 'frame_filter') {
    return 'Pemeriksaan cahaya/ketajaman ringan gateway'
  }
  return null
}

function cameraLatencyLabel(device: Device): string {
  const summary = device.latency_summary
  if (!summary || (summary.p50_ms == null && summary.p95_ms == null)) {
    return 'Belum ada sampel'
  }
  const p50 = typeof summary.p50_ms === 'number' ? summary.p50_ms.toFixed(1) : '-'
  const p95 = typeof summary.p95_ms === 'number' ? summary.p95_ms.toFixed(1) : '-'
  return `${p50} / ${p95} ms`
}

async function toggleDeviceCamera(device: Device): Promise<void> {
  if (isCameraControlSaving.value) return
  isCameraControlSaving.value = true
  errorMessage.value = null
  try {
    const updated = await setDeviceCameraEnabled(device.device_id, !device.camera_enabled)
    devices.value = devices.value.map((item) =>
      item.device_id === updated.device_id ? updated : item,
    )
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isCameraControlSaving.value = false
  }
}

const loadDevicesEpoch = createRefreshEpoch()

async function loadDevices(): Promise<void> {
  const epoch = loadDevicesEpoch.next()
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
    if (!loadDevicesEpoch.isCurrent(epoch)) return
    devices.value = result.items
    total.value = result.pagination.total
    if (activeProfile.value === 'AI_EDGE') {
      const edgeDevices = await listDevices({
        limit: 1,
        offset: 0,
        deployment_profile: 'AI_EDGE',
        is_active: true,
      })
      if (!loadDevicesEpoch.isCurrent(epoch)) return
      edgeDeviceCount.value = edgeDevices.pagination.total
      edgeSetupDevice.value = edgeDevices.items[0] ?? null
      edgeSetupRuntime.value = null
      if (edgeSetupDevice.value) {
        try {
          edgeSetupRuntime.value = await getDeviceRuntimeConfiguration(
            edgeSetupDevice.value.device_id,
          )
        } catch {
          edgeSetupRuntime.value = null
        }
      }
    } else {
      edgeDeviceCount.value = 0
      edgeSetupDevice.value = null
      edgeSetupRuntime.value = null
    }
  } catch (error) {
    if (loadDevicesEpoch.isCurrent(epoch)) errorMessage.value = formatError(error)
  } finally {
    if (loadDevicesEpoch.isCurrent(epoch)) isLoading.value = false
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

function closeDeviceForm(): void {
  if (isSaving.value) return
  isFormOpen.value = false
  formError.value = null
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
  if (isSaving.value) return
  formError.value = null
  if (!activeProfile.value) {
    formError.value = 'Profil server belum dapat dipastikan. Muat ulang halaman lalu coba lagi.'
    return
  }
  if (!form.value.name.trim()) {
    formError.value = 'Nama perangkat wajib diisi.'
    return
  }
  if (!form.value.laboratory_id) {
    formError.value = 'Pilih laboratorium untuk perangkat ini.'
    return
  }
  isSaving.value = true
  let newlyCreatedDevice: Device | null = null
  try {
    if (editingDeviceId.value) {
      await updateDevice(editingDeviceId.value, {
        name: form.value.name.trim(),
        laboratory_id: form.value.laboratory_id,
        is_active: form.value.is_active,
      })
    } else {
      newlyCreatedDevice = await createDevice({
        name: form.value.name.trim(),
        laboratory_id: form.value.laboratory_id,
        deployment_profile: activeProfile.value === 'AI_CENTRAL' ? 'STB_GATEWAY' : 'AI_EDGE',
        device_type: activeProfile.value === 'AI_CENTRAL' ? 'camera_gateway' : 'edge_pc',
      })
    }
    isFormOpen.value = false
    await loadDevices()
    if (newlyCreatedDevice) {
      if (newlyCreatedDevice.deployment_profile === 'AI_EDGE') {
        await startEdgeSetup(newlyCreatedDevice, true)
      } else {
        openCredential(newlyCreatedDevice)
      }
    }
  } catch (error) {
    formError.value = formatError(error)
  } finally {
    isSaving.value = false
  }
}

function openCredential(device: Device): void {
  credentialDevice.value = device
  isEdgeSetupWizard.value = false
  isEdgeSetupMinimized.value = false
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
  installPlatform.value =
    device.deployment_profile === 'STB_GATEWAY' ? 'armbian' : defaultAiEdgePlatform()
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

async function startEdgeSetup(device: Device, provisionForNewDevice = false): Promise<void> {
  if (credentialDevice.value?.device_id === device.device_id && isEdgeSetupWizard.value) {
    isEdgeSetupMinimized.value = false
    return
  }
  openCredential(device)
  isEdgeSetupWizard.value = true
  if (provisionForNewDevice) await issueCredential('provision')
}

function minimizeEdgeSetup(): void {
  if (bundleMessage.value?.startsWith('Paket setup diunduh')) {
    isEdgeSetupMinimized.value = true
  }
}

function closeCredential(): void {
  if (isCredentialLoading.value) return
  issuedCredential.value = null
  credentialDevice.value = null
  isEdgeSetupWizard.value = false
  isEdgeSetupMinimized.value = false
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
  triggerDownload(file, 'device.token')
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

function onDefaultConnectionModeChange(mode: string): void {
  if (mode !== 'same-host' && mode !== 'private-network') return
  setupDefaultsDraft.value.connectionMode = mode
  if (mode === 'same-host') {
    setupDefaultsDraft.value.coreApiUrl = 'http://127.0.0.1:8000'
    if (activeProfile.value === 'AI_CENTRAL') {
      setupDefaultsDraft.value.centralAiUrl = 'http://127.0.0.1:8001'
    }
    return
  }
  if (isLoopbackOrigin(setupDefaultsDraft.value.coreApiUrl)) {
    setupDefaultsDraft.value.coreApiUrl = ''
  }
  if (isLoopbackOrigin(setupDefaultsDraft.value.centralAiUrl)) {
    setupDefaultsDraft.value.centralAiUrl = ''
  }
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
    await deleteDevice(device.device_id, { permanent: !device.is_active })
    devicePendingDeletion.value = null
    if (device.is_active && device.deployment_profile === 'AI_EDGE') {
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
    triggerDownload(file, `presensi-device-${device.device_id}-setup.json`)
    bundleMessage.value =
      'Paket setup diunduh. File ini berisi token rahasia; hapus setelah agent Online.'
  } catch (error) {
    bundleMessage.value = error instanceof Error ? error.message : 'Paket setup tidak dapat dibuat.'
  }
}

async function downloadSetupAndCopyCommand(): Promise<void> {
  downloadSetupBundle()
  if (bundleMessage.value?.startsWith('Paket setup diunduh')) await copyInstallCommand()
}

function onRotationToggle(event: Event): void {
  isRotationOpen.value = (event.currentTarget as HTMLDetailsElement).open
}

function goToPage(nextPage: number): void {
  if (nextPage < 0 || nextPage >= totalPages.value || nextPage === page.value) return
  page.value = nextPage
}

watch([page, statusFilter, includeInactive], () => void loadDevices())
watch(isEdgeSetupWizard, (isOpen) => {
  if (wizardRefreshTimer) clearInterval(wizardRefreshTimer)
  if (isOpen) {
    wizardRefreshTimer = setInterval(() => {
      if (!shouldPausePolling()) void loadDevices()
    }, 4_000)
  }
})
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
    if (shouldPausePolling()) return
    void (async () => {
      await loadAiReadiness()
      await loadDevices()
    })()
  }, 15_000)
})
onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (wizardRefreshTimer) clearInterval(wizardRefreshTimer)
  issuedCredential.value = null
})
</script>

<template>
  <div class="st-page" aria-label="Registry perangkat">
    <UiPageHeader
      eyebrow="Edge fleet monitoring"
      title="Manajemen Perangkat & Kamera"
      description="Daftarkan perangkat, siapkan agent, lalu pantau heartbeat dan kamera."
    >
      <template #actions>
        <RouterLink
          v-if="activeProfile === 'AI_EDGE'"
          class="button button--secondary"
          to="/app/camera-preview"
        >
          Preview kamera
        </RouterLink>
        <UiButton v-if="canRegisterDevice" variant="primary" type="button" @click="openCreate">
          {{ activeProfile === 'AI_EDGE' ? 'Siapkan kamera' : 'Daftarkan perangkat' }}
        </UiButton>
      </template>
    </UiPageHeader>

    <p v-if="errorMessage" class="master-data__alert" role="alert">{{ errorMessage }}</p>
    <UiCard
      v-if="canManage && activeProfile === 'AI_EDGE'"
      title="Siapkan PC kamera AI_EDGE"
      subtitle="Satu alur: daftarkan perangkat, pasang agent, lalu cek kamera dan kesiapan AI."
      data-testid="edge-setup-progress"
    >
      <p v-if="isProfileLoading" class="st-table__muted" role="status">
        Memeriksa kesiapan model dan perangkat…
      </p>
      <template v-else>
        <p v-if="edgeSetupDevice" class="devices-view__setup-device">
          <strong>{{ edgeSetupDevice.name }}</strong> · {{ edgeSetupDevice.laboratory_name }}
        </p>
        <div class="devices-view__setup-steps" aria-label="Tahapan setup AI_EDGE">
          <div
            class="devices-view__setup-step"
            :class="
              edgeSetupDevice
                ? 'devices-view__setup-step--done'
                : 'devices-view__setup-step--pending'
            "
          >
            <span aria-hidden="true">1</span>
            <div>
              <strong>Perangkat</strong><small>{{ edgeSetupDevice ? 'Terdaftar' : 'Belum' }}</small>
            </div>
          </div>
          <div
            class="devices-view__setup-step"
            :class="
              edgeCameraReady
                ? 'devices-view__setup-step--done'
                : 'devices-view__setup-step--pending'
            "
          >
            <span aria-hidden="true">2</span>
            <div>
              <strong>Agent &amp; kamera</strong>
              <small>{{
                edgeCameraReady
                  ? 'Online'
                  : edgeSetupDevice?.camera_enabled === false
                    ? 'Dijeda'
                    : 'Menunggu koneksi'
              }}</small>
            </div>
          </div>
          <div
            class="devices-view__setup-step"
            :class="`devices-view__setup-step--${edgeAiSetupStatus.tone}`"
          >
            <span aria-hidden="true">3</span>
            <div>
              <strong>Kesiapan AI</strong><small>{{ edgeAiSetupStatus.label }}</small>
            </div>
          </div>
        </div>
        <p class="devices-view__setup-detail">
          {{ edgeAiSetupStatus.detail }}
          <template v-if="edgeSetupDevice && edgeAiSetupStatus.tone === 'success'">
            Template wajah siswa dan sesi aktif tetap diperlukan agar presensi dapat dicatat.
          </template>
        </p>
        <div class="devices-view__setup-actions">
          <UiButton
            v-if="!edgeSetupDevice && canRegisterDevice"
            variant="primary"
            type="button"
            data-testid="start-edge-setup"
            @click="openCreate"
          >
            Mulai setup kamera
          </UiButton>
          <UiButton
            v-else-if="edgeSetupDevice && !edgeSetupDevice.last_seen_at"
            variant="primary"
            type="button"
            data-testid="continue-edge-setup"
            @click="startEdgeSetup(edgeSetupDevice)"
          >
            Lanjutkan pemasangan
          </UiButton>
          <UiButton
            v-else-if="edgeSetupDevice && !edgeSetupDevice.camera_enabled"
            variant="secondary"
            type="button"
            :disabled="isCameraControlSaving"
            @click="toggleDeviceCamera(edgeSetupDevice)"
          >
            Aktifkan kamera
          </UiButton>
          <RouterLink
            v-if="edgeCameraReady"
            class="button button--secondary"
            :to="edgePreviewRoute"
            data-testid="edge-setup-preview"
          >
            Buka preview kamera
          </RouterLink>
          <RouterLink
            v-if="edgeSetupDevice && edgeAiSetupStatus.tone !== 'success'"
            class="button button--secondary"
            to="/app/ai-setup"
          >
            Atur AI
          </RouterLink>
          <RouterLink
            v-if="edgeSetupDevice && edgeAiSetupStatus.tone === 'success'"
            class="button button--secondary"
            to="/app/enrollment"
          >
            Daftarkan wajah siswa
          </RouterLink>
        </div>
      </template>
    </UiCard>
    <p
      v-if="canManage && activeProfile === 'AI_EDGE' && edgeDeviceCount > 0"
      class="devices-view__profile-note"
      role="status"
    >
      Profil AI_EDGE pada setup ini memakai satu PC kamera. Nonaktifkan perangkat lama sebelum
      mendaftarkan penggantinya.
    </p>

    <div class="st-kpi" aria-label="Ringkasan armada">
      <UiStat
        label="Total perangkat"
        :value="`${devices.length} unit`"
        caption="Semua lab tercakup"
      />
      <UiStat
        label="Kamera aktif"
        :value="`${onlineCount} unit`"
        caption="Online & siap deteksi"
        tone="success"
      />
      <UiStat
        label="Perlu perhatian"
        :value="`${warnCount} unit`"
        caption="Kamera offline / standby"
        tone="warning"
      />
    </div>

    <details
      v-if="canManage"
      class="devices-view__advanced-defaults"
      :open="activeProfile === 'AI_CENTRAL'"
    >
      <summary>
        {{
          activeProfile === 'AI_EDGE'
            ? 'Pengaturan koneksi lanjutan'
            : 'Default koneksi untuk installer kamera'
        }}
      </summary>
      <UiCard
        title="Default koneksi untuk installer kamera"
        subtitle="Digunakan untuk paket perangkat berikutnya dan disimpan hanya di browser admin ini."
        data-testid="device-setup-defaults-card"
      >
        <template #header>
          <UiButton
            variant="secondary"
            type="button"
            :disabled="isProfileLoading"
            data-testid="edit-device-setup-defaults"
            @click="openSetupDefaultsEditor"
          >
            <span class="st-material-icon" aria-hidden="true">edit</span>
            Edit
          </UiButton>
        </template>
        <p v-if="isProfileLoading" role="status">Memuat default koneksi…</p>
        <dl v-else class="devices-view__defaults-summary">
          <div>
            <dt>URL Core API</dt>
            <dd>
              <code>{{ setupDefaults.coreApiUrl || 'Belum diatur' }}</code>
            </dd>
          </div>
          <div>
            <dt>Koneksi</dt>
            <dd>{{ setupDefaultsConnectionLabel }}</dd>
          </div>
          <div v-if="activeProfile === 'AI_CENTRAL'">
            <dt>URL AI Central</dt>
            <dd>
              <code>{{ setupDefaults.centralAiUrl || 'Belum diatur' }}</code>
            </dd>
          </div>
          <div v-if="activeProfile === 'AI_EDGE'">
            <dt>Model enrollment · terkunci</dt>
            <dd>{{ enrollmentModelVersion || 'Belum dilaporkan server' }}</dd>
          </div>
        </dl>
        <p v-if="setupDefaultsMessage" class="master-data__success" role="status">
          {{ setupDefaultsMessage }}
        </p>
      </UiCard>
    </details>

    <UiModal
      v-if="isSetupDefaultsOpen"
      title="Edit default koneksi installer"
      data-testid="device-setup-defaults-dialog"
      @close="closeSetupDefaultsEditor"
    >
      <form
        id="device-setup-defaults-form"
        class="master-data__form devices-view__setup-defaults-form"
        @submit.prevent="saveSetupDefaultsAndClose"
      >
        <p class="devices-view__profile-note">
          Nilai ini disimpan hanya di browser admin ini, bukan di server. Token perangkat tidak
          disimpan di sini; kredensial dibuat terpisah untuk tiap perangkat.
        </p>
        <label v-if="activeProfile === 'AI_CENTRAL'">
          Jaringan dari host kamera ke server
          <UiSelect
            :model-value="setupDefaultsDraft.connectionMode"
            aria-label="Default jaringan device"
            @update:model-value="onDefaultConnectionModeChange"
          >
            <option value="same-host">Komputer yang sama · localhost</option>
            <option value="private-network">LAN/VPN sekolah · HTTPS</option>
          </UiSelect>
        </label>
        <p v-else-if="activeProfile === 'AI_EDGE'" class="devices-view__profile-note">
          AI_EDGE memakai alamat Core API berikut. Koneksi otomatis diperlakukan sebagai localhost
          untuk komputer yang sama atau HTTPS untuk host lain.
        </p>
        <label>
          Default URL Core API
          <UiInput
            id="device-default-core-api-url"
            v-model="setupDefaultsDraft.coreApiUrl"
            type="url"
            autocomplete="url"
            placeholder="http://127.0.0.1:8000 atau https://presensi.sekolah.id"
          />
        </label>
        <p v-if="activeProfile === 'AI_EDGE'" class="devices-view__profile-note">
          URL ini hanya dipakai untuk perintah dan paket installer kamera baru. Pada laptop ini
          gunakan <code>http://127.0.0.1:8000</code>; untuk PC kamera lain, gunakan alamat Core API
          yang bisa dijangkau lewat LAN/VPN sekolah dengan HTTPS. Perangkat yang sudah terdaftar
          tidak berubah saat default ini diedit.
        </p>
        <label v-if="activeProfile === 'AI_CENTRAL'">
          Default URL AI Central (STB_GATEWAY)
          <UiInput
            v-model="setupDefaultsDraft.centralAiUrl"
            type="url"
            autocomplete="url"
            placeholder="https://ai.sekolah.id"
          />
        </label>
        <label v-if="activeProfile === 'AI_EDGE'">
          Versi model enrollment (terkunci)
          <UiInput
            id="device-default-model-version"
            :model-value="enrollmentModelVersion"
            disabled
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
        <p v-if="setupDefaultsMessage" class="master-data__alert" role="alert">
          {{ setupDefaultsMessage }}
        </p>
      </form>
      <template #footer>
        <UiButton variant="secondary" type="button" @click="closeSetupDefaultsEditor">
          Batal
        </UiButton>
        <UiButton
          variant="primary"
          type="button"
          form="device-setup-defaults-form"
          data-testid="save-device-setup-defaults"
          @click="saveSetupDefaultsAndClose"
        >
          Simpan untuk paket berikutnya
        </UiButton>
      </template>
    </UiModal>

    <div class="devices-view__toolbar">
      <form class="master-data__search" role="search" @submit.prevent="submitSearch">
        <label class="visually-hidden" for="device-search">Cari perangkat atau laboratorium</label>
        <UiInput
          id="device-search"
          v-model="searchText"
          type="search"
          placeholder="Cari perangkat atau laboratorium…"
        />
        <UiButton variant="secondary" type="submit">Cari</UiButton>
      </form>
      <label class="enrollment-view__class-picker">
        Status
        <UiSelect v-model="statusFilter" aria-label="Filter status perangkat">
          <option value="all">Semua status</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
          <option value="warning">Warning</option>
        </UiSelect>
      </label>
      <label v-if="canManage" class="master-data__checkbox">
        <input v-model="includeInactive" type="checkbox" /> Tampilkan perangkat nonaktif
      </label>
    </div>
    <p class="devices-view__camera-help">
      Resolusi dan FPS aktual berasal dari kamera pada host. Kualitas frame dan sampling diatur di
      AI &amp; kamera; resolusi/FPS diubah lewat wizard kamera pada host perangkat.
    </p>
    <UiModal
      v-if="isFormOpen"
      :title="
        editingDeviceId
          ? 'Ubah perangkat'
          : activeProfile === 'AI_EDGE'
            ? 'Siapkan PC kamera'
            : 'Daftarkan perangkat'
      "
      wide
      @close="closeDeviceForm"
    >
      <p v-if="formError" class="master-data__alert" role="alert">{{ formError }}</p>
      <form id="device-registration-form" class="master-data__form" @submit.prevent="submitForm">
        <label>
          Nama perangkat
          <UiInput
            v-model="form.name"
            required
            maxlength="120"
            autocomplete="off"
            data-testid="register-device-name"
          />
        </label>
        <label>
          Laboratorium
          <UiSelect v-model="form.laboratory_id" required data-testid="register-device-lab">
            <option value="" disabled>Pilih laboratorium</option>
            <option v-for="lab in laboratories" :key="lab.id" :value="lab.id">
              {{ lab.code }} · {{ lab.name }}
            </option>
          </UiSelect>
        </label>
        <p class="devices-view__profile-note">
          Profil instalasi: {{ profileLabel(form.deployment_profile) }}
        </p>
        <p
          v-if="!editingDeviceId && activeProfile === 'AI_EDGE'"
          class="devices-view__profile-note"
        >
          Setelah disimpan, wizard akan membuat paket setup agent. Jalankan satu perintah di PC
          kamera untuk memilih webcam dan mengaktifkannya.
        </p>
        <p v-else-if="!editingDeviceId" class="devices-view__profile-note">
          Pendaftaran menambahkan perangkat ke registry. Status Online muncul setelah agent
          diinstal, memakai kredensial perangkat, lalu mengirim heartbeat ke Core API.
        </p>
        <label v-if="editingDeviceId" class="master-data__checkbox">
          <input v-model="form.is_active" type="checkbox" /> Perangkat aktif
        </label>
      </form>
      <template #footer>
        <UiButton variant="secondary" type="button" :disabled="isSaving" @click="closeDeviceForm">
          Batal
        </UiButton>
        <UiButton
          variant="primary"
          type="button"
          :disabled="isSaving"
          form="device-registration-form"
          data-testid="submit-device-registration"
          @click="submitForm"
        >
          {{
            isSaving
              ? 'Menyimpan…'
              : editingDeviceId
                ? 'Simpan perubahan'
                : activeProfile === 'AI_EDGE'
                  ? 'Daftar & lanjutkan'
                  : 'Daftarkan'
          }}
        </UiButton>
      </template>
    </UiModal>

    <div class="st-tablewrap">
      <table class="devices-view__table st-table">
        <thead>
          <tr>
            <th scope="col">Perangkat</th>
            <th scope="col">Laboratorium</th>
            <th scope="col">Deployment</th>
            <th scope="col">Versi app / model</th>
            <th scope="col">Kamera &amp; kualitas</th>
            <th scope="col">Heartbeat</th>
            <th scope="col">Baca kamera p50 / p95</th>
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
              <small>Model: {{ device.model_version ?? '-' }}</small>
            </td>
            <td data-label="Kamera & kualitas">
              <strong>{{ cameraLabel(device) }}</strong>
              <small v-if="!device.last_seen_at">
                Menunggu agent terpasang dan kamera tersambung.
              </small>
              <small v-else-if="device.camera_enabled">{{ cameraModeLabel(device) }}</small>
              <small v-else-if="device.camera_status === 'disabled'">
                Kamera sudah ditutup oleh agent
              </small>
              <small v-else>Menunggu agent menghentikan kamera</small>
              <small>Kualitas: {{ cameraQualityLabel(device) }}</small>
              <small v-if="cameraQualitySourceLabel(device)">
                {{ cameraQualitySourceLabel(device) }}
              </small>
              <RouterLink
                v-if="canManage && device.deployment_profile === 'STB_GATEWAY'"
                class="devices-view__camera-link"
                to="/app/ai-setup"
              >
                Atur kualitas
              </RouterLink>
            </td>
            <td data-label="Heartbeat">
              {{ formatLastSeen(device.last_seen_at) }}
              <small>Timeout {{ device.heartbeat_timeout_seconds }} detik</small>
            </td>
            <td
              data-label="Baca kamera p50 / p95"
              title="Waktu agent membaca frame kamera; p50/p95 dihitung dari 20–512 frame terakhir. Ini bukan latency pengenalan AI."
            >
              {{ cameraLatencyLabel(device) }}
            </td>
            <td data-label="Status">
              <span
                class="status-badge"
                :class="`status-badge--${device.health_status}`"
                :aria-label="`Status ${healthLabel(device.health_status)}`"
              >
                {{ healthLabel(device.health_status) }}
              </span>
              <small v-if="!device.is_active">Nonaktif di registry.</small>
              <small v-else-if="!device.last_seen_at">
                Terdaftar aktif; agent belum mengirim heartbeat. Klik “Siapkan agent” untuk memasang
                agent kamera.
              </small>
              <small v-else-if="device.health_status === 'offline'">
                Heartbeat melewati batas waktu.
              </small>
              <small v-else-if="device.health_status === 'warning'">
                {{ warningStatusMessage(device) }}
              </small>
            </td>
            <td v-if="canManage" data-label="Aksi">
              <div class="devices-view__actions">
                <UiButton variant="text" type="button" @click="openEdit(device)"> Ubah </UiButton>
                <UiButton
                  v-if="device.last_seen_at"
                  variant="secondary"
                  type="button"
                  :disabled="!device.is_active || isCameraControlSaving"
                  :aria-label="device.camera_enabled ? 'Jeda kamera' : 'Aktifkan kamera'"
                  @click="toggleDeviceCamera(device)"
                >
                  {{
                    isCameraControlSaving
                      ? 'Menerapkan…'
                      : device.camera_enabled
                        ? 'Jeda kamera'
                        : 'Aktifkan kamera'
                  }}
                </UiButton>
                <UiButton
                  variant="secondary"
                  type="button"
                  :disabled="!device.is_active"
                  :title="
                    device.is_active
                      ? device.last_seen_at
                        ? 'Token untuk autentikasi AI_EDGE atau STB_GATEWAY ke Core API'
                        : 'Lanjutkan wizard setup agent di PC kamera'
                      : 'Aktifkan perangkat lebih dulu'
                  "
                  @click="
                    device.deployment_profile === 'AI_EDGE' && !device.last_seen_at
                      ? startEdgeSetup(device)
                      : openCredential(device)
                  "
                >
                  {{
                    device.last_seen_at
                      ? 'Kredensial'
                      : device.deployment_profile === 'AI_EDGE'
                        ? 'Lanjutkan setup'
                        : 'Siapkan agent'
                  }}
                </UiButton>
                <UiButton
                  variant="danger"
                  type="button"
                  :aria-label="
                    device.is_active
                      ? `Nonaktifkan ${device.name}`
                      : `Hapus permanen ${device.name}`
                  "
                  :title="
                    device.is_active
                      ? 'Menonaktifkan perangkat dan mencabut kredensialnya'
                      : 'Menghapus perangkat nonaktif jika tidak memiliki riwayat atau layar kiosk'
                  "
                  @click="requestDeviceDeletion(device)"
                >
                  {{ device.is_active ? 'Hapus' : 'Hapus permanen' }}
                </UiButton>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="master-data__pagination">
      <span>{{ total }} perangkat</span>
      <div>
        <UiButton variant="secondary" :disabled="page === 0" @click="goToPage(page - 1)">
          Sebelumnya
        </UiButton>
        <span>Halaman {{ page + 1 }} dari {{ totalPages }}</span>
        <UiButton
          variant="secondary"
          :disabled="page + 1 >= totalPages"
          @click="goToPage(page + 1)"
        >
          Berikutnya
        </UiButton>
      </div>
    </footer>

    <div
      v-if="credentialDevice && !isEdgeSetupMinimized"
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
          <UiButton
            v-if="!issuedCredential"
            variant="text"
            type="button"
            aria-label="Tutup kredensial"
            :disabled="isCredentialLoading"
            @click="closeCredential"
          >
            Tutup
          </UiButton>
        </header>

        <template v-if="isEdgeSetupWizard && credentialDevice.deployment_profile === 'AI_EDGE'">
          <ol class="devices-view__setup-steps devices-view__setup-steps--modal">
            <li class="devices-view__setup-step devices-view__setup-step--done">
              <span aria-hidden="true">1</span>
              <div><strong>Perangkat</strong><small>Terdaftar</small></div>
            </li>
            <li
              class="devices-view__setup-step"
              :class="
                edgeCameraReady
                  ? 'devices-view__setup-step--done'
                  : 'devices-view__setup-step--pending'
              "
            >
              <span aria-hidden="true">2</span>
              <div>
                <strong>Agent &amp; kamera</strong>
                <small>{{ edgeCameraReady ? 'Online' : 'Menunggu setup di PC kamera' }}</small>
              </div>
            </li>
            <li
              class="devices-view__setup-step"
              :class="`devices-view__setup-step--${edgeAiSetupStatus.tone}`"
            >
              <span aria-hidden="true">3</span>
              <div>
                <strong>Kesiapan AI</strong><small>{{ edgeAiSetupStatus.label }}</small>
              </div>
            </li>
          </ol>

          <p v-if="isCredentialLoading" class="devices-view__credential-status" role="status">
            Membuat akses aman untuk agent…
          </p>
          <p v-if="credentialError" class="master-data__alert" role="alert">
            {{ credentialError }}
          </p>

          <template v-if="!issuedCredential">
            <p class="devices-view__credential-instructions">
              Perangkat sudah terdaftar. Buat akses agent satu kali; token langsung dipakai di paket
              setup dan tidak perlu disalin manual.
            </p>
            <UiButton
              variant="primary"
              type="button"
              :disabled="isCredentialLoading"
              data-testid="edge-wizard-provision"
              @click="issueCredential('provision')"
            >
              {{ isCredentialLoading ? 'Menyiapkan…' : 'Buat akses agent & lanjutkan' }}
            </UiButton>
            <details
              :open="isRotationOpen"
              class="devices-view__rotation"
              @toggle="onRotationToggle"
            >
              <summary>Token pernah dibuat atau hilang?</summary>
              <form class="devices-view__rotation-form" @submit.prevent="issueCredential('rotate')">
                <label for="edge-wizard-rotation-reason">Alasan membuat token pengganti</label>
                <UiInput
                  id="edge-wizard-rotation-reason"
                  v-model="rotationReason"
                  required
                  maxlength="200"
                  placeholder="Contoh: token setup sebelumnya hilang"
                />
                <UiButton
                  variant="secondary"
                  type="submit"
                  :disabled="isCredentialLoading || !rotationReason.trim()"
                >
                  {{ isCredentialLoading ? 'Memproses…' : 'Rotasi token & lanjutkan' }}
                </UiButton>
              </form>
            </details>
          </template>

          <template v-else>
            <section class="devices-view__setup-panel" aria-label="Pasang agent kamera">
              <div>
                <h3>Jalankan setup di PC kamera</h3>
                <p>
                  Pilih sistem operasi PC yang terhubung ke webcam. Installer akan memilih kamera,
                  menguji frame, lalu menjalankan agent.
                </p>
              </div>
              <label for="device-install-platform">Sistem operasi PC kamera</label>
              <UiSelect id="device-install-platform" v-model="installPlatform">
                <option value="ubuntu">Ubuntu Linux</option>
                <option value="windows">Windows</option>
              </UiSelect>
              <details class="devices-view__setup-advanced">
                <summary>PC kamera berbeda dari server aplikasi?</summary>
                <p>
                  Untuk satu PC gunakan localhost. Jika kamera berada di komputer lain, masukkan
                  alamat Core API HTTPS yang bisa dijangkau dari PC kamera.
                </p>
                <label for="device-core-api-url">Alamat Core API</label>
                <UiInput
                  id="device-core-api-url"
                  v-model="coreApiUrl"
                  type="url"
                  required
                  autocomplete="url"
                  placeholder="http://127.0.0.1:8000"
                />
              </details>
              <p
                v-if="setupCommandState.error"
                class="devices-view__credential-warning"
                role="alert"
              >
                {{ setupCommandState.error }}
              </p>
              <UiButton
                variant="primary"
                type="button"
                :disabled="!setupCommandState.command"
                data-testid="edge-wizard-download-setup"
                @click="downloadSetupAndCopyCommand"
              >
                Unduh paket &amp; salin perintah
              </UiButton>
              <p v-if="bundleMessage" class="devices-view__credential-status" role="status">
                {{ bundleMessage }}
              </p>
              <p v-if="installCommandMessage" class="devices-view__credential-status" role="status">
                {{ installCommandMessage }}
              </p>
              <div v-if="setupCommandState.command" class="devices-view__credential-commands">
                <p>Di PC kamera, buka Terminal lalu tempel perintah berikut:</p>
                <pre
                  data-testid="device-install-command"
                ><code>{{ setupCommandState.command }}</code></pre>
                <UiButton
                  v-if="bundleMessage?.startsWith('Paket setup diunduh')"
                  variant="secondary"
                  type="button"
                  @click="copyInstallCommand"
                >
                  Salin perintah lagi
                </UiButton>
              </div>
              <p class="devices-view__credential-warning" role="note">
                Paket setup berisi token rahasia. Jika diunduh di komputer berbeda, pindahkan file
                ke folder Downloads PC kamera. Hapus file setelah agent tersambung.
              </p>
              <p v-if="installPlatform === 'ubuntu'" class="devices-view__credential-instructions">
                Di Ubuntu, installer juga memasang agent sebagai systemd user service dan
                mengaktifkan autostart setelah reboot jika izin sudo tersedia.
              </p>
            </section>

            <section
              class="devices-view__setup-result"
              :class="
                edgeCameraReady
                  ? 'devices-view__setup-result--ready'
                  : 'devices-view__setup-result--pending'
              "
              role="status"
            >
              <strong>{{
                edgeCameraReady ? 'Agent dan kamera Online' : 'Menunggu agent tersambung'
              }}</strong>
              <p>
                {{
                  edgeCameraReady
                    ? `${edgeSetupDevice?.camera_metrics?.frame_width ?? '—'} × ${edgeSetupDevice?.camera_metrics?.frame_height ?? '—'} · ${edgeSetupDevice?.camera_metrics?.capture_fps?.toFixed(1) ?? '—'} FPS`
                    : 'Setelah perintah selesai, dashboard mengecek heartbeat dan kamera otomatis setiap beberapa detik.'
                }}
              </p>
              <RouterLink
                v-if="edgeCameraReady"
                class="button button--secondary"
                :to="edgePreviewRoute"
                data-testid="edge-wizard-preview"
              >
                Uji preview kamera
              </RouterLink>
            </section>

            <section
              class="devices-view__setup-result"
              :class="`devices-view__setup-result--${edgeAiSetupStatus.tone}`"
              role="status"
            >
              <strong>{{ edgeAiSetupStatus.label }}</strong>
              <p>{{ edgeAiSetupStatus.detail }}</p>
              <RouterLink
                v-if="edgeAiSetupStatus.tone !== 'success'"
                to="/app/ai-setup"
                class="button button--secondary"
              >
                Buka AI &amp; Kamera
              </RouterLink>
              <RouterLink v-else to="/app/enrollment" class="button button--secondary">
                Daftarkan wajah siswa
              </RouterLink>
            </section>

            <div
              v-if="bundleMessage?.startsWith('Paket setup diunduh')"
              class="master-data__form-actions"
            >
              <UiButton variant="secondary" type="button" @click="minimizeEdgeSetup">
                Lanjutkan di dashboard
              </UiButton>
            </div>
          </template>
        </template>

        <template v-else-if="issuedCredential">
          <p class="devices-view__credential-warning" role="alert">
            Token ini hanya ditampilkan sekarang. Salin atau unduh sebelum menutup panel. Sistem
            hanya menyimpan verifier token dan tidak dapat menampilkan token lama kembali.
          </p>
          <label class="devices-view__token-label" for="device-token">Token perangkat</label>
          <div class="devices-view__token-row">
            <UiInput
              id="device-token"
              :value="issuedCredential.token"
              type="text"
              readonly
              autocomplete="off"
              spellcheck="false"
              aria-label="Token perangkat, hanya ditampilkan setelah dibuat"
              data-testid="device-token-value"
            />
            <UiButton variant="secondary" type="button" @click="copyCredential"> Salin </UiButton>
            <UiButton variant="secondary" type="button" @click="downloadCredential">
              Unduh device.token
            </UiButton>
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
            <UiSelect id="device-install-platform" v-model="installPlatform">
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
            </UiSelect>
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
                <option value="same-host">Komputer yang sama - localhost</option>
                <option value="private-network">LAN/VPN sekolah - HTTPS privat</option>
                <option value="public-domain">Domain publik - belum diaktifkan</option>
                <option value="cloudflare-tunnel">Cloudflare Tunnel - belum diaktifkan</option>
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
            <UiInput
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
            <UiInput
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
              <UiInput
                id="device-model-version"
                :model-value="enrollmentModelVersion"
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
            <UiButton
              variant="secondary"
              type="button"
              :disabled="
                !setupCommandState.command || !bundleMessage?.startsWith('Paket setup diunduh')
              "
              @click="copyInstallCommand"
            >
              Salin perintah instalasi perangkat
            </UiButton>
            <UiButton
              variant="primary"
              type="button"
              :disabled="!setupCommandState.command"
              @click="downloadSetupBundle"
            >
              Unduh paket setup perangkat
            </UiButton>
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
            <UiButton variant="primary" type="button" @click="closeCredential">
              Saya sudah menyimpan token
            </UiButton>
          </div>
        </template>

        <template v-else>
          <p class="devices-view__credential-instructions">
            Kredensial ini adalah identitas agent
            {{
              credentialDevice.deployment_profile === 'AI_EDGE'
                ? 'AI_EDGE di PC kamera'
                : 'STB_GATEWAY'
            }}
            untuk mengakses Core API. Agent memakainya untuk mengirim heartbeat dan status
            perangkat; kredensial ini bukan akun login staf.
          </p>
          <p class="devices-view__credential-instructions">
            Buat token untuk pemasangan pertama agent. Token tidak bisa dibuka ulang setelah panel
            ditutup. Jika token lama hilang, gunakan rotasi untuk menerbitkan token pengganti.
          </p>
          <p v-if="credentialError" class="master-data__alert" role="alert">
            {{ credentialError }}
          </p>
          <div class="devices-view__credential-actions">
            <UiButton
              variant="primary"
              type="button"
              :disabled="isCredentialLoading"
              @click="issueCredential('provision')"
            >
              {{ isCredentialLoading ? 'Membuat token…' : 'Buat token pertama' }}
            </UiButton>
          </div>
          <details :open="isRotationOpen" class="devices-view__rotation" @toggle="onRotationToggle">
            <summary>Token pernah dibuat, hilang, atau perlu diganti?</summary>
            <form class="devices-view__rotation-form" @submit.prevent="issueCredential('rotate')">
              <label for="credential-rotation-reason">Alasan rotasi</label>
              <UiInput
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
              <UiButton
                variant="secondary"
                type="submit"
                :disabled="isCredentialLoading || !rotationReason.trim()"
              >
                {{ isCredentialLoading ? 'Merotasi…' : 'Rotasi dan tampilkan token baru' }}
              </UiButton>
            </form>
          </details>
          <div class="master-data__form-actions">
            <UiButton
              variant="text"
              type="button"
              :disabled="isCredentialLoading"
              @click="closeCredential"
            >
              Batal
            </UiButton>
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
            <p class="master-data__eyebrow">
              {{
                devicePendingDeletion.is_active
                  ? 'Konfirmasi penonaktifan'
                  : 'Konfirmasi hapus permanen'
              }}
            </p>
            <h2 id="device-delete-title">
              {{ devicePendingDeletion.is_active ? 'Nonaktifkan' : 'Hapus permanen' }}
              {{ devicePendingDeletion.name }}?
            </h2>
          </div>
        </header>
        <p id="device-delete-description" class="devices-view__credential-warning">
          <template v-if="devicePendingDeletion.is_active">
            Perangkat akan dinonaktifkan dan kredensialnya dicabut. Data presensi dan audit lama
            tetap tersimpan. Anda dapat melihatnya kembali dengan filter perangkat nonaktif.
          </template>
          <template v-else>
            Perangkat dihapus dari daftar hanya jika tidak memiliki riwayat pengenalan atau layar
            kiosk. Data presensi dan audit tetap tersimpan; perangkat yang masih terhubung ke data
            tersebut akan ditolak dan tetap nonaktif.
          </template>
        </p>
        <p v-if="deleteError" class="master-data__alert" role="alert">{{ deleteError }}</p>
        <div class="master-data__form-actions">
          <UiButton
            variant="secondary"
            type="button"
            :disabled="isDeletingDevice"
            @click="closeDeviceDeletion"
          >
            Batal
          </UiButton>
          <UiButton
            variant="danger"
            type="button"
            :disabled="isDeletingDevice"
            @click="confirmDeviceDeletion"
          >
            {{
              isDeletingDevice
                ? devicePendingDeletion.is_active
                  ? 'Menonaktifkan…'
                  : 'Menghapus…'
                : devicePendingDeletion.is_active
                  ? 'Ya, nonaktifkan perangkat'
                  : 'Ya, hapus permanen'
            }}
          </UiButton>
        </div>
      </section>
    </div>
  </div>
</template>
