<template>
  <section class="welcome-card" aria-labelledby="welcome-title">
    <div class="welcome-card__icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none">
        <path d="m3.5 9 8.5-5 8.5 5-8.5 5-8.5-5Z" />
        <path d="M7 11.1v4.5c2.9 2.2 7.1 2.2 10 0v-4.5M20.5 9v6" />
      </svg>
    </div>
    <div class="welcome-card__content">
      <p class="welcome-card__eyebrow">Ruang kerja</p>
      <h2 id="welcome-title">Selamat datang</h2>
      <p>
        Navigasi dan area aplikasi sudah siap. Modul praktikum akan tampil di sini saat tersedia
        untuk akun Anda.
      </p>
    </div>
    <span class="welcome-card__status">Siap digunakan</span>
  </section>

  <section class="workspace-card" aria-labelledby="workspace-title">
    <div>
      <p class="workspace-card__eyebrow">Fondasi aplikasi</p>
      <h2 id="workspace-title">Ruang kerja presensi</h2>
      <p>Shell responsif dengan navigasi Vue, header halaman, dan tema yang tersimpan.</p>
    </div>
    <span class="workspace-card__badge">Vue 3</span>
  </section>
</template>
