// Metadata izin, cermin PERMISSION_PREREQUISITES backend
// (apps/api/.../api/security/roles.py). Jaga tetap sinkron bila backend berubah.
export const PERMISSION_META: Record<
  string,
  { group: string; label: string; hint: string; needs?: string }
> = {
  schedule_read: {
    group: 'Jadwal',
    label: 'Lihat Jadwal',
    hint: 'Baca saja daftar dan detail jadwal.',
  },
  session_view: {
    group: 'Sesi dan Kehadiran',
    label: 'Pantau Sesi',
    hint: 'Melihat sesi dan roster lab penugasan.',
  },
  session_operate: {
    group: 'Sesi dan Kehadiran',
    label: 'Operasikan Sesi',
    hint: 'Buka/tutup sesi dari halaman Sesi.',
    needs: 'session_view',
  },
  attendance_manual: {
    group: 'Sesi dan Kehadiran',
    label: 'Tandai Kehadiran Manual',
    hint: 'Tandai manual pada sesi aktif.',
    needs: 'session_view',
  },
  attendance_read: {
    group: 'Sesi dan Kehadiran',
    label: 'Baca Kehadiran',
    hint: 'Melihat hasil presensi sesi.',
  },
  attendance_correct: {
    group: 'Koreksi',
    label: 'Ajukan Koreksi',
    hint: 'Mengajukan koreksi dari sesi/laporan.',
    needs: 'session_view atau reports_read',
  },
  reports_read: {
    group: 'Laporan dan EWS',
    label: 'Lihat Laporan',
    hint: 'Laporan dan ekspor sesuai cakupan lab.',
  },
  reports_export: {
    group: 'Laporan dan EWS',
    label: 'Ekspor Laporan',
    hint: 'Unduh CSV/XLSX memakai filter yang sama.',
    needs: 'reports_read',
  },
  ews_read: {
    group: 'Laporan dan EWS',
    label: 'Lihat EWS',
    hint: 'Watchlist absen/terlambat sesuai cakupan.',
  },
  ews_follow_up: {
    group: 'Laporan dan EWS',
    label: 'Catat Tindak Lanjut',
    hint: 'Menambah catatan tindak lanjut EWS.',
    needs: 'ews_read',
  },
  manage_master_data: {
    group: 'Data Master',
    label: 'Kelola Data Master',
    hint: 'Siswa, kelas, laboratorium.',
  },
  manage_accounts: {
    group: 'Administrasi',
    label: 'Kelola Akun Staf',
    hint: 'Akun, penugasan, delegasi.',
  },
  manage_settings: {
    group: 'Administrasi',
    label: 'Kelola Pengaturan',
    hint: 'Kebijakan, AI, audit.',
  },
  roster_read: {
    group: 'Akademik',
    label: 'Baca Roster',
    hint: 'Daftar siswa kelas penugasan.',
  },
  laboratory_read: {
    group: 'Akademik',
    label: 'Baca Laboratorium',
    hint: 'Daftar dan detail lab.',
  },
  device_operate: {
    group: 'Infrastruktur',
    label: 'Operasikan Perangkat',
    hint: 'Perangkat, preview, kiosk.',
  },
  schedule_manage: {
    group: 'Jadwal',
    label: 'Kelola Jadwal',
    hint: 'Buat dan ubah jadwal.',
  },
  enrollment_manage: {
    group: 'Presensi',
    label: 'Kelola Pendaftaran Wajah',
    hint: 'Capture dan template wajah.',
  },
}

export function permissionLabel(perm: string): string {
  return PERMISSION_META[perm]?.label ?? perm
}
