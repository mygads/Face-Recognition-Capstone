<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const email = ref('')
const password = ref('')

async function submitLogin(): Promise<void> {
  try {
    await auth.login(email.value, password.value)
    const requestedPath = route.query.redirect
    const safeDestination =
      typeof requestedPath === 'string' &&
      requestedPath.startsWith('/') &&
      !requestedPath.startsWith('//') &&
      router.resolve(requestedPath).matched.length > 0
        ? requestedPath
        : { name: 'dashboard' }

    await router.replace(safeDestination)
  } catch {
    // The auth store exposes a safe, user-facing message without request data.
  } finally {
    password.value = ''
  }
}
</script>

<template>
  <section class="auth-card" aria-labelledby="login-title">
    <span class="auth-card__mark" aria-hidden="true">P</span>
    <p class="auth-card__eyebrow">Portal sekolah</p>
    <h1 id="login-title">Masuk ke akun</h1>
    <p class="auth-card__description">
      Gunakan akun internal sekolah untuk membuka ruang kerja presensi praktikum.
    </p>

    <form class="auth-card__form" @submit.prevent="submitLogin">
      <div class="auth-card__field">
        <label for="login-email">Email sekolah</label>
        <input
          id="login-email"
          v-model.trim="email"
          name="username"
          type="email"
          autocomplete="username"
          placeholder="nama@sekolah.edu"
          required
          :disabled="auth.isLoading"
        />
      </div>

      <div class="auth-card__field">
        <label for="login-password">Kata sandi</label>
        <input
          id="login-password"
          v-model="password"
          name="password"
          type="password"
          autocomplete="current-password"
          placeholder="Masukkan kata sandi"
          required
          :disabled="auth.isLoading"
        />
      </div>

      <p v-if="auth.errorMessage" class="auth-card__error" role="alert" aria-live="assertive">
        {{ auth.errorMessage }}
      </p>

      <button class="auth-card__submit" type="submit" :disabled="auth.isLoading">
        {{ auth.isLoading ? 'Memverifikasi…' : 'Masuk' }}
      </button>
    </form>
  </section>
</template>
