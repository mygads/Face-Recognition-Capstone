<script setup lang="ts">
import UiEmptyState from '../components/ui/UiEmptyState.vue'
</script>

<template>
  <UiEmptyState
    title="Akses tidak tersedia"
    description="Akun Anda tidak memiliki role atau izin yang dibutuhkan untuk halaman ini."
    icon="lock"
  >
    <template #actions>
      <RouterLink class="st-btn st-btn--secondary" to="/app/dashboard"
        >Kembali ke ringkasan</RouterLink
      >
    </template>
  </UiEmptyState>
</template>
