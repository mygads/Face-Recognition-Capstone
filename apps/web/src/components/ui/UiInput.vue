<script setup lang="ts">
withDefaults(defineProps<{ modelValue?: string | number | null; invalid?: boolean }>(), {
  modelValue: '',
  invalid: false,
})
defineEmits<{ (e: 'update:modelValue', v: string): void }>()
defineOptions({ inheritAttrs: false })
</script>

<template>
  <input
    class="st-input"
    :class="{ 'st-input--invalid': invalid }"
    v-bind="$attrs"
    :value="modelValue ?? ''"
    :aria-invalid="invalid ? 'true' : undefined"
    @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
  />
</template>

<style scoped>
.st-input {
  width: 100%;
  min-height: 44px;
  padding: 0 14px;
  border: 1px solid var(--st-outline-variant);
  border-radius: var(--st-radius-sm);
  background: var(--st-surface);
  color: var(--st-text-main);
  font-family: var(--st-font);
  font-size: 0.875rem;
}
.st-input::placeholder {
  color: var(--st-text-muted);
  opacity: 0.8;
}
.st-input:focus {
  outline: 2px solid var(--st-primary-container);
  outline-offset: 1px;
  border-color: var(--st-primary-container);
}
.st-input--invalid {
  border-color: var(--st-error);
}
.st-input:disabled {
  opacity: 0.6;
}
</style>
