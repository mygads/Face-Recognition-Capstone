<script setup lang="ts">
defineProps<{ title: string; description?: string; eyebrow?: string }>()
</script>

<template>
  <div class="st-pagehead">
    <div class="st-pagehead__text">
      <p v-if="eyebrow" class="st-pagehead__eyebrow">{{ eyebrow }}</p>
      <h1 class="st-pagehead__title">{{ title }}</h1>
      <p v-if="description" class="st-pagehead__desc">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="st-pagehead__actions"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.st-pagehead {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px 16px;
  margin-bottom: 20px;
  font-family: var(--st-font);
}
.st-pagehead__eyebrow {
  margin: 0 0 4px;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--st-text-muted);
}
.st-pagehead__title {
  margin: 0;
  font-size: 1.35rem;
  font-weight: 700;
  color: var(--st-text-main);
  letter-spacing: -0.01em;
}
.st-pagehead__desc {
  margin: 4px 0 0;
  font-size: 0.85rem;
  color: var(--st-text-muted);
}
.st-pagehead__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
@media (max-width: 640px) {
  .st-pagehead__actions {
    width: 100%;
  }
  .st-pagehead__actions > * {
    flex: 1 1 100%;
    min-width: 0;
  }
}
</style>
