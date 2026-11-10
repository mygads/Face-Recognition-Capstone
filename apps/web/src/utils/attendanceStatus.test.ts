import { describe, expect, it } from 'vitest'
import {
  attendanceStatusLabel,
  correctionDecisionLabel,
  deviceHealthLabel,
} from './attendanceStatus'

describe('attendanceStatus', () => {
  it('menerjemahkan status kehadiran', () => {
    expect(attendanceStatusLabel('present')).toBe('Hadir')
    expect(attendanceStatusLabel('late')).toBe('Terlambat')
    expect(attendanceStatusLabel('absent')).toBe('Absen')
    expect(attendanceStatusLabel('excused')).toBe('Izin')
    expect(attendanceStatusLabel('not_recorded')).toBe('Belum tercatat')
    expect(attendanceStatusLabel(null)).toBe('Belum tercatat')
  })
  it('menerjemahkan status keputusan', () => {
    expect(correctionDecisionLabel('approved')).toBe('Disetujui')
    expect(correctionDecisionLabel('rejected')).toBe('Ditolak')
    expect(correctionDecisionLabel('pending')).toBe('Menunggu')
  })
  it('menerjemahkan status kesehatan perangkat', () => {
    expect(deviceHealthLabel('online')).toBe('Online')
    expect(deviceHealthLabel('offline')).toBe('Offline')
    expect(deviceHealthLabel('warning')).toBe('Perlu perhatian')
    expect(deviceHealthLabel(null)).toBe('-')
  })
})
