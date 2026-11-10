<script setup lang="ts">
defineProps<{ title?: string; subtitle?: string }>()
</script>

<template>
  <section class="st-card">
    <header v-if="title || subtitle || $slots.header" class="st-card__head">
      <div>
        <h2 v-if="title" class="st-card__title">{{ title }}</h2>
        <p v-if="subtitle" class="st-card__subtitle">{{ subtitle }}</p>
      </div>
      <slot name="header" />
    </header>
    <slot />
  </section>
</template>

<style scoped>
.st-card {
  background: var(--st-surface);
  border: 1px solid var(--st-border);
  border-radius: var(--st-radius-lg);
  padding: var(--st-space-lg);
  box-shadow: var(--st-shadow-sm);
  font-family: var(--st-font);
  color: var(--st-text-main);
}
.st-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: var(--st-space-md);
}
.st-card__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}
.st-card__subtitle {
  margin: 4px 0 0;
  font-size: 0.82rem;
  color: var(--st-text-muted);
}
</style>
