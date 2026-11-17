<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { mapFaceToBox, type BoxFit, type OverlayFace } from '../utils/faceBoxFit'

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
  }>(),
  {
    faces: () => [],
    label: null,
    imageWidth: null,
    imageHeight: null,
    fit: 'fill',
  },
)

const svgRef = ref<SVGSVGElement | null>(null)
const boxSize = ref({ width: 0, height: 0 })
let observer: ResizeObserver | null = null

function measure(): void {
  const el = svgRef.value
  if (el) boxSize.value = { width: el.clientWidth, height: el.clientHeight }
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
  const list = Array.isArray(props.faces) ? props.faces.slice(0, 5) : []
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
</script>

<template>
  <svg
    ref="svgRef"
    class="face-overlay"
    viewBox="0 0 1 1"
    preserveAspectRatio="none"
    aria-hidden="true"
    data-testid="face-overlay"
  >
    <g
      v-for="(face, index) in boxes"
      :key="`${index}-${face.x}-${face.y}`"
      :class="['face-overlay__mark', index === largestIndex ? 'is-primary' : 'is-secondary']"
      :data-testid="`face-box-${index}`"
    >
      <rect
        :x="face.x"
        :y="face.y"
        :width="face.width"
        :height="face.height"
        class="face-overlay__box"
        vector-effect="non-scaling-stroke"
      />
      <g v-if="Array.isArray(face.landmarks)">
        <circle
          v-for="(point, pointIndex) in (face.landmarks ?? []).slice(0, 5)"
          :key="pointIndex"
          :cx="Array.isArray(point) ? point[0] : 0"
          :cy="Array.isArray(point) ? point[1] : 0"
          r="0.008"
          class="face-overlay__point"
          vector-effect="non-scaling-stroke"
        />
      </g>
      <text
        v-if="label && index === largestIndex"
        :x="Math.min(0.98, Math.max(0, face.x))"
        :y="Math.max(0.02, face.y - 0.015)"
        class="face-overlay__tag"
      >
        {{ label }}
      </text>
    </g>
  </svg>
</template>

<style scoped>
.face-overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
.face-overlay__box {
  fill: none;
  stroke-width: 2px;
}
.face-overlay__mark.is-primary .face-overlay__box {
  stroke: #22c55e;
}
.face-overlay__mark.is-secondary .face-overlay__box {
  stroke: #f59e0b;
  stroke-dasharray: 6 4;
}
.face-overlay__point {
  fill: #22c55e;
  stroke: #ffffff;
  stroke-width: 1px;
}
.face-overlay__mark.is-secondary .face-overlay__point {
  fill: #f59e0b;
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
