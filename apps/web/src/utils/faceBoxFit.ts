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
  // Jepit sebagai irisan kotak: x2/y2 dijepit dulu, baru lebar/tinggi dihitung
  // dari selisihnya. Menjepit posisi dan ukuran secara terpisah membuat kotak
  // di tepi tampak lebih lebar daripada bagian wajah yang benar-benar terlihat.
  const x1 = project(face.x, renderedWidth, offsetX, boxWidth)
  const y1 = project(face.y, renderedHeight, offsetY, boxHeight)
  const x2 = project(face.x + face.width, renderedWidth, offsetX, boxWidth)
  const y2 = project(face.y + face.height, renderedHeight, offsetY, boxHeight)
  const mapped: OverlayFace = {
    ...face,
    x: x1,
    y: y1,
    width: Math.max(0, x2 - x1),
    height: Math.max(0, y2 - y1),
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
