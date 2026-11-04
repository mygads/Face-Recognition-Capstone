import { describe, expect, it } from 'vitest'
import { centralSyncStatusLabel } from './configStatus'

describe('central sync status label', () => {
  it('melabeli setiap status sinkron dalam Bahasa Indonesia', () => {
    expect(centralSyncStatusLabel('applied')).toBe('Sudah diterapkan')
    expect(centralSyncStatusLabel('pending')).toBe('Menunggu sinkron')
    expect(centralSyncStatusLabel('error')).toBe('Gagal diterapkan')
    expect(centralSyncStatusLabel('unavailable')).toBe('Tidak terjangkau')
    expect(centralSyncStatusLabel('disabled')).toBe('Nonaktif')
  })

  it('menandai status belum diketahui secara eksplisit', () => {
    expect(centralSyncStatusLabel(null)).toBe('Belum diketahui')
    expect(centralSyncStatusLabel(undefined)).toBe('Belum diketahui')
  })
})
