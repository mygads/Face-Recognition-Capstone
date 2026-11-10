<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

defineProps<{ title: string; subtitle?: string }>()
const emit = defineEmits<{ close: [] }>()

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="st-drawer" role="dialog" aria-modal="true" :aria-label="title">
    <button
      class="st-drawer__backdrop"
      type="button"
      aria-label="Tutup panel"
      @click="$emit('close')"
    />
    <aside class="st-drawer__panel">
      <header class="st-drawer__head">
        <div>
          <h2 class="st-drawer__title">{{ title }}</h2>
          <p v-if="subtitle" class="st-drawer__subtitle">{{ subtitle }}</p>
        </div>
        <button class="st-drawer__close" type="button" aria-label="Tutup" @click="$emit('close')">
          <span class="st-material-icon" aria-hidden="true">close</span>
        </button>
      </header>
      <div class="st-drawer__body"><slot /></div>
      <footer v-if="$slots.footer" class="st-drawer__foot"><slot name="footer" /></footer>
    </aside>
  </div>
</template>

<style scoped>
.st-drawer {
  position: fixed;
  inset: 0;
  z-index: 60;
  font-family: var(--st-font);
}
.st-drawer__backdrop {
  position: absolute;
  inset: 0;
  background: rgb(22 37 37 / 0.45);
  border: 0;
  cursor: pointer;
}
.st-drawer__panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(480px, 100%);
  background: var(--st-surface);
  box-shadow: var(--st-shadow-md);
  display: flex;
  flex-direction: column;
}
.st-drawer__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 20px 12px;
  border-bottom: 1px solid var(--st-border);
}
.st-drawer__title {
  margin: 0;
  font-size: 1.02rem;
  font-weight: 700;
  color: var(--st-text-main);
}
.st-drawer__subtitle {
  margin: 4px 0 0;
  font-size: 0.8rem;
  color: var(--st-text-muted);
}
.st-drawer__close {
  display: inline-flex;
  border: 0;
  background: transparent;
  cursor: pointer;
  color: var(--st-text-muted);
  padding: 4px;
}
.st-drawer__body {
  flex: 1;
  overflow: auto;
  padding: 16px 20px;
}
.st-drawer__foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--st-border);
}
</style>
