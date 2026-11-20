import type { OverlayFace } from '../components/FaceOverlay.vue'

export interface NormalizedFacePoint {
  x: number
  y: number
  z?: number
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

/**
 * Convert real MediaPipe face mesh results into the normalized coordinates
 * used by the shared preview/kiosk overlay. Sparse detections are rejected so
 * an accidental five-point result is never presented as a dense mesh.
 */
export function toFaceOverlayFaces(
  faces: readonly (readonly NormalizedFacePoint[])[],
): OverlayFace[] {
  return faces.slice(0, 3).flatMap((points) => {
    if (points.length < 400) return []
    if (
      points.some(
        (point) =>
          !Number.isFinite(point.x) ||
          !Number.isFinite(point.y) ||
          (point.z !== undefined && !Number.isFinite(point.z)),
      )
    ) {
      return []
    }

    const landmarks = points.map((point) => [clamp01(point.x), clamp01(point.y), point.z ?? 0])
    const xs = landmarks.map(([x]) => x)
    const ys = landmarks.map(([, y]) => y)
    const minX = Math.min(...xs)
    const maxX = Math.max(...xs)
    const minY = Math.min(...ys)
    const maxY = Math.max(...ys)
    const paddingX = Math.max((maxX - minX) * 0.035, 0.008)
    const paddingY = Math.max((maxY - minY) * 0.035, 0.008)
    const x = clamp01(minX - paddingX)
    const y = clamp01(minY - paddingY)
    const right = clamp01(maxX + paddingX)
    const bottom = clamp01(maxY + paddingY)

    return [
      {
        x,
        y,
        width: Math.max(0, right - x),
        height: Math.max(0, bottom - y),
        landmarks,
      },
    ]
  })
}
