<script setup lang="ts">
import { computed } from 'vue'
import FaceOverlay, { type OverlayFace } from './FaceOverlay.vue'
import type { BoxFit } from '../utils/faceBoxFit'

const props = withDefaults(
  defineProps<{
    faces?: OverlayFace[] | null
    imageWidth?: number | null
    imageHeight?: number | null
    label?: string | null
    fit?: BoxFit
  }>(),
  {
    faces: () => [],
    imageWidth: null,
    imageHeight: null,
    label: null,
    fit: 'contain',
  },
)

const viewportStyle = computed(() => ({
  aspectRatio:
    props.imageWidth && props.imageHeight ? `${props.imageWidth} / ${props.imageHeight}` : '4 / 3',
}))
</script>

<template>
  <div class="camera-frame">
    <div
      class="camera-frame__viewport"
      :style="viewportStyle"
      aria-label="Bingkai kamera"
      data-testid="camera-frame"
    >
      <slot />
      <FaceOverlay
        v-if="faces?.length"
        :faces="faces"
        :image-width="imageWidth"
        :image-height="imageHeight"
        :label="label"
        :fit="fit"
      />
      <span class="camera-frame__corner camera-frame__corner--tl" aria-hidden="true" />
      <span class="camera-frame__corner camera-frame__corner--tr" aria-hidden="true" />
      <span class="camera-frame__corner camera-frame__corner--bl" aria-hidden="true" />
      <span class="camera-frame__corner camera-frame__corner--br" aria-hidden="true" />
    </div>
  </div>
</template>

<style scoped>
.camera-frame {
  display: grid;
  justify-items: stretch;
  min-width: 0;
  width: 100%;
}

.camera-frame__viewport {
  position: relative;
  width: 100%;
  min-width: 0;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  border: 1px solid var(--border-color-light, #d7dee8);
  border-radius: var(--radius-lg, 16px);
  background: #0b1724;
}

.camera-frame__viewport :deep(.camera-frame__media) {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  border-radius: inherit;
}

.camera-frame__viewport :deep(.camera-frame__placeholder) {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  color: #a9bccd;
  font-size: 0.85rem;
  text-align: center;
  pointer-events: none;
}

.camera-frame__corner {
  position: absolute;
  z-index: 2;
  width: 24px;
  height: 24px;
  border: 3px solid var(--st-gold, #fbbf24);
  pointer-events: none;
}

.camera-frame__corner--tl {
  top: -2px;
  left: -2px;
  border-right: 0;
  border-bottom: 0;
  border-top-left-radius: 12px;
}

.camera-frame__corner--tr {
  top: -2px;
  right: -2px;
  border-left: 0;
  border-bottom: 0;
  border-top-right-radius: 12px;
}

.camera-frame__corner--bl {
  bottom: -2px;
  left: -2px;
  border-right: 0;
  border-top: 0;
  border-bottom-left-radius: 12px;
}

.camera-frame__corner--br {
  right: -2px;
  bottom: -2px;
  border-left: 0;
  border-top: 0;
  border-bottom-right-radius: 12px;
}
</style>
