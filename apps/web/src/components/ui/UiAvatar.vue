<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ name: string }>()
const initials = computed(() =>
  props.name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w.charAt(0).toUpperCase())
    .join(''),
)
</script>

<template>
  <span class="st-avatar" aria-hidden="true">{{ initials }}</span>
</template>

<style scoped>
.st-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 999px;
  background: var(--st-surface-container);
  color: var(--st-primary-container);
  font-weight: 700;
  font-size: 0.75rem;
  font-family: var(--st-font);
}
</style>
