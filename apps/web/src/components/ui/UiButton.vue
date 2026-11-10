<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'outlined' | 'text' | 'danger' | 'danger-soft'
    size?: 'md' | 'sm'
    disabled?: boolean
    type?: 'button' | 'submit' | 'reset'
  }>(),
  { variant: 'primary', size: 'md', disabled: false, type: 'button' },
)
const cls = computed(() => [
  'st-btn',
  `st-btn--${props.variant}`,
  `st-btn--${props.size}`,
  { 'st-btn--disabled': props.disabled },
])
</script>

<template>
  <button :type="type" :class="cls" :disabled="disabled"><slot /></button>
</template>

<style scoped>
.st-btn {
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 20px;
  border: 1px solid transparent;
  border-radius: var(--st-radius-sm);
  font-family: var(--st-font);
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition:
    background-color 120ms ease,
    border-color 120ms ease,
    transform 60ms ease;
}
.st-btn:active {
  transform: translateY(1px);
}
.st-btn--primary {
  background: var(--st-secondary);
  border-color: var(--st-secondary);
  color: var(--st-on-primary);
}
.st-btn--primary:hover {
  background: var(--st-primary-container);
  border-color: var(--st-primary-container);
}
.st-btn--secondary {
  background: var(--st-info-tint);
  border-color: var(--st-info-tint);
  color: var(--st-info);
}
.st-btn--outlined {
  background: var(--st-surface);
  border-color: var(--st-outline-variant);
  color: var(--st-text-main);
}
.st-btn--outlined:hover {
  border-color: var(--st-primary-container);
  color: var(--st-primary-container);
}
.st-btn--text {
  background: transparent;
  border-color: transparent;
  color: var(--st-primary-container);
  padding: 0 12px;
}
.st-btn--danger {
  background: var(--st-danger);
  border-color: var(--st-danger);
  color: #fff;
}
.st-btn--disabled,
.st-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none;
}
.st-btn:focus-visible {
  outline: 2px solid var(--st-primary-container);
  outline-offset: 3px;
}
.st-btn--sm {
  min-height: 36px;
  padding: 0 14px;
  font-size: 0.8125rem;
}
</style>
