<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ tone?: 'present' | 'late' | 'absent' | 'excused' | 'neutral' | 'info' }>(),
  { tone: 'neutral' },
)
const cls = computed(() => [
  'st-badge',
  `st-badge--${props.tone}`,
  'ui-badge',
  `ui-badge--${props.tone}`,
])
</script>

<template>
  <span :class="cls" role="status"><slot /></span>
</template>

<style scoped>
.st-badge {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 2px 12px;
  border-radius: 999px;
  font-family: var(--st-font);
  font-weight: 600;
  font-size: 0.75rem;
  letter-spacing: 0.01em;
}
.st-badge--present {
  background: var(--st-success-tint);
  color: var(--st-success);
}
.st-badge--late {
  background: var(--st-warning-tint);
  color: var(--st-warning);
}
.st-badge--absent {
  background: var(--st-danger-tint);
  color: var(--st-danger);
}
.st-badge--excused {
  background: var(--st-info-tint);
  color: var(--st-info);
}
.st-badge--neutral {
  background: var(--st-neutral-tint);
  color: var(--st-neutral-pill);
}
.st-badge--info {
  background: var(--st-info-tint);
  color: var(--st-info);
}
/* kelas lama dipertahankan agar tidak merusak pemakaian eksisting */
.ui-badge {
  display: inline-flex;
}
</style>
