<script setup lang="ts">
withDefaults(defineProps<{ modelValue?: string | number | null }>(), { modelValue: '' })
defineEmits<{ (e: 'update:modelValue', v: string): void }>()
defineOptions({ inheritAttrs: false })
</script>

<template>
  <select
    class="st-select"
    v-bind="$attrs"
    :value="modelValue ?? ''"
    @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
  >
    <slot />
  </select>
</template>

<style scoped>
.st-select {
  min-height: 44px;
  padding: 0 12px;
  border: 1px solid var(--st-outline-variant);
  border-radius: var(--st-radius-sm);
  background: var(--st-surface);
  color: var(--st-text-main);
  font-family: var(--st-font);
  font-size: 0.875rem;
  max-width: 100%;
}
.st-select:focus {
  outline: 2px solid var(--st-primary-container);
  outline-offset: 1px;
  border-color: var(--st-primary-container);
}
</style>
