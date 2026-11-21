<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ApiError,
  listClasses,
  listClassEnrollmentStatus,
  listFaceTemplates,
  revokeFaceTemplate,
  submitEnrollmentCaptures,
  type EnrollmentCaptureResult,
  type EnrollmentStudentStatus,
  type FaceTemplate,
  type SchoolClass,
} from '../api/client'
import {
  UiAvatar,
  UiBadge,
  UiButton,
  UiCard,
  UiEmptyState,
  UiModal,
  UiPageHeader,
  UiSearchInput,
  UiSelect,
  UiStat,
  UiTextarea,
} from '../components/ui'
import FaceOverlay from '../components/FaceOverlay.vue'
import { useFaceLandmarks } from '../composables/useFaceLandmarks'
import { associateFaceRoles } from '../utils/faceLandmarks'
import { useAuthStore } from '../stores/auth'
import { fetchWithPreviewTimeout } from '../utils/previewFetch'

type CapturePhase = 'ready' | 'countdown' | 'capturing' | 'processing' | 'confirming' | 'complete'
type CameraFaceObservation = {
  x: number
  y: number
  width: number
  height: number
  landmarks?: number[][] | null
  role?: 'primary' | 'background' | 'ambiguous' | null
  is_primary?: boolean
  acceptable?: boolean
  reason_codes?: string[]
  [key: string]: unknown
}
type CameraObservation = {
  state: 'pending' | 'ready' | 'adjust' | 'no_face' | 'multiple_faces' | 'unavailable'
  message: string
  frame_width: number
  frame_height: number
  face_count: number
  faces: CameraFaceObservation[]
}
type LocalPreviewStatus = {
  camera_open: boolean
  recognition_state?: string
  camera_observation?: CameraObservation
}

const auth = useAuthStore()
const classes = ref<SchoolClass[]>([])
const students = ref<EnrollmentStudentStatus[]>([])
const selectedClassId = ref('')
const selectedStudentId = ref('')
const rosterSearch = ref('')
const filteredStudents = computed(() => {
  const q = rosterSearch.value.trim().toLowerCase()
  if (!q) return students.value
  return students.value.filter(
    (student) =>
      student.full_name.toLowerCase().includes(q) ||
      student.student_number.toLowerCase().includes(q),
  )
})
const enrolledCount = computed(
  () => students.value.filter((s) => s.template_status === 'enrolled').length,
)
const pendingCount = computed(
  () => students.value.filter((s) => s.template_status !== 'enrolled').length,
)
const capturePoseSteps = [
  { label: 'Lihat lurus ke kamera', guidance: 'Wajah menghadap kamera dengan posisi santai.' },
  {
    label: 'Putar sedikit ke kiri',
    guidance: 'Gerakkan kepala sedikit saja, jangan sampai keluar frame.',
  },
  {
    label: 'Putar sedikit ke kanan',
    guidance: 'Gerakkan kepala sedikit saja, jangan sampai keluar frame.',
  },
  { label: 'Kembali menghadap lurus', guidance: 'Lihat kamera seperti pada foto pertama.' },
] as const
const videoElement = ref<HTMLVideoElement | null>(null)
const labImageElement = ref<HTMLImageElement | null>(null)
const isLocalAIEdgeHost = ['localhost', '127.0.0.1'].includes(window.location.hostname)
const cameraSource = ref<'device' | 'lab'>(isLocalAIEdgeHost ? 'lab' : 'device')
const labStreamKey = ref(0)
const labStreamFailed = ref(false)
const localPreviewToken = ref<string | null>(null)
const cameraObservation = ref<CameraObservation | null>(null)
const localPreviewRecognitionState = ref<string | null>(null)
const localPreviewError = ref<string | null>(null)
const isOpeningLocalPreview = ref(false)
const devicePreviewError = ref<string | null>(null)
const previewHost = isLocalAIEdgeHost ? window.location.hostname : null
const previewBaseUrl = previewHost ? `http://${previewHost}:8765` : null
const labStreamSrc = computed(() => {
  if (!previewBaseUrl || !localPreviewToken.value) return null
  return `${previewBaseUrl}/v1/stream?token=${encodeURIComponent(localPreviewToken.value)}&retry=${labStreamKey.value}`
})
const capturePhase = ref<CapturePhase>('ready')
const countdownValue = ref(3)
const captureIndex = ref(0)
const captureResult = ref<EnrollmentCaptureResult | null>(null)
const duplicateWarnings = computed(() => captureResult.value?.duplicate_warnings ?? [])
const confirmationRequired = computed(() => captureResult.value?.confirmation_required ?? true)
const activeTemplates = ref<FaceTemplate[]>([])
const isLoadingTemplates = ref(false)
const isRevoking = ref(false)
const showRevokeConfirm = ref(false)
const revokeReason = ref('')
const identityConfirmed = ref(false)
const pageError = ref<string | null>(null)
const pageMessage = ref<string | null>(null)
const isLoading = ref(false)
const isStarting = ref(false)
const stream = ref<MediaStream | null>(null)
const selectedStudent = computed(
  () => students.value.find((student) => student.id === selectedStudentId.value) ?? null,
)
const capturePoseStep = computed(() => capturePoseSteps[captureIndex.value - 1] ?? null)
const deviceFaceMesh = useFaceLandmarks(
  videoElement,
  computed(() => cameraSource.value === 'device' && stream.value !== null),
)
const labFaceMesh = useFaceLandmarks(
  labImageElement,
  computed(
    () =>
      cameraSource.value === 'lab' &&
      selectedStudent.value !== null &&
      Boolean(labStreamSrc.value) &&
      !labStreamFailed.value &&
      !localPreviewError.value,
  ),
)
const labFaceOverlays = computed(() =>
  associateFaceRoles(labFaceMesh.faces.value, cameraObservation.value?.faces ?? []),
)
let flowVersion = 0
let previewGeneration = 0
let statusTimer: number | undefined
let streamRetryTimer: number | undefined
let streamRetryAttempts = 0
const MAX_STREAM_RETRY_DELAY_MS = 8000

const cameraObservationLabel = computed(() => {
  if (cameraSource.value === 'lab' && localPreviewRecognitionState.value === 'camera_disabled') {
    return 'Kamera dijeda'
  }
  switch (cameraObservation.value?.state) {
    case 'ready':
      return 'Wajah siap ditangkap'
    case 'adjust':
      return 'Atur posisi atau pencahayaan'
    case 'no_face':
      return 'Mencari wajah'
    case 'multiple_faces':
      return 'Pastikan satu orang di dalam frame'
    case 'unavailable':
      return 'Pemeriksaan wajah tidak tersedia'
    default:
      return 'Menyiapkan deteksi wajah AI_EDGE'
  }
})
const cameraObservationMessage = computed(
  () =>
    localPreviewError.value ??
    cameraObservation.value?.message ??
    'Menunggu hasil deteksi wajah dari AI_EDGE…',
)
const deviceCameraGuidanceLabel = computed(() => {
  if (devicePreviewError.value) return 'Kamera perangkat belum siap'
  if (deviceFaceMesh.state.value === 'loading') return 'Menyiapkan deteksi wajah…'
  if (deviceFaceMesh.state.value === 'unavailable') return 'Deteksi wajah tidak tersedia'
  if (deviceFaceMesh.state.value === 'ready') {
    return deviceFaceMesh.faces.value.length ? 'Wajah terdeteksi' : 'Mencari wajah'
  }
  return stream.value ? 'Menghubungkan deteksi wajah…' : 'Kamera perangkat belum aktif'
})
const deviceCameraGuidanceMessage = computed(() => {
  if (devicePreviewError.value) return devicePreviewError.value
  if (deviceFaceMesh.state.value === 'loading') {
    return 'Model mesh lokal sedang disiapkan untuk kamera ini.'
  }
  if (deviceFaceMesh.state.value === 'ready' && deviceFaceMesh.faces.value.length) {
    const points = deviceFaceMesh.faces.value[0]?.landmarks?.length ?? 478
    return `Mesh aktif · ${points} titik. Capture tetap divalidasi oleh server.`
  }
  if (deviceFaceMesh.state.value === 'ready' && !deviceFaceMesh.faces.value.length) {
    return 'Posisikan satu wajah di depan kamera dengan pencahayaan yang cukup.'
  }
  if (deviceFaceMesh.state.value === 'unavailable') {
    return deviceFaceMesh.errorMessage.value ?? 'Periksa dukungan kamera dan browser.'
  }
  return 'Kamera ini diproses di browser. Capture pendaftaran tetap divalidasi oleh server.'
})
const labMeshStatus = computed(() => {
  if (localPreviewRecognitionState.value === 'camera_disabled') {
    return 'Mesh lokal menunggu kamera dilanjutkan.'
  }
  if (localPreviewError.value) return localPreviewError.value
  if (!labStreamSrc.value || labStreamFailed.value) return 'Menunggu stream AI_EDGE.'
  if (labFaceMesh.state.value === 'loading') return 'Memuat model mesh lokal…'
  if (labFaceMesh.state.value === 'unavailable') {
    return labFaceMesh.errorMessage.value ?? 'Mesh lokal tidak tersedia.'
  }
  if (labFaceMesh.state.value !== 'ready') return 'Menunggu frame kamera…'
  if (!labFaceMesh.frameSize.value.width) return 'Model siap · menunggu frame kamera.'
  const face = labFaceMesh.faces.value[0]
  if (!face) return 'Model siap · mencari wajah di frame.'
  const points = face.landmarks?.length ?? 478
  const fps = labFaceMesh.fps.value === null ? '' : ` · ${labFaceMesh.fps.value} FPS`
  return `Mesh aktif · ${points} titik${fps}.`
})
const deviceCameraGuidanceTone = computed(() => {
  if (devicePreviewError.value || deviceFaceMesh.state.value === 'unavailable') return 'unavailable'
  if (deviceFaceMesh.faces.value.length) return 'ready'
  if (deviceFaceMesh.state.value === 'ready') return 'no_face'
  return deviceFaceMesh.state.value
})
const canStartAgentCapture = computed(
  () =>
    cameraSource.value !== 'lab' ||
    Boolean(
      localPreviewToken.value &&
      cameraObservation.value?.state === 'ready' &&
      !labStreamFailed.value,
    ),
)
const eligibleStudents = computed(() =>
  students.value.filter((student) => student.template_status !== 'enrolled'),
)
const progressPercent = computed<number | null>(() => {
  if (capturePhase.value === 'countdown') return 5
  if (capturePhase.value === 'capturing') return Math.round((captureIndex.value / 4) * 70) + 10
  if (capturePhase.value === 'confirming') return 100
  if (capturePhase.value === 'processing') return null
  return 0
})

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details?.map((item) => `${item.field}: ${item.message}`)
    return details?.length ? details.join(' · ') : error.message
  }
  if (error instanceof DOMException && error.name === 'NotAllowedError') {
    return 'Akses kamera belum diizinkan. Izinkan kamera pada browser lalu coba lagi.'
  }
  return 'Permintaan tidak dapat diproses. Periksa kamera dan koneksi, lalu coba lagi.'
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function stopCamera(): void {
  stream.value?.getTracks().forEach((track) => track.stop())
  stream.value = null
  if (videoElement.value) videoElement.value.srcObject = null
}

function handleLabStreamLoad(): void {
  if (streamRetryTimer) window.clearTimeout(streamRetryTimer)
  streamRetryTimer = undefined
  streamRetryAttempts = 0
  labStreamFailed.value = false
  localPreviewError.value = null
}

async function startDevicePreview(): Promise<void> {
  if (cameraSource.value !== 'device' || !selectedStudent.value || stream.value) return
  if (!window.isSecureContext) {
    devicePreviewError.value = 'Kamera browser hanya tersedia lewat localhost atau HTTPS.'
    return
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    devicePreviewError.value = 'Browser ini tidak dapat membuka kamera. Periksa izin dan perangkat.'
    return
  }
  const currentFlow = ++flowVersion
  devicePreviewError.value = null
  try {
    const cameraStream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: 'user',
        width: { ideal: 640 },
        height: { ideal: 480 },
        aspectRatio: { ideal: 4 / 3 },
      },
    })
    if (currentFlow !== flowVersion) {
      cameraStream.getTracks().forEach((track) => track.stop())
      return
    }
    stream.value = cameraStream
    if (!videoElement.value) throw new Error('Preview kamera tidak tersedia.')
    videoElement.value.srcObject = stream.value
    await videoElement.value.play()
  } catch (error) {
    if (currentFlow !== flowVersion) return
    stopCamera()
    if (error instanceof DOMException && error.name === 'NotAllowedError') {
      devicePreviewError.value =
        'Akses kamera belum diizinkan. Izinkan kamera pada browser lalu muat ulang preview.'
    } else if (error instanceof DOMException && error.name === 'NotReadableError') {
      devicePreviewError.value =
        'Kamera sedang dipakai aplikasi lain. Jika ini kamera lab, pilih Kamera lab via AI_EDGE.'
    } else {
      devicePreviewError.value = 'Preview kamera tidak dapat dibuka. Periksa kamera lalu coba lagi.'
    }
  }
}

async function openLocalPreviewSession(): Promise<string> {
  if (!previewBaseUrl) {
    throw new Error('Preview AI_EDGE hanya tersedia di komputer lab yang menjalankan agent.')
  }
  const accessToken = auth.getValidAccessToken()
  if (!accessToken)
    throw new Error('Sesi login berakhir. Masuk kembali lalu buka pendaftaran wajah.')
  const response = await fetchWithPreviewTimeout(`${previewBaseUrl}/v1/session`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: 'no-store',
  })
  if (!response.ok) {
    if (response.status === 403) {
      throw new Error('Preview AI_EDGE hanya tersedia untuk Admin atau Laboran.')
    }
    throw new Error(
      'Agent AI_EDGE tidak merespons. Pastikan service kamera berjalan di komputer ini.',
    )
  }
  const result = (await response.json()) as { preview_token?: unknown }
  if (typeof result.preview_token !== 'string') {
    throw new Error('Agent AI_EDGE mengirim token preview yang tidak valid.')
  }
  return result.preview_token
}

async function closeLocalPreviewSession(token: string): Promise<void> {
  if (!previewBaseUrl) return
  await fetch(`${previewBaseUrl}/v1/session`, {
    method: 'DELETE',
    headers: { 'X-Presensi-Preview-Token': token },
    cache: 'no-store',
    keepalive: true,
  }).catch(() => undefined)
}

function stopLocalPreview(): void {
  previewGeneration += 1
  isOpeningLocalPreview.value = false
  if (statusTimer) window.clearTimeout(statusTimer)
  if (streamRetryTimer) window.clearTimeout(streamRetryTimer)
  statusTimer = undefined
  streamRetryTimer = undefined
  streamRetryAttempts = 0
  const token = localPreviewToken.value
  localPreviewToken.value = null
  cameraObservation.value = null
  localPreviewRecognitionState.value = null
  localPreviewError.value = null
  if (token) void closeLocalPreviewSession(token)
}

async function fetchLocalPreview(path: '/v1/status' | '/v1/frame.jpg'): Promise<Response> {
  if (!previewBaseUrl || !localPreviewToken.value) {
    throw new Error('Sesi preview AI_EDGE belum aktif.')
  }
  const requestToken = localPreviewToken.value
  let response = await fetchWithPreviewTimeout(`${previewBaseUrl}${path}`, {
    headers: { 'X-Presensi-Preview-Token': requestToken },
    cache: 'no-store',
  })
  if (
    response.status === 401 &&
    localPreviewToken.value === requestToken &&
    cameraSource.value === 'lab'
  ) {
    const nextToken = await openLocalPreviewSession()
    if (localPreviewToken.value !== requestToken || cameraSource.value !== 'lab') {
      void closeLocalPreviewSession(nextToken)
      throw new Error('Sesi preview AI_EDGE telah ditutup.')
    }
    localPreviewToken.value = nextToken
    void closeLocalPreviewSession(requestToken)
    labStreamKey.value += 1
    labStreamFailed.value = false
    localPreviewError.value = null
    response = await fetchWithPreviewTimeout(`${previewBaseUrl}${path}`, {
      headers: { 'X-Presensi-Preview-Token': localPreviewToken.value },
      cache: 'no-store',
    })
  }
  return response
}

async function pollLocalPreviewStatus(generation: number): Promise<void> {
  if (generation !== previewGeneration || cameraSource.value !== 'lab' || !selectedStudent.value) {
    return
  }
  try {
    const response = await fetchLocalPreview('/v1/status')
    if (!response.ok) throw new Error('Status kamera AI_EDGE belum tersedia.')
    const status = (await response.json()) as LocalPreviewStatus
    if (generation === previewGeneration) {
      localPreviewRecognitionState.value = status.recognition_state ?? null
      cameraObservation.value = status.camera_open ? (status.camera_observation ?? null) : null
      localPreviewError.value = status.camera_open
        ? null
        : status.recognition_state === 'camera_disabled'
          ? 'Kamera dijeda dari halaman Perangkat. Lanjutkan kamera untuk menampilkan preview.'
          : 'Agent belum membuka kamera. Periksa kamera dan service AI_EDGE.'
    }
  } catch (error) {
    if (generation === previewGeneration) {
      localPreviewRecognitionState.value = null
      cameraObservation.value = null
      localPreviewError.value =
        error instanceof Error ? error.message : 'Status deteksi AI_EDGE tidak tersedia.'
    }
  } finally {
    if (generation === previewGeneration && cameraSource.value === 'lab') {
      statusTimer = window.setTimeout(() => void pollLocalPreviewStatus(generation), 500)
    }
  }
}

async function startLocalPreview(): Promise<void> {
  if (
    cameraSource.value !== 'lab' ||
    !selectedStudent.value ||
    localPreviewToken.value ||
    isOpeningLocalPreview.value
  ) {
    return
  }
  if (!previewBaseUrl) {
    localPreviewError.value = 'Pilih kamera perangkat ini atau buka aplikasi di komputer AI_EDGE.'
    return
  }
  const generation = ++previewGeneration
  isOpeningLocalPreview.value = true
  localPreviewError.value = null
  labStreamFailed.value = false
  try {
    const token = await openLocalPreviewSession()
    if (generation !== previewGeneration || cameraSource.value !== 'lab') {
      void closeLocalPreviewSession(token)
      return
    }
    localPreviewToken.value = token
    labStreamKey.value += 1
    streamRetryAttempts = 0
    void pollLocalPreviewStatus(generation)
  } catch (error) {
    if (generation === previewGeneration) {
      localPreviewError.value =
        error instanceof Error ? error.message : 'Preview AI_EDGE tidak dapat dibuka.'
    }
  } finally {
    if (generation === previewGeneration) isOpeningLocalPreview.value = false
  }
}

function scheduleLabStreamRetry(): void {
  if (streamRetryTimer) return
  streamRetryAttempts += 1
  const exponent = Math.min(streamRetryAttempts - 1, 4)
  const delay = Math.min(500 * 2 ** exponent, MAX_STREAM_RETRY_DELAY_MS)
  streamRetryTimer = window.setTimeout(() => {
    streamRetryTimer = undefined
    void retryLabStream(true)
  }, delay)
}

async function retryLabStream(automatic = false): Promise<void> {
  if (streamRetryTimer) window.clearTimeout(streamRetryTimer)
  streamRetryTimer = undefined
  if (!automatic) streamRetryAttempts = 0
  if (cameraSource.value !== 'lab' || isOpeningLocalPreview.value) return
  if (!localPreviewToken.value) {
    void startLocalPreview()
    return
  }

  const generation = previewGeneration
  const previousToken = localPreviewToken.value
  isOpeningLocalPreview.value = true
  localPreviewError.value = null
  try {
    const nextToken = await openLocalPreviewSession()
    if (
      generation !== previewGeneration ||
      cameraSource.value !== 'lab' ||
      localPreviewToken.value !== previousToken
    ) {
      void closeLocalPreviewSession(nextToken)
      return
    }
    localPreviewToken.value = nextToken
    labStreamKey.value += 1
    labStreamFailed.value = false
    void closeLocalPreviewSession(previousToken)
  } catch (error) {
    if (generation === previewGeneration && cameraSource.value === 'lab') {
      localPreviewError.value =
        error instanceof Error ? error.message : 'Preview AI_EDGE tidak dapat dibuka.'
      labStreamFailed.value = true
      if (automatic) scheduleLabStreamRetry()
    }
  } finally {
    if (generation === previewGeneration) isOpeningLocalPreview.value = false
  }
}

function handleLabStreamError(): void {
  labStreamFailed.value = true
  cameraObservation.value = null
  scheduleLabStreamRetry()
}

async function loadClasses(): Promise<void> {
  isLoading.value = true
  pageError.value = null
  try {
    const result = await listClasses({ limit: 100, offset: 0, is_active: true })
    classes.value = result.items
    selectedClassId.value = result.items[0]?.id ?? ''
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

async function loadRoster(classId: string): Promise<void> {
  flowVersion += 1
  stopCamera()
  stopLocalPreview()
  isStarting.value = false
  students.value = []
  activeTemplates.value = []
  selectedStudentId.value = ''
  capturePhase.value = 'ready'
  captureResult.value = null
  identityConfirmed.value = false
  pageMessage.value = null
  pageError.value = null
  if (!classId) return

  isLoading.value = true
  try {
    students.value = await listClassEnrollmentStatus(classId)
    selectedStudentId.value = eligibleStudents.value[0]?.id ?? ''
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isLoading.value = false
  }
  if (cameraSource.value === 'device') void startDevicePreview()
  else if (selectedStudent.value) void startLocalPreview()
}

onMounted(() => {
  void loadClasses()
})

watch(cameraSource, (source) => {
  flowVersion += 1
  stopCamera()
  labStreamFailed.value = false
  if (source === 'device') {
    stopLocalPreview()
    void startDevicePreview()
  } else {
    void startLocalPreview()
  }
})

watch(selectedClassId, (classId, previousClassId) => {
  if (classId && classId !== previousClassId) void loadRoster(classId)
})

onBeforeUnmount(() => {
  flowVersion += 1
  stopCamera()
  stopLocalPreview()
})

async function captureVideoFrame(): Promise<Blob> {
  if (cameraSource.value === 'lab') {
    const response = await fetchLocalPreview('/v1/frame.jpg')
    if (!response.ok) throw new Error('Frame kamera AI_EDGE belum siap.')
    return response.blob()
  }

  const canvas = document.createElement('canvas')
  const video = videoElement.value
  if (!video || video.videoWidth < 1 || video.videoHeight < 1) {
    throw new Error('Kamera belum siap.')
  }
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Kamera belum siap.')
  context.drawImage(video, 0, 0, canvas.width, canvas.height)
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (image) => (image ? resolve(image) : reject(new Error('Capture kamera gagal.'))),
      'image/jpeg',
      0.88,
    )
  })
}

async function startEnrollment(): Promise<void> {
  if (!selectedStudent.value || isStarting.value) return
  pageError.value = null
  pageMessage.value = null
  captureResult.value = null
  identityConfirmed.value = false
  captureIndex.value = 0
  isStarting.value = true
  const currentFlow = ++flowVersion

  try {
    if (cameraSource.value === 'lab') {
      // Single-owner: stream dan frame capture berasal dari agent yang sama
      // dengan deteksi YuNet; browser tidak membuka webcam kedua.
      stopCamera()
      if (!localPreviewToken.value || labStreamFailed.value) {
        throw new Error(localPreviewError.value ?? 'Stream kamera lab belum tersedia.')
      }
      if (cameraObservation.value?.state !== 'ready') {
        throw new Error(
          cameraObservation.value?.message ??
            'Tunggu sampai deteksi AI_EDGE menemukan satu wajah siap.',
        )
      }
    } else {
      if (!stream.value) await startDevicePreview()
      if (currentFlow !== flowVersion) return
      if (!stream.value || !videoElement.value) {
        throw new Error(devicePreviewError.value ?? 'Preview kamera belum siap. Tunggu sebentar.')
      }
    }
    capturePhase.value = 'countdown'
    for (let remaining = 3; remaining > 0; remaining -= 1) {
      countdownValue.value = remaining
      await delay(1000)
      if (currentFlow !== flowVersion) return
    }

    capturePhase.value = 'capturing'
    const captures: Blob[] = []
    for (let index = 0; index < 4; index += 1) {
      captureIndex.value = index + 1
      // Show each prompt before its frame is captured so the student can
      // follow the small pose change without guessing when the shutter fires.
      await delay(index === 0 ? 600 : 1000)
      if (currentFlow !== flowVersion) return
      captures.push(await captureVideoFrame())
      if (currentFlow !== flowVersion) return
    }

    capturePhase.value = 'processing'
    // Frames are secured as Blobs: release the camera while the operator
    // reviews the result, instead of streaming through the confirm step.
    stopCamera()
    const submittedStudentId = selectedStudent.value.id
    captureResult.value = await submitEnrollmentCaptures(submittedStudentId, captures)
    if (currentFlow !== flowVersion) return
    if (captureResult.value.student_id !== submittedStudentId) {
      throw new Error('Hasil pendaftaran tidak sesuai dengan siswa yang dipilih.')
    }
    capturePhase.value = 'confirming'
  } catch (error) {
    if (currentFlow === flowVersion) {
      pageError.value = formatError(error)
      capturePhase.value = 'ready'
      stopCamera()
    }
  } finally {
    if (currentFlow === flowVersion) isStarting.value = false
  }
}

function cancelCapture(): void {
  flowVersion += 1
  isStarting.value = false
  capturePhase.value = 'ready'
  captureResult.value = null
  identityConfirmed.value = false
  captureIndex.value = 0
  stopCamera()
  if (cameraSource.value === 'device') void startDevicePreview()
  else void startLocalPreview()
}

function selectStudent(student: EnrollmentStudentStatus): void {
  cancelCapture()
  pageMessage.value = null
  pageError.value = null
  selectedStudentId.value = student.id
  activeTemplates.value = []
  if (student.template_status === 'enrolled') void loadActiveTemplates(student.id)
}

async function loadActiveTemplates(studentId: string): Promise<void> {
  isLoadingTemplates.value = true
  try {
    const templates = await listFaceTemplates(studentId)
    if (selectedStudentId.value === studentId) activeTemplates.value = templates
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isLoadingTemplates.value = false
  }
}

async function revokeSelectedTemplates(): Promise<void> {
  const templates = activeTemplates.value
  const student = selectedStudent.value
  if (templates.length === 0 || !student || isRevoking.value) return
  isRevoking.value = true
  pageError.value = null
  let alreadyRevokedBatches = 0
  try {
    const templateByBatch = new Map<string, FaceTemplate>()
    for (const template of templates) {
      if (!templateByBatch.has(template.enrollment_batch_id)) {
        templateByBatch.set(template.enrollment_batch_id, template)
      }
    }
    for (const template of templateByBatch.values()) {
      try {
        await revokeFaceTemplate(template.id)
      } catch (error) {
        if (!(error instanceof ApiError) || error.code !== 'face_template_already_revoked') {
          throw error
        }
        alreadyRevokedBatches += 1
      }
    }

    const [updatedRoster, refreshedTemplates] = await Promise.all([
      listClassEnrollmentStatus(selectedClassId.value),
      listFaceTemplates(student.id),
    ])
    students.value = updatedRoster
    const updatedStudent = updatedRoster.find((item) => item.id === student.id)
    selectedStudentId.value = updatedStudent?.id ?? ''
    activeTemplates.value = refreshedTemplates
    if (refreshedTemplates.length === 0) {
      pageMessage.value =
        alreadyRevokedBatches === templateByBatch.size
          ? `${student.full_name}: acuan wajah sudah dicabut sebelumnya. Status diperbarui.`
          : `${student.full_name}: semua acuan wajah aktif sudah dicabut. Siswa dapat didaftarkan ulang.`
    } else {
      pageMessage.value =
        `${student.full_name}: status disegarkan. ` +
        `${refreshedTemplates.length} acuan wajah aktif masih tersisa.`
    }
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isRevoking.value = false
  }
}

const selectedClassLabel = computed(
  () => classes.value.find((item) => item.id === selectedClassId.value)?.code ?? '',
)
const revokeReasonLength = computed(() => revokeReason.value.trim().length)
const revokeReasonValid = computed(
  () => revokeReasonLength.value >= 10 && revokeReasonLength.value <= 120,
)

function openRevokeConfirm(): void {
  revokeReason.value = ''
  showRevokeConfirm.value = true
}

async function confirmRevoke(): Promise<void> {
  if (!revokeReasonValid.value || isRevoking.value) return
  await revokeSelectedTemplates()
  if (!pageError.value) {
    showRevokeConfirm.value = false
    revokeReason.value = ''
  }
}

function confirmIdentityAndContinue(): void {
  if (
    !captureResult.value ||
    !selectedStudent.value ||
    (confirmationRequired.value && !identityConfirmed.value)
  )
    return
  const currentIndex = students.value.findIndex((student) => student.id === selectedStudentId.value)
  students.value = students.value.map((student) =>
    student.id === selectedStudentId.value
      ? {
          ...student,
          template_status: captureResult.value?.template_status ?? student.template_status,
        }
      : student,
  )
  capturePhase.value = 'ready'
  captureResult.value = null
  identityConfirmed.value = false
  stopCamera()

  const nextStudent =
    students.value
      .slice(currentIndex + 1)
      .find((student) => student.template_status !== 'enrolled') ?? null
  if (nextStudent) {
    selectedStudentId.value = nextStudent.id
    if (cameraSource.value === 'device') void startDevicePreview()
    pageMessage.value = `${nextStudent.full_name} dipilih. Pastikan siswa yang benar sebelum memulai.`
    return
  }
  selectedStudentId.value = ''
  stopLocalPreview()
  stopCamera()
  capturePhase.value = 'complete'
  pageMessage.value = 'Semua siswa yang dipilih untuk kelas ini sudah diproses.'
}

function statusLabel(status: EnrollmentStudentStatus['template_status']): string {
  if (status === 'enrolled') return 'Terdaftar'
  if (status === 'needs_reenrollment') return 'Perlu daftar ulang'
  return 'Belum terdaftar'
}
</script>

<template>
  <div class="st-page" aria-label="Pendaftaran wajah siswa">
    <UiPageHeader
      eyebrow="Modul biometrik siswa"
      title="Pendaftaran Wajah Biometrik"
      description="Manajemen acuan biometrik siswa yang bersumber dari Data Master. Daftarkan siswa satu per satu; pastikan nama di layar sesuai dengan siswa di depan kamera."
    >
      <template #actions>
        <UiButton variant="secondary" type="button" @click="loadClasses">Sinkron Master</UiButton>
      </template>
    </UiPageHeader>
    <p v-if="pageError" class="st-alert st-alert--error" role="alert">{{ pageError }}</p>
    <p v-if="pageMessage" class="st-alert st-alert--success" role="status">{{ pageMessage }}</p>

    <div class="st-kpi">
      <UiStat
        label="Siap & terverifikasi"
        :value="`${enrolledCount} siswa`"
        caption="Koleksi valid"
        tone="success"
      />
      <UiStat
        label="Belum terdaftar"
        :value="`${pendingCount} siswa`"
        caption="Perlu sesi pemotretan"
        tone="warning"
      />
    </div>

    <UiCard
      title="Pilih kelas dan siswa"
      subtitle="1. Data master siswa = identitas & keanggotaan kelas. 2. Pendaftaran wajah = data acuan wajah untuk presensi."
    >
      <template #header>
        <label class="st-field" style="min-width: 240px"
          ><span>Kelas</span>
          <UiSelect v-model="selectedClassId" aria-label="Pilih kelas" :disabled="isLoading">
            <option value="" disabled>Pilih kelas aktif</option>
            <option v-for="schoolClass in classes" :key="schoolClass.id" :value="schoolClass.id">
              {{ schoolClass.name }} · {{ schoolClass.academic_year }}
            </option>
          </UiSelect>
        </label>
      </template>
      <UiSearchInput
        v-model="rosterSearch"
        placeholder="Cari NIS atau Nama Siswa…"
        aria-label="Cari siswa"
      />
      <div class="st-tablewrap" style="margin-top: 10px">
        <table class="st-table">
          <thead>
            <tr>
              <th>Nomor siswa</th>
              <th>Nama lengkap</th>
              <th>Status acuan</th>
              <th><span class="st-table__actions">Tindakan</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="isLoading">
              <td colspan="4"><UiEmptyState title="Memuat kelas dan siswa…" /></td>
            </tr>
            <tr v-else-if="!selectedClassId">
              <td colspan="4"><UiEmptyState title="Belum ada kelas aktif untuk dipilih." /></td>
            </tr>
            <tr v-else-if="filteredStudents.length === 0">
              <td colspan="4"><UiEmptyState title="Tidak ada siswa yang cocok." /></td>
            </tr>
            <tr
              v-for="student in filteredStudents"
              v-else
              :key="student.id"
              :data-testid="`enrollment-student-${student.id}`"
              :class="{ 'st-list__item--active': student.id === selectedStudentId }"
            >
              <td class="st-table__mono">{{ student.student_number }}</td>
              <td>
                <span class="st-table__who"
                  ><UiAvatar :name="student.full_name" />{{ student.full_name }}</span
                >
              </td>
              <td>
                <UiBadge
                  :tone="
                    student.template_status === 'enrolled'
                      ? 'present'
                      : student.template_status === 'needs_reenrollment'
                        ? 'late'
                        : 'neutral'
                  "
                >
                  {{ statusLabel(student.template_status) }}
                </UiBadge>
              </td>
              <td class="st-table__actions">
                <button
                  class="st-rowbtn"
                  type="button"
                  :disabled="isStarting"
                  @click="selectStudent(student)"
                >
                  {{
                    student.id === selectedStudentId
                      ? 'Dipilih ✓'
                      : student.template_status === 'enrolled'
                        ? 'Ambil Ulang'
                        : 'Mulai Pendaftaran'
                  }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </UiCard>

    <UiCard
      v-if="selectedStudent || capturePhase === 'complete'"
      title="Capture kamera"
      :subtitle="
        selectedStudent
          ? `${selectedStudent.full_name} · ${selectedStudent.student_number}`
          : 'Pendaftaran kelas selesai'
      "
    >
      <template #header>
        <UiButton
          v-if="capturePhase === 'countdown' || capturePhase === 'capturing'"
          variant="secondary"
          type="button"
          @click="cancelCapture"
          >Batalkan</UiButton
        >
      </template>
      <div v-if="selectedStudent" class="enrollment-view__capture-layout">
        <div class="enrollment-view__source-toggle" role="radiogroup" aria-label="Sumber kamera">
          <label>
            <input
              v-model="cameraSource"
              type="radio"
              value="device"
              name="camera-source"
              data-testid="enrollment-source-device"
            />
            Kamera perangkat ini
          </label>
          <label>
            <input
              v-model="cameraSource"
              type="radio"
              value="lab"
              name="camera-source"
              :disabled="!previewBaseUrl"
              data-testid="enrollment-source-lab"
            />
            Kamera lab via AI_EDGE · deteksi aktif
          </label>
        </div>
        <div class="enrollment-view__camera-frame">
          <video
            v-if="cameraSource === 'device'"
            ref="videoElement"
            class="enrollment-view__camera enrollment-view__camera--mirror"
            autoplay
            muted
            playsinline
            aria-label="Preview kamera siswa"
            data-testid="enrollment-camera"
          />
          <FaceOverlay
            v-if="cameraSource === 'device' && deviceFaceMesh.faces.value.length"
            :faces="deviceFaceMesh.faces.value"
            :image-width="deviceFaceMesh.frameSize.value.width"
            :image-height="deviceFaceMesh.frameSize.value.height"
            fit="cover"
            mirrored
            class="enrollment-view__face-overlay"
            data-testid="enrollment-device-mesh"
          />
          <img
            v-else-if="labStreamSrc && !labStreamFailed && !localPreviewError"
            :key="labStreamKey"
            ref="labImageElement"
            :src="labStreamSrc"
            crossorigin="anonymous"
            class="enrollment-view__camera enrollment-view__camera--mirror"
            alt="Stream kamera lab dari agent"
            data-testid="enrollment-lab-stream"
            @error="handleLabStreamError"
            @load="handleLabStreamLoad"
          />
          <FaceOverlay
            v-if="cameraSource === 'lab' && labFaceMesh.faces.value.length"
            :faces="labFaceOverlays"
            :image-width="labFaceMesh.frameSize.value.width"
            :image-height="labFaceMesh.frameSize.value.height"
            fit="cover"
            mirrored
            class="enrollment-view__face-overlay"
            data-testid="enrollment-lab-mesh"
          />
          <div
            v-if="
              (cameraSource === 'device' && !stream) ||
              (cameraSource === 'lab' && (!labStreamSrc || labStreamFailed || localPreviewError))
            "
            class="enrollment-view__camera-placeholder"
          >
            <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
              <rect x="5" y="11" width="28" height="26" rx="4" />
              <path d="m33 19 10-6v22l-10-6" />
              <circle cx="19" cy="24" r="6" />
            </svg>
            <span v-if="cameraSource === 'device' && devicePreviewError">{{
              devicePreviewError
            }}</span>
            <span v-else-if="cameraSource === 'device'">Membuka preview kamera…</span>
            <span v-else-if="localPreviewError">{{ localPreviewError }}</span>
            <span v-else-if="isOpeningLocalPreview">Menghubungkan ke kamera AI_EDGE…</span>
            <span v-else-if="streamRetryTimer" data-testid="enrollment-lab-retry-status">
              Koneksi stream terputus; sistem mencoba ulang otomatis.
            </span>
            <span v-else>Stream kamera lab belum tersedia.</span>
            <UiButton
              v-if="cameraSource === 'lab'"
              variant="secondary"
              size="sm"
              type="button"
              :disabled="isOpeningLocalPreview"
              data-testid="retry-lab-stream"
              @click="retryLabStream"
            >
              Coba lagi
            </UiButton>
            <UiButton
              v-else-if="devicePreviewError"
              variant="secondary"
              size="sm"
              type="button"
              @click="startDevicePreview"
            >
              Muat ulang preview
            </UiButton>
          </div>
          <div
            v-if="cameraSource === 'lab'"
            class="enrollment-view__face-guidance"
            :class="`is-${cameraObservation?.state ?? 'pending'}`"
            role="status"
            data-testid="enrollment-face-guidance"
          >
            <span class="enrollment-view__face-guidance-dot" aria-hidden="true" />
            <span>
              <strong>{{ cameraObservationLabel }}</strong>
              <small>{{ cameraObservationMessage }}</small>
              <small v-if="!localPreviewError" data-testid="enrollment-lab-mesh-status">{{
                labMeshStatus
              }}</small>
            </span>
          </div>
          <div
            v-else
            class="enrollment-view__face-guidance"
            :class="`is-${deviceCameraGuidanceTone}`"
            role="status"
            data-testid="enrollment-device-guidance"
          >
            <span class="enrollment-view__face-guidance-dot" aria-hidden="true" />
            <span>
              <strong>{{ deviceCameraGuidanceLabel }}</strong>
              <small>{{ deviceCameraGuidanceMessage }}</small>
            </span>
          </div>
          <span
            v-if="capturePhase === 'countdown'"
            class="enrollment-view__countdown"
            aria-live="polite"
            >{{ countdownValue }}</span
          >
        </div>

        <div class="enrollment-view__capture-info">
          <p v-if="capturePhase === 'ready'" class="enrollment-view__instruction">
            Pastikan wajah dan nama siswa sesuai, terlihat jelas, dan cukup terang sebelum
            melanjutkan.
          </p>
          <p
            v-else-if="capturePhase === 'countdown'"
            class="enrollment-view__instruction"
            aria-live="polite"
          >
            Siap-siap… capture dimulai dalam {{ countdownValue }} detik.
          </p>
          <p
            v-else-if="capturePhase === 'capturing'"
            class="enrollment-view__instruction"
            aria-live="polite"
          >
            Pengambilan {{ captureIndex }} dari 4.
          </p>
          <p
            v-if="capturePhase === 'capturing' && capturePoseStep"
            class="enrollment-view__capture-pose"
            aria-live="polite"
            data-testid="enrollment-capture-pose"
          >
            <strong>{{ capturePoseStep.label }}</strong>
            <span>{{ capturePoseStep.guidance }}</span>
          </p>
          <div
            v-else-if="capturePhase === 'processing'"
            class="enrollment-view__processing"
            role="status"
            aria-live="polite"
            aria-busy="true"
            data-testid="enrollment-processing-status"
          >
            <span class="enrollment-view__processing-spinner" aria-hidden="true" />
            <div>
              <strong>Mengirim dan memeriksa 4 frame</strong>
              <p>
                Core API sedang memeriksa wajah dan kualitas gambar, lalu menyiapkan acuan. Tunggu
                sebentar; hasil akan muncul di sini setelah proses selesai.
              </p>
            </div>
          </div>
          <template v-else-if="capturePhase === 'confirming' && captureResult">
            <p class="enrollment-view__instruction" role="status">
              {{ captureResult.accepted_frames }} dari 4 frame diterima,
              {{ captureResult.rejected_frames }} tidak digunakan.
              {{ captureResult.template_count }}
              acuan wajah tersimpan. Pastikan siswa pada preview cocok dengan identitas berikut.
            </p>
            <label v-if="confirmationRequired" class="enrollment-view__confirm">
              <input v-model="identityConfirmed" type="checkbox" />
              <span
                >Saya memastikan siswa di kamera adalah {{ selectedStudent.full_name }} ({{
                  selectedStudent.student_number
                }}).</span
              >
            </label>
            <p v-if="duplicateWarnings.length" class="st-alert st-alert--error" role="status">
              Ada kemungkinan wajah mirip dengan
              {{ duplicateWarnings.map((w) => `${w.full_name} (${w.student_number})`).join(', ') }}.
              Periksa kembali identitas dan lanjutkan hanya setelah operator memastikan siswa yang
              benar.
            </p>
            <UiButton
              variant="primary"
              type="button"
              data-testid="confirm-enrollment-identity"
              :disabled="confirmationRequired && !identityConfirmed"
              @click="confirmIdentityAndContinue"
            >
              Konfirmasi identitas & lanjut
            </UiButton>
          </template>
          <div v-else-if="capturePhase === 'complete'" class="enrollment-view__instruction">
            Semua siswa yang dapat diproses sudah selesai.
          </div>
          <div
            v-if="
              capturePhase === 'countdown' ||
              capturePhase === 'capturing' ||
              capturePhase === 'processing'
            "
            class="enrollment-view__progress"
            role="progressbar"
            aria-label="Kemajuan pendaftaran"
            :aria-valuenow="progressPercent ?? undefined"
            :aria-valuetext="
              progressPercent === null
                ? 'Mengirim dan memeriksa empat frame di Core API'
                : `${progressPercent}%`
            "
            :aria-busy="capturePhase === 'processing'"
            aria-valuemin="0"
            aria-valuemax="100"
          >
            <span
              :class="{ 'enrollment-view__progress--indeterminate': progressPercent === null }"
              :style="progressPercent === null ? undefined : { width: `${progressPercent}%` }"
            />
          </div>
          <p v-if="capturePhase === 'capturing'" class="st-table__muted">
            {{ captureIndex }} / 4 capture
          </p>
          <p
            v-if="capturePhase === 'confirming' && captureResult"
            class="enrollment-view__result-status"
            role="status"
          >
            Status: {{ statusLabel(captureResult.template_status) }}
          </p>
          <div
            v-if="selectedStudent.template_status === 'enrolled' && capturePhase === 'ready'"
            class="enrollment-view__revoke"
          >
            <p class="st-table__muted">
              Template aktif: {{ isLoadingTemplates ? 'memuat…' : activeTemplates.length }}
            </p>
            <UiButton
              variant="secondary"
              type="button"
              data-testid="revoke-enrollment-template"
              :disabled="isLoadingTemplates || isRevoking || activeTemplates.length === 0"
              @click="openRevokeConfirm"
            >
              {{ isRevoking ? 'Mencabut…' : 'Cabut semua template untuk daftar ulang' }}
            </UiButton>
            <UiModal
              v-if="showRevokeConfirm"
              title="Cabut Acuan Wajah Siswa?"
              @close="showRevokeConfirm = false"
            >
              <p class="st-modal__eyebrow">Konfirmasi kritis</p>
              <p v-if="selectedStudent" class="st-identityline" data-testid="revoke-identity">
                <UiAvatar :name="selectedStudent.full_name" />
                <span>
                  <strong>{{ selectedStudent.full_name }}</strong
                  ><br />
                  <span class="st-table__muted"
                    >NIS: {{ selectedStudent.student_number
                    }}<span v-if="selectedClassLabel"> · {{ selectedClassLabel }}</span></span
                  >
                </span>
              </p>
              <p class="st-alert st-alert--error" role="note">
                <strong>Peringatan dampak:</strong>
                Pencabutan menghapus acuan wajah aktif siswa ini. Siswa tidak dapat melakukan
                presensi mandiri sampai acuan wajah didaftarkan kembali.
              </p>
              <div class="st-fieldhead">
                <label for="revoke-reason">Alasan pencabutan *</label>
                <span class="st-charcount" aria-live="polite"
                  >{{ revokeReasonLength }}/120 karakter</span
                >
              </div>
              <UiTextarea
                id="revoke-reason"
                v-model="revokeReason"
                data-testid="revoke-reason-input"
                maxlength="120"
                rows="3"
                placeholder="Contoh: Perubahan bentuk fisik signifikan / kualitas tangkapan lama menyebabkan galat pengenalan berulang…"
                :invalid="revokeReasonLength > 0 && !revokeReasonValid"
              />
              <p class="st-table__muted">Alasan wajib diisi (minimal 10 karakter).</p>
              <template #footer>
                <UiButton variant="secondary" type="button" @click="showRevokeConfirm = false"
                  >Batal</UiButton
                >
                <UiButton
                  variant="danger"
                  type="button"
                  data-testid="confirm-revoke-template"
                  :disabled="!revokeReasonValid || isRevoking"
                  @click="confirmRevoke"
                >
                  <span class="st-material-icon" aria-hidden="true">person_remove</span>
                  {{ isRevoking ? 'Mencabut…' : 'Ya, cabut acuan' }}
                </UiButton>
              </template>
            </UiModal>
          </div>
          <UiButton
            v-if="
              capturePhase === 'ready' &&
              selectedStudent &&
              selectedStudent.template_status !== 'enrolled'
            "
            variant="primary"
            type="button"
            data-testid="start-enrollment-capture"
            :disabled="isStarting || !canStartAgentCapture"
            :title="
              cameraSource === 'lab' && !canStartAgentCapture ? cameraObservationMessage : undefined
            "
            @click="startEnrollment"
          >
            {{
              selectedStudent.template_status === 'needs_reenrollment'
                ? 'Daftar ulang siswa'
                : 'Mulai pendaftaran'
            }}
          </UiButton>
        </div>
      </div>
    </UiCard>
  </div>
</template>

<style scoped>
.enrollment-view__camera {
  transform: none;
}

.enrollment-view__camera--mirror {
  transform: scaleX(-1);
}

.enrollment-view__face-overlay {
  z-index: 1;
}

.enrollment-view__face-guidance {
  position: absolute;
  right: 12px;
  bottom: 12px;
  left: 12px;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid rgb(255 255 255 / 16%);
  border-radius: 12px;
  color: #f7fbff;
  background: rgb(12 21 31 / 84%);
  box-shadow: 0 8px 24px rgb(0 0 0 / 18%);
  backdrop-filter: blur(8px);
  font-size: 0.78rem;
  line-height: 1.4;
  pointer-events: none;
}

.enrollment-view__face-guidance > span:last-child {
  display: grid;
  gap: 2px;
}

.enrollment-view__face-guidance small {
  color: #d0d9e4;
}

.enrollment-view__face-guidance-dot {
  width: 9px;
  height: 9px;
  flex: 0 0 9px;
  border-radius: 50%;
  background: #91a0b2;
  box-shadow: 0 0 0 4px rgb(145 160 178 / 16%);
}

.enrollment-view__face-guidance.is-ready .enrollment-view__face-guidance-dot {
  background: #51e2ab;
  box-shadow: 0 0 0 4px rgb(81 226 171 / 18%);
}

.enrollment-view__face-guidance.is-adjust .enrollment-view__face-guidance-dot,
.enrollment-view__face-guidance.is-multiple_faces .enrollment-view__face-guidance-dot {
  background: #ffc66d;
  box-shadow: 0 0 0 4px rgb(255 198 109 / 18%);
}

.enrollment-view__face-guidance.is-unavailable .enrollment-view__face-guidance-dot {
  background: #ff807a;
  box-shadow: 0 0 0 4px rgb(255 128 122 / 18%);
}
</style>
