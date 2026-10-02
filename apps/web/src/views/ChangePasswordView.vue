<script setup lang="ts">
import { useRouter } from 'vue-router'
import PasswordChangeForm from '../components/PasswordChangeForm.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

async function finishPasswordChange(): Promise<void> {
  auth.logout()
  await router.replace({ name: 'login', query: { passwordChanged: '1' } })
}
</script>

<template>
  <section class="auth-card" aria-labelledby="change-password-title">
    <span class="auth-card__mark" aria-hidden="true">P</span>
    <p class="auth-card__eyebrow">Keamanan akun</p>
    <h1 id="change-password-title">Buat kata sandi baru</h1>
    <p class="auth-card__description">
      Kata sandi sementara hanya untuk masuk pertama kali. Ganti sekarang sebelum membuka aplikasi.
    </p>
    <PasswordChangeForm first-login @saved="finishPasswordChange" />
  </section>
</template>
