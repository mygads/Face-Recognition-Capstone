import { onBeforeUnmount, onMounted, ref, shallowRef, watch, type Ref } from 'vue'
import wasmLoaderPath from '@mediapipe/tasks-vision/vision_wasm_module_internal.js?url'
import wasmBinaryPath from '@mediapipe/tasks-vision/vision_wasm_module_internal.wasm?url'
import type { OverlayFace } from '../components/FaceOverlay.vue'
import { FACE_MESH_TARGET_FPS, getFaceMeshInputSize } from '../utils/faceMeshPerformance'

type WorkerResponse =
  | { type: 'ready'; delegate: 'GPU' | 'CPU' }
  | {
      type: 'result'
      faces: OverlayFace[]
      width: number
      height: number
      inferenceMs: number
      delegate: 'GPU' | 'CPU'
    }
  | { type: 'error'; message: string }

export type LandmarkSource = HTMLImageElement | HTMLVideoElement

export function getSourceFrame(source: LandmarkSource): {
  ready: boolean
  width: number
  height: number
} {
  if ('videoWidth' in source) {
    return {
      ready: source.readyState >= 2,
      width: source.videoWidth,
      height: source.videoHeight,
    }
  }
  // MJPEG <img> elements keep their request open while frames arrive, so
  // `complete` may remain false even though the browser has decoded frames.
  // Intrinsic dimensions are set once a usable image frame is available.
  const width = source.naturalWidth
  const height = source.naturalHeight
  return { ready: width > 0 && height > 0, width, height }
}

export function useFaceLandmarks<TSource extends LandmarkSource>(
  image: Ref<TSource | null>,
  enabled: Readonly<Ref<boolean>>,
) {
  const faces = shallowRef<OverlayFace[]>([])
  const state = ref<'idle' | 'loading' | 'ready' | 'unavailable'>('idle')
  const fps = ref<number | null>(null)
  const frameSize = ref({ width: 0, height: 0 })
  const delegate = ref<'GPU' | 'CPU' | null>(null)
  const errorMessage = ref<string | null>(null)
  let worker: Worker | null = null
  let frameTimer: ReturnType<typeof setTimeout> | undefined
  let frameInFlight = false
  let generation = 0
  let resultTimes: number[] = []

  function stop(): void {
    generation += 1
    if (frameTimer) clearTimeout(frameTimer)
    frameTimer = undefined
    worker?.terminate()
    worker = null
    frameInFlight = false
    resultTimes = []
    faces.value = []
    fps.value = null
    frameSize.value = { width: 0, height: 0 }
    delegate.value = null
    errorMessage.value = null
  }

  function scheduleCapture(activeGeneration: number): void {
    if (
      activeGeneration !== generation ||
      !worker ||
      (typeof document !== 'undefined' && document.hidden)
    ) {
      return
    }
    frameTimer = setTimeout(() => {
      void captureFrame(activeGeneration)
    }, 1000 / FACE_MESH_TARGET_FPS)
  }

  async function captureFrame(activeGeneration: number): Promise<void> {
    const source = image.value
    const activeWorker = worker
    const frame = source ? getSourceFrame(source) : null
    if (
      activeGeneration !== generation ||
      !activeWorker ||
      frameInFlight ||
      (typeof document !== 'undefined' && document.hidden) ||
      !source ||
      !frame?.ready ||
      frame.width < 1 ||
      frame.height < 1
    ) {
      scheduleCapture(activeGeneration)
      return
    }

    frameInFlight = true
    try {
      const meshSize = getFaceMeshInputSize(frame.width, frame.height)
      const bitmap =
        meshSize.width === frame.width && meshSize.height === frame.height
          ? await createImageBitmap(source)
          : await createImageBitmap(source, {
              resizeWidth: meshSize.width,
              resizeHeight: meshSize.height,
              resizeQuality: 'low',
            })
      if (activeGeneration !== generation || activeWorker !== worker) {
        bitmap.close()
        frameInFlight = false
        return
      }
      activeWorker.postMessage({ type: 'frame', bitmap, timestamp: performance.now() }, [bitmap])
    } catch {
      frameInFlight = false
      state.value = 'unavailable'
      errorMessage.value = 'Browser tidak dapat membaca stream untuk mesh wajah.'
      return
    }
    scheduleCapture(activeGeneration)
  }

  function startForSource(source: LandmarkSource | null, active: boolean): void {
    stop()
    if (!source || !active) {
      state.value = 'idle'
      return
    }

    if (typeof Worker === 'undefined' || typeof createImageBitmap === 'undefined') {
      state.value = 'unavailable'
      errorMessage.value = 'Browser ini belum mendukung pemroses mesh wajah.'
      return
    }

    state.value = 'loading'
    const activeGeneration = generation
    const activeWorker = new Worker(
      new URL('../workers/faceLandmarker.worker.ts', import.meta.url),
      { type: 'module', name: 'presensi-face-mesh' },
    )
    worker = activeWorker
    activeWorker.addEventListener('message', (event: MessageEvent<WorkerResponse>) => {
      if (activeGeneration !== generation || activeWorker !== worker) return
      const message = event.data
      if (message.type === 'ready') {
        state.value = 'ready'
        delegate.value = message.delegate
        scheduleCapture(activeGeneration)
      } else if (message.type === 'result') {
        frameInFlight = false
        faces.value = message.faces
        frameSize.value = { width: message.width, height: message.height }
        const now = performance.now()
        resultTimes.push(now)
        resultTimes = resultTimes.filter((time) => now - time <= 2000)
        fps.value =
          resultTimes.length > 1
            ? Math.round(
                ((resultTimes.length - 1) * 1000) /
                  (resultTimes[resultTimes.length - 1] - resultTimes[0]),
              )
            : null
      } else {
        frameInFlight = false
        state.value = 'unavailable'
        errorMessage.value = message.message
      }
    })
    activeWorker.addEventListener('error', () => {
      if (activeGeneration !== generation) return
      frameInFlight = false
      state.value = 'unavailable'
      errorMessage.value = 'Pemroses mesh wajah tidak dapat dijalankan pada browser ini.'
    })
    activeWorker.postMessage({
      type: 'initialize',
      modelUrl: new URL('/models/face_landmarker.task', window.location.origin).href,
      wasmLoaderPath,
      wasmBinaryPath,
    })
  }

  function onVisibilityChange(): void {
    if (typeof document === 'undefined') return
    if (document.hidden) {
      if (frameTimer) clearTimeout(frameTimer)
      frameTimer = undefined
      faces.value = []
      return
    }
    if (worker && state.value === 'ready') scheduleCapture(generation)
  }

  watch(
    () => [image.value, enabled.value] as const,
    ([source, active]) => startForSource(source, active),
    { flush: 'post' },
  )
  onMounted(() => {
    document.addEventListener('visibilitychange', onVisibilityChange)
    startForSource(image.value, enabled.value)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('visibilitychange', onVisibilityChange)
    stop()
  })

  return { faces, state, fps, frameSize, delegate, errorMessage }
}
