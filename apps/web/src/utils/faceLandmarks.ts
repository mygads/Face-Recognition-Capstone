import type { OverlayFace } from '../components/FaceOverlay.vue'

export interface NormalizedFacePoint {
  x: number
  y: number
  z?: number
}

export type FaceSelectionRole = 'primary' | 'background' | 'ambiguous'

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

function intersectionOverUnion(a: OverlayFace, b: OverlayFace): number {
  const left = Math.max(a.x, b.x)
  const top = Math.max(a.y, b.y)
  const right = Math.min(a.x + a.width, b.x + b.width)
  const bottom = Math.min(a.y + a.height, b.y + b.height)
  const intersection = Math.max(0, right - left) * Math.max(0, bottom - top)
  const union = a.width * a.height + b.width * b.height - intersection
  return union > 0 ? intersection / union : 0
}

/**
 * Attach agent selection roles to browser meshes by geometric overlap. The
 * array order of YuNet and MediaPipe detections is unrelated and must not be
 * used to pair faces.
 */
export function associateFaceRoles(
  meshFaces: readonly OverlayFace[],
  agentFaces: readonly OverlayFace[],
): OverlayFace[] {
  if (agentFaces.length === 0) return [...meshFaces]
  const pairs = meshFaces.flatMap((mesh, meshIndex) =>
    agentFaces.flatMap((candidate, agentIndex) => {
      const overlap = intersectionOverUnion(mesh, candidate)
      return overlap > 0.04 ? [{ meshIndex, agentIndex, overlap }] : []
    }),
  )
  pairs.sort((a, b) => b.overlap - a.overlap)
  const assignedMeshes = new Set<number>()
  const assignedAgents = new Set<number>()
  const assignment = new Map<number, number>()
  for (const pair of pairs) {
    if (assignedMeshes.has(pair.meshIndex) || assignedAgents.has(pair.agentIndex)) continue
    assignedMeshes.add(pair.meshIndex)
    assignedAgents.add(pair.agentIndex)
    assignment.set(pair.meshIndex, pair.agentIndex)
  }
  return meshFaces.map((mesh, index) => {
    const agentIndex = assignment.get(index)
    if (agentIndex === undefined) return mesh
    const selected = agentFaces[agentIndex]
    return {
      ...mesh,
      role: selected.role,
      acceptable: selected.acceptable,
      reason_codes: selected.reason_codes,
    }
  })
}
