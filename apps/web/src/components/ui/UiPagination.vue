<script setup lang="ts">
const props = withDefaults(
  defineProps<{ page: number; totalPages: number; total?: number; label?: string }>(),
  { total: 0, label: 'data' },
)
defineEmits<{ (e: 'update:page', v: number): void }>()
const pages = () => {
  const out: number[] = []
  for (let p = Math.max(1, props.page - 2); p <= Math.min(props.totalPages, props.page + 2); p++)
    out.push(p)
  return out
}
</script>

<template>
  <div class="st-pager">
    <p v-if="total" class="st-pager__info">
      Menampilkan halaman {{ page }} dari {{ totalPages }} · {{ total }} {{ label }}
    </p>
    <div class="st-pager__btns">
      <button type="button" :disabled="page <= 1" @click="$emit('update:page', page - 1)">‹</button>
      <button
        v-for="p in pages()"
        :key="p"
        type="button"
        :class="{ 'st-pager__btn--active': p === page }"
        @click="$emit('update:page', p)"
      >
        {{ p }}
      </button>
      <button type="button" :disabled="page >= totalPages" @click="$emit('update:page', page + 1)">
        Berikutnya ›
      </button>
    </div>
  </div>
</template>

<style scoped>
.st-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 4px 0;
  font-family: var(--st-font);
}
.st-pager__info {
  margin: 0;
  font-size: 0.8rem;
  color: var(--st-text-muted);
}
.st-pager__btns {
  display: flex;
  align-items: center;
  gap: 4px;
}
.st-pager__btns button {
  min-width: 34px;
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 8px;
  cursor: pointer;
  color: var(--st-text-main);
  font-weight: 600;
  font-size: 0.82rem;
  font-family: inherit;
}
.st-pager__btns button:disabled {
  opacity: 0.4;
  cursor: default;
}
.st-pager__btn--active {
  background: var(--st-primary-container) !important;
  color: #fff !important;
}
</style>
