<script setup lang="ts">
import { onMounted, onUnmounted, useSlots } from 'vue'

const props = withDefaults(defineProps<{ title: string; wide?: boolean }>(), { wide: false })
const emit = defineEmits<{ close: [] }>()

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
void props
void useSlots
</script>

<template>
  <div class="st-modal" role="dialog" aria-modal="true" :aria-label="title">
    <button
      class="st-modal__backdrop"
      type="button"
      aria-label="Tutup dialog"
      @click="$emit('close')"
    />
    <div class="st-modal__box" :class="{ 'st-modal__box--wide': wide }">
      <header class="st-modal__head">
        <h2 class="st-modal__title">{{ title }}</h2>
        <button class="st-modal__close" type="button" aria-label="Tutup" @click="$emit('close')">
          <span class="st-material-icon" aria-hidden="true">close</span>
        </button>
      </header>
      <div class="st-modal__body"><slot /></div>
      <footer v-if="$slots.footer" class="st-modal__foot"><slot name="footer" /></footer>
    </div>
  </div>
</template>

<style scoped>
.st-modal {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 20px;
  font-family: var(--st-font);
}
.st-modal__backdrop {
  position: absolute;
  inset: 0;
  background: rgb(22 37 37 / 0.45);
  border: 0;
  cursor: pointer;
}
.st-modal__box {
  position: relative;
  width: min(520px, 100%);
  max-height: min(86vh, 760px);
  overflow: auto;
  background: var(--st-surface);
  border-radius: var(--st-radius-lg);
  box-shadow: var(--st-shadow-md);
  padding: 20px;
}
.st-modal__box--wide {
  width: min(720px, 100%);
}
.st-modal__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.st-modal__title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--st-text-main);
}
.st-modal__close {
  display: inline-flex;
  border: 0;
  background: transparent;
  cursor: pointer;
  color: var(--st-text-muted);
  padding: 4px;
}
.st-modal__foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>
