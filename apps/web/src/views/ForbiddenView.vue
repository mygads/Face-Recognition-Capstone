<template>
  <section class="workspace-card forbidden-card" aria-labelledby="forbidden-title">
    <div>
      <p class="workspace-card__eyebrow">Akses role</p>
      <h2 id="forbidden-title">Akses tidak tersedia</h2>
      <p>Akun Anda tidak memiliki role yang dibutuhkan untuk halaman ini.</p>
    </div>
    <RouterLink class="forbidden-card__link" to="/app/dashboard">Kembali ke ringkasan</RouterLink>
  </section>
</template>
