<script setup lang="ts">
defineProps<{ tabs: { id: string; label: string; count?: number }[]; modelValue: string }>()
defineEmits<{ (e: 'update:modelValue', v: string): void }>()
</script>

<template>
  <div class="st-tabs" role="tablist">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      role="tab"
      type="button"
      class="st-tabs__tab"
      :class="{ 'st-tabs__tab--active': tab.id === modelValue }"
      :aria-selected="tab.id === modelValue"
      @click="$emit('update:modelValue', tab.id)"
    >
      {{ tab.label }}
      <span v-if="tab.count !== undefined" class="st-tabs__count">{{ tab.count }}</span>
    </button>
  </div>
</template>

<style scoped>
.st-tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--st-border);
  font-family: var(--st-font);
}
.st-tabs__tab {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 0;
  background: transparent;
  padding: 10px 14px;
  font-size: 0.86rem;
  font-weight: 600;
  color: var(--st-text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  font-family: inherit;
}
.st-tabs__tab--active {
  color: var(--st-primary-container);
  border-bottom-color: var(--st-primary-container);
}
.st-tabs__count {
  background: var(--st-neutral-tint);
  color: var(--st-neutral-pill);
  border-radius: 999px;
  padding: 1px 9px;
  font-size: 0.72rem;
}
.st-tabs__tab--active .st-tabs__count {
  background: var(--st-surface-container);
  color: var(--st-primary-container);
}
</style>
