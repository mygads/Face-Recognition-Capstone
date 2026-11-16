/** Label Indonesia untuk status kehadiran. Satu sumber
 *  agar badge di seluruh halaman konsisten (Stitch 1:1). */
export function attendanceStatusLabel(status: string | null | undefined): string {
  if (status === 'present') return 'Hadir'
  if (status === 'late') return 'Terlambat'
  if (status === 'absent') return 'Absen'
  if (status === 'excused') return 'Izin'
  return 'Belum tercatat'
}

/** Label Indonesia untuk status kesehatan perangkat. Nilai tak dikenal
 *  ditampilkan apa adanya agar tidak menyembunyikan info diagnostik. */
export function deviceHealthLabel(status: string | null | undefined): string {
  if (!status) return '-'
  if (status === 'online') return 'Online'
  if (status === 'offline') return 'Offline'
  if (status === 'warning' || status === 'degraded') return 'Perlu perhatian'
  return status
}
