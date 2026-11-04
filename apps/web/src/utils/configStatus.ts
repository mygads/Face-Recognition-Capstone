/**
 * Label Bahasa Indonesia untuk status sinkron konfigurasi AI Central.
 *
 * Core API menerima kombinasi yang valid-skema tapi bisa ditolak worker
 * central saat apply (mis. minimum konsensus tak terjangkau); tanpa label
 * ini admin hanya melihat revisi berbeda tanpa tahu sebabnya.
 */
export type CentralSyncStatus = 'disabled' | 'pending' | 'applied' | 'error' | 'unavailable'

export function centralSyncStatusLabel(status: CentralSyncStatus | null | undefined): string {
  switch (status) {
    case 'applied':
      return 'Sudah diterapkan'
    case 'pending':
      return 'Menunggu sinkron'
    case 'error':
      return 'Gagal diterapkan'
    case 'unavailable':
      return 'Tidak terjangkau'
    case 'disabled':
      return 'Nonaktif'
    default:
      return 'Belum diketahui'
  }
}
