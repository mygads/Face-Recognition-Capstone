import { describe, expect, it } from 'vitest'
import { associateFaceRoles, toFaceOverlayFaces } from './faceLandmarks'

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

describe('associateFaceRoles', () => {
  const mesh = [
    { x: 0.1, y: 0.1, width: 0.3, height: 0.4, landmarks: [] },
    { x: 0.65, y: 0.2, width: 0.12, height: 0.16, landmarks: [] },
  ]

  it('maps agent-selected face roles by overlap, independent of detection order', () => {
    const mapped = associateFaceRoles(mesh, [
      { x: 0.64, y: 0.19, width: 0.14, height: 0.18, role: 'background' },
      { x: 0.08, y: 0.08, width: 0.34, height: 0.44, role: 'primary' },
    ])

    expect(mapped[0].role).toBe('primary')
    expect(mapped[1].role).toBe('background')
  })

  it('leaves unmatched meshes unclassified rather than pairing by array index', () => {
    const mapped = associateFaceRoles(mesh, [
      { x: 0.3, y: 0.6, width: 0.1, height: 0.1, role: 'primary' },
    ])

    expect(mapped).toEqual(mesh)
  })
})
