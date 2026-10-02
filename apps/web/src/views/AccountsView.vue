<script setup lang="ts">
import { ref } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import {
  ApiError,
  createStaffAccount,
  type StaffAccountCreate,
  type StaffAccountCreated,
} from '../api/client'

const form = ref<StaffAccountCreate>({
  full_name: '',
  email: '',
  role: 'TEACHER',
})
const createdAccount = ref<StaffAccountCreated | null>(null)
const isSaving = ref(false)
const errorMessage = ref<string | null>(null)
const copyMessage = ref<string | null>(null)

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details?.map((item) => `${item.field}: ${item.message}`)
    return details?.length ? details.join(' · ') : error.message
  }
  return 'Permintaan tidak dapat diproses. Coba lagi.'
}

async function submitForm(): Promise<void> {
  errorMessage.value = null
  copyMessage.value = null
  createdAccount.value = null
  isSaving.value = true
  try {
    createdAccount.value = await createStaffAccount({
      full_name: form.value.full_name.trim(),
      email: form.value.email.trim(),
      role: form.value.role,
    })
    form.value = { full_name: '', email: '', role: form.value.role }
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isSaving.value = false
  }
}

async function copyTemporaryPassword(): Promise<void> {
  if (!createdAccount.value) return
  try {
    await navigator.clipboard.writeText(createdAccount.value.temporary_password)
    copyMessage.value = 'Kata sandi sementara disalin.'
  } catch {
    copyMessage.value = 'Salin kata sandi dari kotak di atas secara manual.'
  }
}
</script>

<template>
  <section class="accounts-view" aria-label="Kelola akun staf">
    <PageHeader
      eyebrow="Administrasi"
      title="Kelola akun staf"
      description="Buat akun guru dan laboran. Akun baru wajib mengganti kata sandi sebelum memakai sistem."
    />

    <p v-if="errorMessage" class="master-data__alert" role="alert">{{ errorMessage }}</p>

    <section
      v-if="createdAccount"
      class="accounts-view__created master-data__success"
      aria-live="polite"
      data-testid="account-created"
    >
      <div>
        <h2>Akun berhasil dibuat</h2>
        <p>
          Berikan kata sandi sementara ini kepada {{ createdAccount.full_name }}. Kata sandi hanya
          tersedia pada layar ini dan harus diganti saat login pertama.
        </p>
      </div>
      <dl class="accounts-view__details">
        <div>
          <dt>Email</dt>
          <dd>{{ createdAccount.email }}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd>{{ createdAccount.role === 'TEACHER' ? 'Guru' : 'Laboran' }}</dd>
        </div>
      </dl>
      <label class="accounts-view__password-label" for="temporary-password">
        Kata sandi sementara
      </label>
      <div class="accounts-view__password-row">
        <input
          id="temporary-password"
          :value="createdAccount.temporary_password"
          type="text"
          readonly
          aria-label="Kata sandi sementara, hanya ditampilkan setelah akun dibuat"
          data-testid="temporary-password"
        />
        <button class="button button--secondary" type="button" @click="copyTemporaryPassword">
          Salin
        </button>
      </div>
      <p v-if="copyMessage" class="accounts-view__copy-message" role="status">
        {{ copyMessage }}
      </p>
    </section>

    <section class="master-data__panel">
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">Akun internal</p>
          <h2>Buat akun guru atau laboran</h2>
        </div>
      </div>
      <p class="accounts-view__hint">
        Sistem membuat kata sandi sementara secara otomatis. Nilai itu tidak disimpan sebagai teks
        biasa dan tidak dapat ditampilkan ulang setelah panel ini ditutup.
      </p>
      <form class="master-data__form" @submit.prevent="submitForm">
        <label>
          Nama lengkap
          <input
            v-model="form.full_name"
            required
            minlength="2"
            maxlength="200"
            autocomplete="name"
          />
        </label>
        <label>
          Email login
          <input v-model="form.email" type="email" required maxlength="320" autocomplete="email" />
        </label>
        <label>
          Role
          <select v-model="form.role" required>
            <option value="TEACHER">Guru</option>
            <option value="LABORANT">Laboran</option>
          </select>
        </label>
        <div class="master-data__form-actions">
          <button class="button button--primary" type="submit" :disabled="isSaving">
            {{ isSaving ? 'Membuat akun…' : 'Buat akun' }}
          </button>
        </div>
      </form>
    </section>
  </section>
</template>
