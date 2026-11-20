import { describe, expect, it } from 'vitest'
import { toFaceOverlayFaces } from './faceLandmarks'

describe('toFaceOverlayFaces', () => {
  it('converts all 478 normalized 3D landmarks and pads a matching face box', () => {
    const points = Array.from({ length: 478 }, (_, index) => ({
      x: 0.35 + (index % 20) * 0.01,
      y: 0.2 + Math.floor(index / 20) * 0.01,
      z: -0.02,
    }))

    const [face] = toFaceOverlayFaces([points])

    expect(face.landmarks).toHaveLength(478)
    expect(face.landmarks?.[0]).toEqual([0.35, 0.2, -0.02])
    expect(face.x).toBeLessThan(0.35)
    expect(face.y).toBeLessThan(0.2)
    expect(face.width).toBeGreaterThan(0.18)
    expect(face.height).toBeGreaterThan(0.22)
  })

  it('rejects sparse or non-finite results instead of fabricating a mesh', () => {
    const sparse = Array.from({ length: 5 }, () => ({ x: 0.5, y: 0.5 }))
    const invalid = Array.from({ length: 478 }, (_, index) => ({
      x: index === 20 ? Number.NaN : 0.5,
      y: 0.5,
    }))

    expect(toFaceOverlayFaces([sparse])).toEqual([])
    expect(toFaceOverlayFaces([invalid])).toEqual([])
  })

  it('limits visible faces and clamps points at the camera edges', () => {
    const points = Array.from({ length: 478 }, () => ({ x: -0.1, y: 1.1 }))
    const faces = toFaceOverlayFaces([points, points, points, points])

    expect(faces).toHaveLength(3)
    expect(faces[0].landmarks?.[0]).toEqual([0, 1, 0])
    expect(faces[0].x).toBe(0)
    expect(faces[0].y).toBeGreaterThan(0.98)
    expect(faces[0].y + faces[0].height).toBeLessThanOrEqual(1)
  })
})
