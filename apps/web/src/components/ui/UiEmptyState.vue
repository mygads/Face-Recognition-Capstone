<script setup lang="ts">
defineProps<{ title: string; description?: string; icon?: string }>()
</script>

<template>
  <div class="st-empty" role="status">
    <span v-if="icon" class="st-material-icon st-empty__icon" aria-hidden="true">{{ icon }}</span>
    <h2 class="st-empty__title">{{ title }}</h2>
    <p v-if="description" class="st-empty__desc">{{ description }}</p>
    <div v-if="$slots.actions" class="st-empty__actions"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.st-empty {
  display: grid;
  justify-items: center;
  gap: 8px;
  padding: 32px 16px;
  text-align: center;
  font-family: var(--st-font);
}
.st-empty__icon {
  font-size: 40px;
  color: var(--st-outline);
}
.st-empty__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
  color: var(--st-text-main);
}
.st-empty__desc {
  margin: 0;
  max-width: 46ch;
  font-size: 0.85rem;
  color: var(--st-text-muted);
}
.st-empty__actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
</style>
