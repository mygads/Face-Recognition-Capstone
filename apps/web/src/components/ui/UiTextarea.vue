<script setup lang="ts">
withDefaults(defineProps<{ modelValue?: string | null; invalid?: boolean }>(), {
  modelValue: '',
  invalid: false,
})
defineEmits<{ (e: 'update:modelValue', v: string): void }>()
defineOptions({ inheritAttrs: false })
</script>

<template>
  <textarea
    class="st-textarea"
    :class="{ 'st-textarea--invalid': invalid }"
    v-bind="$attrs"
    :value="modelValue ?? ''"
    @input="$emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
  />
</template>

<style scoped>
.st-textarea {
  width: 100%;
  min-height: 96px;
  padding: 10px 12px;
  border: 1px solid var(--st-outline-variant);
  border-radius: var(--st-radius-sm);
  background: var(--st-surface);
  color: var(--st-text-main);
  font-family: var(--st-font);
  font-size: 0.875rem;
  resize: vertical;
}
.st-textarea:focus {
  outline: 2px solid var(--st-primary-container);
  outline-offset: 1px;
  border-color: var(--st-primary-container);
}
.st-textarea--invalid {
  border-color: var(--st-error);
}
</style>
