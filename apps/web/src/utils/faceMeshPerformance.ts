/** Browser-only visual mesh budget; the AI_EDGE recognition frame is untouched. */
export const FACE_MESH_TARGET_FPS = 15
export const FACE_MESH_MAX_INPUT_DIMENSION = 480
export const FACE_MESH_MAX_INPUT_PIXELS = 129_600

export function getFaceMeshInputSize(
  width: number,
  height: number,
  maxDimension = FACE_MESH_MAX_INPUT_DIMENSION,
  maxPixels = FACE_MESH_MAX_INPUT_PIXELS,
): { width: number; height: number } {
  if (
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    !Number.isFinite(maxDimension) ||
    !Number.isFinite(maxPixels) ||
    width < 1 ||
    height < 1 ||
    maxDimension < 1 ||
    maxPixels < 1
  ) {
    throw new RangeError('Face mesh dimensions must be positive finite numbers.')
  }

  const scale = Math.min(
    1,
    maxDimension / Math.max(width, height),
    Math.sqrt(maxPixels / (width * height)),
  )
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  }
}
