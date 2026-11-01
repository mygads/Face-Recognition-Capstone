import type { RecognitionConfiguration } from '../api/client'

export type UnknownSettings = Record<string, unknown>

export function recognitionDefaults(): RecognitionConfiguration {
  return {
    min_face_pixels: 80,
    min_laplacian_variance: 45,
    min_brightness: 25,
    max_brightness: 235,
    min_top1_similarity: null,
    min_top1_top2_margin: null,
    yunet_score_threshold: 0.9,
    yunet_nms_threshold: 0.3,
    minimum_agreeing_frames: 3,
    sample_every_n_frames: 5,
    best_frame_count: 5,
    max_history_frames: 10,
    calibration_reference: null,
  }
}

export function numeric(settings: UnknownSettings, key: string, fallback: number): number {
  const value = settings[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

export function optionalNumeric(settings: UnknownSettings, key: string): number | null {
  const value = settings[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function recognitionFrom(settings: UnknownSettings): RecognitionConfiguration {
  const defaults = recognitionDefaults()
  return {
    min_face_pixels: numeric(settings, 'min_face_pixels', defaults.min_face_pixels),
    min_laplacian_variance: numeric(
      settings,
      'min_laplacian_variance',
      defaults.min_laplacian_variance,
    ),
    min_brightness: numeric(settings, 'min_brightness', defaults.min_brightness),
    max_brightness: numeric(settings, 'max_brightness', defaults.max_brightness),
    min_top1_similarity: optionalNumeric(settings, 'min_top1_similarity'),
    min_top1_top2_margin: optionalNumeric(settings, 'min_top1_top2_margin'),
    yunet_score_threshold: numeric(
      settings,
      'yunet_score_threshold',
      defaults.yunet_score_threshold,
    ),
    yunet_nms_threshold: numeric(settings, 'yunet_nms_threshold', defaults.yunet_nms_threshold),
    minimum_agreeing_frames: numeric(
      settings,
      'minimum_agreeing_frames',
      defaults.minimum_agreeing_frames,
    ),
    sample_every_n_frames: numeric(
      settings,
      'sample_every_n_frames',
      defaults.sample_every_n_frames,
    ),
    best_frame_count: numeric(settings, 'best_frame_count', defaults.best_frame_count),
    max_history_frames: numeric(settings, 'max_history_frames', defaults.max_history_frames),
    calibration_reference:
      typeof settings.calibration_reference === 'string' ? settings.calibration_reference : null,
  }
}

/**
 * Titik awal ketat SEMENTARA agar instalasi baru langsung jalan end-to-end.
 *
 * Ini BUKAN hasil kalibrasi: nilainya sengaja ketat (presisi tinggi, recall
 * rendah — wajah meragukan jatuh ke "ulangi/frontal" atau presensi manual)
 * dan referensinya menandai diri sebagai non-final. Produksi WAJIB kalibrasi
 * lokal (backlog P0-5) sebelum threshold ini dianggap final.
 */
export const FACTORY_SAFE_CALIBRATION_REFERENCE =
  'DEFAULT-AMAN-SEMENTARA — wajib kalibrasi lokal sebelum produksi (P0-5)'

export function factorySafeThresholds(): Pick<
  RecognitionConfiguration,
  'min_top1_similarity' | 'min_top1_top2_margin' | 'calibration_reference'
> {
  return {
    min_top1_similarity: 0.65,
    min_top1_top2_margin: 0.2,
    calibration_reference: FACTORY_SAFE_CALIBRATION_REFERENCE,
  }
}

export function isFactoryDefaultReference(reference: string | null | undefined): boolean {
  return typeof reference === 'string' && reference.startsWith('DEFAULT-AMAN-SEMENTARA')
}

export function sanitizeOptionalNumber(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function sanitizeRecognitionForm(form: RecognitionConfiguration): string | null {
  for (const value of [
    form.min_top1_similarity,
    form.min_top1_top2_margin,
    form.yunet_score_threshold,
    form.yunet_nms_threshold,
  ]) {
    // v-model.number and parseOptionalNumber produce NaN for non-numeric
    // typing; without this guard NaN silently coerces to null and clears
    // calibrated thresholds instead of surfacing a validation error.
    if (typeof value === 'number' && Number.isNaN(value)) {
      return 'Nilai threshold harus berupa angka.'
    }
  }
  const top1 = sanitizeOptionalNumber(form.min_top1_similarity)
  const margin = sanitizeOptionalNumber(form.min_top1_top2_margin)
  form.min_top1_similarity = top1
  form.min_top1_top2_margin = margin
  if ((top1 === null) !== (margin === null)) {
    return 'Top-1 dan margin harus diisi bersamaan atau dikosongkan keduanya.'
  }
  if (top1 !== null && !(form.calibration_reference ?? '').trim()) {
    return 'Referensi laporan kalibrasi wajib diisi bila threshold diatur.'
  }
  const yunetScore = sanitizeOptionalNumber(form.yunet_score_threshold)
  const yunetNms = sanitizeOptionalNumber(form.yunet_nms_threshold)
  if (yunetScore === null || yunetScore < 0 || yunetScore > 1) {
    return 'YuNet score threshold harus di antara 0 dan 1.'
  }
  if (yunetNms === null || yunetNms < 0 || yunetNms > 1) {
    return 'YuNet NMS threshold harus di antara 0 dan 1.'
  }
  form.yunet_score_threshold = yunetScore
  form.yunet_nms_threshold = yunetNms
  return null
}
