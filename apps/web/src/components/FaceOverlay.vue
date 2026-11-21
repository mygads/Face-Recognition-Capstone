<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { mapFaceToBox, type BoxFit, type OverlayFace } from '../utils/faceBoxFit'
import {
  FACE_MESH_CONTOURS,
  FACE_MESH_FACE_OVAL,
  FACE_MESH_LEFT_EYE,
  FACE_MESH_LEFT_EYEBROW,
  FACE_MESH_LIPS,
  FACE_MESH_RIGHT_EYE,
  FACE_MESH_RIGHT_EYEBROW,
  FACE_MESH_TESSELLATION,
} from '../utils/faceMeshTopology'

export type { OverlayFace }

const props = withDefaults(
  defineProps<{
    faces?: OverlayFace[] | null
    label?: string | null
    /** Resolusi natural frame kamera (px). Tanpa ini = fill 1:1 (lama). */
    imageWidth?: number | null
    imageHeight?: number | null
    /** Samakan dengan object-fit CSS elemen gambar di bawah overlay. */
    fit?: BoxFit
    /** Balik koordinat mesh bila video pratinjau dicerminkan. */
    mirrored?: boolean
  }>(),
  {
    faces: () => [],
    label: null,
    imageWidth: null,
    imageHeight: null,
    fit: 'fill',
    mirrored: false,
  },
)
defineOptions({ inheritAttrs: false })

const svgRef = ref<SVGSVGElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const boxSize = ref({ width: 0, height: 0 })
let observer: ResizeObserver | null = null
let canvasContext: CanvasRenderingContext2D | null = null

function measure(): void {
  const el = svgRef.value
  if (el) {
    boxSize.value = { width: el.clientWidth, height: el.clientHeight }
    drawFaceMesh()
  }
}

function drawConnections(
  context: CanvasRenderingContext2D,
  points: number[][],
  connections: Uint16Array,
  width: number,
  height: number,
): void {
  context.beginPath()
  for (let index = 0; index < connections.length; index += 2) {
    const start = points[connections[index]]
    const end = points[connections[index + 1]]
    if (!start || !end || !Number.isFinite(start[0]) || !Number.isFinite(start[1])) continue
    if (!Number.isFinite(end[0]) || !Number.isFinite(end[1])) continue
    context.moveTo(start[0] * width, start[1] * height)
    context.lineTo(end[0] * width, end[1] * height)
  }
  context.stroke()
}

function drawFaceMesh(): void {
  const canvas = canvasRef.value
  if (!canvas) return
  const { width, height } = boxSize.value
  const denseFaces = boxes.value
    .map((face, index) => ({ face, index }))
    .filter(({ face }) => Array.isArray(face.landmarks) && face.landmarks.length >= 400)
  if (denseFaces.length === 0 && !canvasContext) return
  const context = canvasContext ?? canvas.getContext('2d')
  if (!context || width < 1 || height < 1) return
  canvasContext = context

  // The overlay is diagnostic UI; a 1.5x backing store keeps dense mesh strokes
  // crisp while avoiding the 4x canvas fill cost of a 2x device-pixel ratio.
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5)
  const canvasWidth = Math.round(width * pixelRatio)
  const canvasHeight = Math.round(height * pixelRatio)
  if (canvas.width !== canvasWidth || canvas.height !== canvasHeight) {
    canvas.width = canvasWidth
    canvas.height = canvasHeight
  }
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)
  context.clearRect(0, 0, width, height)

  denseFaces.forEach(({ face, index }) => {
    const points = face.landmarks
    if (!Array.isArray(points)) return
    const isPrimary = index === visualPrimaryIndex.value
    if (isPrimary) {
      context.lineWidth = 0.72
      context.strokeStyle = 'rgba(245, 252, 255, 0.72)'
      drawConnections(context, points, FACE_MESH_TESSELLATION, width, height)
    }

    context.lineWidth = 1.15
    context.strokeStyle = isPrimary ? '#68f4d5' : '#ffc16c'
    drawConnections(context, points, FACE_MESH_FACE_OVAL, width, height)

    if (isPrimary) {
      context.lineWidth = 1.15
      context.strokeStyle = '#68f4d5'
      drawConnections(context, points, FACE_MESH_CONTOURS, width, height)
      context.lineWidth = 1
      context.strokeStyle = 'rgba(255,255,255,0.9)'
      drawConnections(context, points, FACE_MESH_LIPS, width, height)
      drawConnections(context, points, FACE_MESH_LEFT_EYE, width, height)
      drawConnections(context, points, FACE_MESH_RIGHT_EYE, width, height)
      drawConnections(context, points, FACE_MESH_LEFT_EYEBROW, width, height)
      drawConnections(context, points, FACE_MESH_RIGHT_EYEBROW, width, height)
    }

    if (isPrimary) {
      context.fillStyle = 'rgba(255, 255, 255, 0.92)'
      for (const point of points) {
        if (!Number.isFinite(point[0]) || !Number.isFinite(point[1])) continue
        context.beginPath()
        context.arc(point[0] * width, point[1] * height, 0.72, 0, Math.PI * 2)
        context.fill()
      }
    }
  })
}

onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined' && svgRef.value) {
    observer = new ResizeObserver(() => measure())
    observer.observe(svgRef.value)
  }
})

onBeforeUnmount(() => observer?.disconnect())

const boxes = computed(() => {
  // Agent recognition may provide five sparse landmarks, but those are not a
  // face mesh. Render only dense local FaceLandmarker output (478 points).
  const list = Array.isArray(props.faces)
    ? props.faces
        .filter((face) => Array.isArray(face.landmarks) && face.landmarks.length >= 400)
        .slice(0, 5)
    : []
  const { imageWidth, imageHeight, fit } = props
  const { width, height } = boxSize.value
  if (fit === 'fill' || !imageWidth || !imageHeight || !width || !height) return list
  return list.map((face) => mapFaceToBox(face, imageWidth, imageHeight, width, height, fit))
})
const largestIndex = computed(() => {
  let best = -1
  let bestArea = 0
  boxes.value.forEach((face, index) => {
    const area = Math.max(0, face.width) * Math.max(0, face.height)
    if (area > bestArea) {
      bestArea = area
      best = index
    }
  })
  return best
})
const visualPrimaryIndex = computed(() => {
  const hasAgentSelection = boxes.value.some((face) =>
    ['primary', 'background', 'ambiguous'].includes(String(face.role)),
  )
  return hasAgentSelection
    ? boxes.value.findIndex((face) => face.role === 'primary')
    : largestIndex.value
})

function isPrimaryFace(face: OverlayFace, index: number): boolean {
  return visualPrimaryIndex.value === index && face.role !== 'ambiguous'
}

watch(boxes, drawFaceMesh, { flush: 'post' })
</script>

<template>
  <canvas
    ref="canvasRef"
    class="face-overlay__mesh"
    :class="{ 'is-mirrored': mirrored }"
    aria-hidden="true"
  />
  <svg
    v-bind="$attrs"
    ref="svgRef"
    class="face-overlay"
    :class="{ 'is-mirrored': mirrored }"
    viewBox="0 0 1 1"
    preserveAspectRatio="none"
    aria-hidden="true"
    data-testid="face-overlay"
  >
    <g
      v-for="(face, index) in boxes"
      :key="`${index}-${face.x}-${face.y}`"
      :class="[
        'face-overlay__mark',
        isPrimaryFace(face, index) ? 'is-primary' : 'is-secondary',
        face.acceptable === true ? 'is-ready' : 'is-adjust',
      ]"
      :data-testid="`face-mark-${index}`"
      :data-x="face.x"
      :data-y="face.y"
      :data-width="face.width"
      :data-height="face.height"
      :data-role="face.role ?? (isPrimaryFace(face, index) ? 'primary' : 'secondary')"
    >
      <text
        v-if="label && isPrimaryFace(face, index)"
        :x="Math.min(0.98, Math.max(0, face.x))"
        :y="Math.max(0.02, face.y - 0.015)"
        class="face-overlay__tag"
      >
        {{ label }}
      </text>
      <text
        v-else-if="face.role === 'ambiguous' || !isPrimaryFace(face, index)"
        :x="Math.min(0.98, Math.max(0, face.x))"
        :y="Math.max(0.02, face.y - 0.015)"
        class="face-overlay__tag"
      >
        {{ face.role === 'ambiguous' ? 'Bergantian' : 'Wajah lain' }}
      </text>
    </g>
  </svg>
</template>

<style scoped>
.face-overlay__mesh {
  position: absolute;
  z-index: 1;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
.face-overlay {
  position: absolute;
  z-index: 2;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
.face-overlay.is-mirrored,
.face-overlay__mesh.is-mirrored {
  transform: scaleX(-1);
}
.face-overlay__tag {
  fill: #ffffff;
  font-size: 0.036px;
  font-weight: 700;
  paint-order: stroke;
  stroke: rgb(0 0 0 / 0.65);
  stroke-width: 0.004px;
}
</style>
