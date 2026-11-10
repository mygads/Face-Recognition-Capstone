<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isSafeRedirectPath } from '../router/index'
import { useAuthStore } from '../stores/auth'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiField from '../components/ui/UiField.vue'
import UiInput from '../components/ui/UiInput.vue'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const email = ref('')
const password = ref('')

async function submitLogin(): Promise<void> {
  try {
    await auth.login(email.value, password.value)
    if (auth.passwordChangeRequired) {
      await router.replace({ name: 'change-password' })
      return
    }
    const requestedPath = route.query.redirect
    const safeDestination =
      isSafeRedirectPath(requestedPath) && router.resolve(requestedPath).matched.length > 0
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
  <div class="st-login">
    <div class="st-login__brand">
      <img
        class="st-login__logo"
        src="/logo-sekolah.png"
        alt="Logo SMA Cimahi"
        width="112"
        height="112"
      />
      <div>
        <p class="st-login__school">Presensi Praktikum</p>
        <p class="st-login__sub">SMA Taruna Nusantara Kampus Cimahi</p>
      </div>
    </div>
    <UiCard
      title="Portal Khusus Staf"
      subtitle="Masuk menggunakan akun resmi terdaftar untuk mengelola administrasi, mengoperasikan sesi praktikum, dan pemantauan laboratorium."
    >
      <p v-if="route.query.passwordChanged === '1'" class="st-login__success" role="status">
        Kata sandi berhasil diperbarui. Silakan masuk kembali.
      </p>
      <form class="st-login__form" @submit.prevent="submitLogin">
        <UiField label="Email sekolah" :required="true" :error="null">
          <UiInput
            id="login-email"
            v-model="email"
            name="username"
            type="email"
            autocomplete="username"
            placeholder="nama@sekolah.edu"
            required
            :disabled="auth.isLoading"
          />
        </UiField>
        <UiField label="Kata sandi" :required="true" :error="auth.errorMessage">
          <UiInput
            id="login-password"
            v-model="password"
            name="password"
            type="password"
            autocomplete="current-password"
            placeholder="Masukkan kata sandi"
            required
            :invalid="Boolean(auth.errorMessage)"
            :disabled="auth.isLoading"
          />
        </UiField>
        <UiButton type="submit" variant="primary" :disabled="auth.isLoading">
          {{ auth.isLoading ? 'Memverifikasi…' : 'Masuk' }}
        </UiButton>
      </form>
    </UiCard>
  </div>
</template>

<style scoped>
.st-login {
  display: grid;
  gap: var(--st-space-lg);
  justify-items: center;
  padding: var(--st-space-lg) var(--st-space-md) 48px;
  font-family: var(--st-font);
  color: var(--st-text-main);
}
.st-login__brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  text-align: center;
}
.st-login__mark {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  border-radius: var(--st-radius);
  background: var(--st-primary-container);
  color: var(--st-on-primary);
  font-weight: 700;
  font-size: 1.25rem;
}
.st-login__school {
  margin: 0;
  font-weight: 700;
  letter-spacing: -0.01em;
}
.st-login__sub {
  margin: 2px 0 0;
  font-size: 0.8rem;
  color: var(--st-text-muted);
}
.st-login__form {
  display: grid;
  gap: var(--st-space-md);
  margin-top: var(--st-space-md);
}
.st-login__success {
  margin: 0 0 var(--st-space-sm);
  padding: 10px 12px;
  border-radius: var(--st-radius-sm);
  background: var(--st-success-tint);
  color: var(--st-success);
  font-size: 0.82rem;
  font-weight: 600;
}
.st-login :deep(.st-card) {
  width: min(100%, 480px);
}
.st-login :deep(.st-btn) {
  width: 100%;
}
</style>
