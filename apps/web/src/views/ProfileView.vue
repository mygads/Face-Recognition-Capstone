<script setup lang="ts">
import { useRouter } from 'vue-router'
import PasswordChangeForm from '../components/PasswordChangeForm.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

async function finishPasswordChange(): Promise<void> {
  await auth.logout()
  await router.replace({ name: 'login', query: { passwordChanged: '1' } })
}
</script>

<template>
  <section class="profile-view" aria-label="Profil akun">
    <article class="workspace-card profile-view__account">
      <div>
        <p class="workspace-card__eyebrow">Informasi akun</p>
        <h2>{{ auth.account?.full_name ?? 'Akun' }}</h2>
      </div>
      <dl class="profile-view__details">
        <div>
          <dt>Email</dt>
          <dd>{{ auth.account?.email }}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd>{{ auth.account?.roles.join(', ') }}</dd>
        </div>
      </dl>
    </article>

    <article class="workspace-card profile-view__security">
      <div>
        <p class="workspace-card__eyebrow">Keamanan</p>
        <h2>Ubah kata sandi</h2>
        <p>Gunakan kata sandi unik yang tidak dipakai pada layanan lain.</p>
      </div>
      <PasswordChangeForm @saved="finishPasswordChange" />
    </article>
  </section>
</template>
