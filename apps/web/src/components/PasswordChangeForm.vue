<script setup lang="ts">
import { ref } from 'vue'
import { ApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'

defineOptions({ name: 'PasswordChangeForm' })

defineProps<{
  firstLogin?: boolean
}>()

const emit = defineEmits<{
  saved: []
}>()

const auth = useAuthStore()
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const errorMessage = ref<string | null>(null)
const isSaving = ref(false)

async function submit(): Promise<void> {
  errorMessage.value = null
  if (newPassword.value !== confirmPassword.value) {
    errorMessage.value = 'Konfirmasi kata sandi baru belum sama.'
    return
  }
  if (newPassword.value.length < 12) {
    errorMessage.value = 'Gunakan kata sandi baru minimal 12 karakter.'
    return
  }

  isSaving.value = true
  try {
    await auth.updatePassword(currentPassword.value, newPassword.value)
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    emit('saved')
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError
        ? error.message
        : 'Kata sandi belum dapat diperbarui. Periksa koneksi lalu coba lagi.'
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <form class="auth-card__form password-change-form" @submit.prevent="submit">
    <div v-if="!firstLogin" class="auth-card__field">
      <label for="profile-current-password">Kata sandi saat ini</label>
      <input
        id="profile-current-password"
        v-model="currentPassword"
        type="password"
        autocomplete="current-password"
        required
        :disabled="isSaving"
      />
    </div>
    <div v-else class="auth-card__field">
      <label for="profile-current-password">Kata sandi sementara</label>
      <input
        id="profile-current-password"
        v-model="currentPassword"
        type="password"
        autocomplete="current-password"
        required
        :disabled="isSaving"
      />
    </div>

    <div class="auth-card__field">
      <label for="profile-new-password">Kata sandi baru</label>
      <input
        id="profile-new-password"
        v-model="newPassword"
        type="password"
        autocomplete="new-password"
        minlength="12"
        maxlength="128"
        required
        :disabled="isSaving"
      />
    </div>

    <div class="auth-card__field">
      <label for="profile-confirm-password">Ulangi kata sandi baru</label>
      <input
        id="profile-confirm-password"
        v-model="confirmPassword"
        type="password"
        autocomplete="new-password"
        minlength="12"
        maxlength="128"
        required
        :disabled="isSaving"
      />
    </div>

    <p v-if="errorMessage" class="auth-card__error" role="alert">{{ errorMessage }}</p>
    <button class="auth-card__submit" type="submit" :disabled="isSaving">
      {{ isSaving ? 'Menyimpan…' : 'Simpan kata sandi baru' }}
    </button>
    <p class="profile-view__hint">
      Minimal 12 karakter. Anda akan diminta masuk kembali setelah perubahan.
    </p>
  </form>
</template>
