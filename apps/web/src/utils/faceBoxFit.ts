export type BoxFit = 'fill' | 'cover' | 'contain'

export interface NormalizedBox {
  x: number
  y: number
  width: number
  height: number
}

export interface OverlayFace extends NormalizedBox {
  landmarks?: number[][] | null
  [key: string]: unknown
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

/**
 * Petakan wajah dari koordinat ternormalisasi frame kamera ke koordinat
 * ternormalisasi box tampilan, mengikuti `object-fit` CSS.
 *
 * - fill: regang 1:1 (perilaku lama).
 * - cover: potong tengah sisi yang berlebih, lalu regang sisa crop ke box.
 * - contain: seluruh frame terlihat + bar letterbox dihitung sebagai offset.
 */
export function mapFaceToBox<T extends OverlayFace>(
  face: T,
  imageWidth: number,
  imageHeight: number,
  boxWidth: number,
  boxHeight: number,
  fit: BoxFit = 'fill',
): T {
  if (
    !Number.isFinite(imageWidth) ||
    !Number.isFinite(imageHeight) ||
    !Number.isFinite(boxWidth) ||
    !Number.isFinite(boxHeight) ||
    imageWidth <= 0 ||
    imageHeight <= 0 ||
    boxWidth <= 0 ||
    boxHeight <= 0 ||
    fit === 'fill'
  ) {
    return face
  }
  const scale =
    fit === 'cover'
      ? Math.max(boxWidth / imageWidth, boxHeight / imageHeight)
      : Math.min(boxWidth / imageWidth, boxHeight / imageHeight)
  // Ukuran gambar yang dirender (px) dan offset-nya di dalam box (px).
  const renderedWidth = imageWidth * scale
  const renderedHeight = imageHeight * scale
  const offsetX = (boxWidth - renderedWidth) / 2
  const offsetY = (boxHeight - renderedHeight) / 2
  const project = (value: number, rendered: number, offset: number, box: number) =>
    clamp01((value * rendered + offset) / box)
  const mapped: OverlayFace = {
    ...face,
    x: project(face.x, renderedWidth, offsetX, boxWidth),
    y: project(face.y, renderedHeight, offsetY, boxHeight),
    width: clamp01((face.width * renderedWidth) / boxWidth),
    height: clamp01((face.height * renderedHeight) / boxHeight),
  }
  if (Array.isArray(face.landmarks)) {
    mapped.landmarks = face.landmarks.map((point) =>
      Array.isArray(point)
        ? [
            project(Number(point[0]), renderedWidth, offsetX, boxWidth),
            project(Number(point[1]), renderedHeight, offsetY, boxHeight),
          ]
        : point,
    )
  }
  return mapped as T
}
