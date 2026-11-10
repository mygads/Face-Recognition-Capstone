<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  caption?: string
  tone?: 'default' | 'success' | 'warning' | 'danger' | 'info'
  icon?: string
  progress?: number
}>()
</script>

<template>
  <div class="st-stat">
    <p class="st-stat__label">
      {{ label
      }}<span v-if="icon" class="st-material-icon st-stat__icon" aria-hidden="true">{{
        icon
      }}</span>
    </p>
    <p class="st-stat__value" :class="tone ? `st-stat__value--${tone}` : ''">{{ value }}</p>
    <p v-if="caption" class="st-stat__caption">{{ caption }}</p>
    <div v-if="progress !== undefined" class="st-stat__bar" role="presentation">
      <span :style="{ width: Math.max(0, Math.min(100, progress)) + '%' }" />
    </div>
  </div>
</template>

<style scoped>
.st-stat {
  background: var(--st-surface);
  border: 1px solid var(--st-border);
  border-radius: var(--st-radius-lg);
  padding: 18px;
  box-shadow: var(--st-shadow-sm);
  font-family: var(--st-font);
}
.st-stat__label {
  margin: 0 0 6px;
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--st-text-muted);
}
.st-stat__value {
  margin: 0;
  font-size: 1.7rem;
  font-weight: 800;
  color: var(--st-text-main);
  line-height: 1.1;
}
.st-stat__value--success {
  color: var(--st-success);
}
.st-stat__value--warning {
  color: var(--st-warning);
}
.st-stat__value--danger {
  color: var(--st-danger);
}
.st-stat__value--info {
  color: var(--st-info);
}
.st-stat__caption {
  margin: 4px 0 0;
  font-size: 0.78rem;
  color: var(--st-text-muted);
}
.st-stat__label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.st-stat__icon {
  font-size: 20px;
  color: var(--st-outline);
}
.st-stat__bar {
  height: 6px;
  border-radius: 999px;
  background: var(--st-neutral-tint);
  margin-top: 10px;
  overflow: hidden;
}
.st-stat__bar > span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--st-primary-container);
}
.st-stat:has(.st-stat__value--success) .st-stat__bar > span {
  background: var(--st-success);
}
.st-stat:has(.st-stat__value--warning) .st-stat__bar > span {
  background: var(--st-warning);
}
.st-stat:has(.st-stat__value--danger) .st-stat__bar > span {
  background: var(--st-danger);
}
.st-stat:has(.st-stat__value--info) .st-stat__bar > span {
  background: var(--st-info);
}
</style>
