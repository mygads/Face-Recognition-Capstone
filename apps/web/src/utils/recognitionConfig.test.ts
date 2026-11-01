import { describe, expect, it } from 'vitest'
import {
  recognitionDefaults,
  recognitionFrom,
  sanitizeRecognitionForm,
  type UnknownSettings,
} from './recognitionConfig'
import type { RecognitionConfiguration } from '../api/client'

function formWith(overrides: Partial<RecognitionConfiguration>): RecognitionConfiguration {
  return { ...recognitionDefaults(), ...overrides }
}

describe('recognition configuration helpers', () => {
  it('defaults to the calibrated YuNet operating point', () => {
    const defaults = recognitionDefaults()
    expect(defaults.yunet_score_threshold).toBe(0.9)
    expect(defaults.yunet_nms_threshold).toBe(0.3)
    expect(defaults.min_top1_similarity).toBeNull()
  })

  it('reads stored settings and falls back to defaults for missing values', () => {
    const form = recognitionFrom({ yunet_score_threshold: 0.7 } as UnknownSettings)
    expect(form.yunet_score_threshold).toBe(0.7)
    expect(form.yunet_nms_threshold).toBe(0.3)
    expect(form.min_top1_similarity).toBeNull()
  })

  it('rejects out-of-range YuNet thresholds', () => {
    expect(sanitizeRecognitionForm(formWith({ yunet_score_threshold: 1.5 }))).toContain(
      'YuNet score threshold',
    )
    expect(sanitizeRecognitionForm(formWith({ yunet_nms_threshold: -0.1 }))).toContain(
      'YuNet NMS threshold',
    )
  })

  it('accepts calibrated thresholds with a calibration reference', () => {
    const form = formWith({
      min_top1_similarity: 0.6,
      min_top1_top2_margin: 0.15,
      yunet_score_threshold: 0.85,
      yunet_nms_threshold: 0.25,
      calibration_reference: 'LAP-2026-011',
    })
    expect(sanitizeRecognitionForm(form)).toBeNull()
    expect(form.yunet_score_threshold).toBe(0.85)
  })

  it('rejects NaN thresholds instead of silently clearing them', () => {
    expect(sanitizeRecognitionForm(formWith({ min_top1_similarity: Number.NaN }))).toContain(
      'angka',
    )
    expect(sanitizeRecognitionForm(formWith({ yunet_score_threshold: Number.NaN }))).toContain(
      'angka',
    )
  })

  it('keeps requiring top-1 and margin together', () => {
    const form = formWith({ min_top1_similarity: 0.6 })
    expect(sanitizeRecognitionForm(form)).toContain('bersamaan')
  })
})
