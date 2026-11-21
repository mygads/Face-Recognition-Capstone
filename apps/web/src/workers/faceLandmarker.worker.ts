import { FaceLandmarker, FilesetResolver, type FaceLandmarkerResult } from '@mediapipe/tasks-vision'
import { toFaceOverlayFaces, type NormalizedFacePoint } from '../utils/faceLandmarks'

type InitializeMessage = {
  type: 'initialize'
  modelUrl: string
  wasmLoaderPath: string
  wasmBinaryPath: string
}

type FrameMessage = {
  type: 'frame'
  bitmap: ImageBitmap
  timestamp: number
}

type WorkerMessage = InitializeMessage | FrameMessage

const workerScope = self as unknown as {
  postMessage(message: Record<string, unknown>): void
  addEventListener(type: string, listener: (event: MessageEvent<WorkerMessage>) => void): void
}
let landmarker: FaceLandmarker | null = null
let activeDelegate: 'GPU' | 'CPU' = 'CPU'
let lastTimestamp = 0

async function createLandmarker(
  modelBuffer: Uint8Array,
  delegate: 'GPU' | 'CPU',
  wasmLoaderPath: string,
  wasmBinaryPath: string,
): Promise<FaceLandmarker> {
  const files = await FilesetResolver.forVisionTasks('', true)
  return FaceLandmarker.createFromOptions(
    { ...files, wasmLoaderPath, wasmBinaryPath },
    {
      baseOptions: { modelAssetBuffer: modelBuffer, delegate },
      runningMode: 'VIDEO',
      // A few faces are needed to color the agent-selected foreground face
      // and background faces consistently. The overlay draws a dense mesh
      // only for the primary face to keep kiosk rendering inexpensive.
      numFaces: 3,
      minFaceDetectionConfidence: 0.5,
      minFacePresenceConfidence: 0.5,
      minTrackingConfidence: 0.5,
      outputFaceBlendshapes: false,
      outputFacialTransformationMatrixes: false,
    },
  )
}

async function initialize(message: InitializeMessage): Promise<void> {
  try {
    const response = await fetch(message.modelUrl, { cache: 'force-cache' })
    if (!response.ok) {
      throw new Error('Model mesh tidak tersedia dari aplikasi lokal.')
    }
    const modelBuffer = new Uint8Array(await response.arrayBuffer())

    try {
      landmarker = await createLandmarker(
        modelBuffer,
        'GPU',
        message.wasmLoaderPath,
        message.wasmBinaryPath,
      )
      activeDelegate = 'GPU'
    } catch {
      landmarker = await createLandmarker(
        modelBuffer,
        'CPU',
        message.wasmLoaderPath,
        message.wasmBinaryPath,
      )
      activeDelegate = 'CPU'
    }

    workerScope.postMessage({ type: 'ready', delegate: activeDelegate })
  } catch {
    workerScope.postMessage({
      type: 'error',
      message: 'Mesh wajah tidak dapat dimuat. Pastikan aset model tersedia.',
    })
  }
}

function serializeFaces(result: FaceLandmarkerResult) {
  return toFaceOverlayFaces(
    result.faceLandmarks.map((face) =>
      face.map((point) => ({
        x: point.x,
        y: point.y,
        z: point.z,
      })),
    ) as NormalizedFacePoint[][],
  )
}

function processFrame(message: FrameMessage): void {
  const { bitmap, timestamp } = message
  try {
    if (!landmarker) return
    const safeTimestamp = Math.max(timestamp, lastTimestamp + 1)
    lastTimestamp = safeTimestamp
    const startedAt = performance.now()
    const result = landmarker.detectForVideo(bitmap, safeTimestamp)
    workerScope.postMessage({
      type: 'result',
      faces: serializeFaces(result),
      width: bitmap.width,
      height: bitmap.height,
      inferenceMs: performance.now() - startedAt,
      delegate: activeDelegate,
    })
  } catch {
    workerScope.postMessage({
      type: 'error',
      message: 'Mesh wajah berhenti. Muat ulang preview untuk mencoba lagi.',
    })
  } finally {
    bitmap.close()
  }
}

workerScope.addEventListener('message', (event: MessageEvent<WorkerMessage>) => {
  if (event.data.type === 'initialize') {
    void initialize(event.data)
    return
  }
  processFrame(event.data)
})

workerScope.addEventListener('messageerror', () => {
  workerScope.postMessage({
    type: 'error',
    message: 'Frame kamera tidak dapat diteruskan ke pemroses mesh.',
  })
})
