<script setup lang="ts">
withDefaults(defineProps<{ modelValue?: string; placeholder?: string }>(), {
  modelValue: '',
  placeholder: 'Cari…',
})
defineEmits<{ (e: 'update:modelValue', v: string): void }>()
defineOptions({ inheritAttrs: false })
</script>

<template>
  <label class="st-search">
    <span class="st-material-icon st-search__icon" aria-hidden="true">search</span>
    <input
      class="st-search__input"
      v-bind="$attrs"
      :value="modelValue"
      :placeholder="placeholder"
      type="search"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
  </label>
</template>

<style scoped>
.st-search {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--st-surface);
  border: 1px solid var(--st-outline-variant);
  border-radius: var(--st-radius-sm);
  padding: 0 12px;
  min-height: 44px;
  min-width: 220px;
  font-family: var(--st-font);
}
.st-search__icon {
  color: var(--st-text-muted);
  font-size: 20px;
}
.st-search__input {
  border: 0;
  outline: 0;
  background: transparent;
  flex: 1;
  font-size: 0.875rem;
  color: var(--st-text-main);
  font-family: inherit;
  min-width: 0;
}
</style>
