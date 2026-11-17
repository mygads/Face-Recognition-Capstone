import { describe, expect, it } from 'vitest'
import { mapFaceToBox } from './faceBoxFit'

const FACE = { x: 0.5, y: 0.5, width: 0.2, height: 0.2, landmarks: [[0.5, 0.5]] }

describe('mapFaceToBox', () => {
  it('fill mempertahankan koordinat', () => {
    expect(mapFaceToBox(FACE, 640, 480, 360, 440, 'fill')).toEqual(FACE)
  })

  it('cover memotong sisi landscape pada box portrait', () => {
    // Frame 640x480 (4:3) di box 360x440: crop horizontal ~39%.
    const mapped = mapFaceToBox(FACE, 640, 480, 360, 440, 'cover')
    expect(mapped.x).toBeCloseTo(0.5, 5)
    expect(mapped.y).toBeCloseTo(0.5, 5)
    // Wajah selebar 20% frame (128px) dirender 440/480*128 = 117px dari 360px box.
    expect(mapped.width).toBeCloseTo(117.33 / 360, 4)
    // Landmark ikut bergeser sama.
    expect(mapped.landmarks?.[0][0]).toBeCloseTo(0.5, 5)
  })

  it('cover memetakan wajah tepi yang masih terlihat', () => {
    // Wajah di x=0.25 frame: masih dalam crop terlihat (0.193-0.807).
    const mapped = mapFaceToBox({ ...FACE, x: 0.25 }, 640, 480, 360, 440, 'cover')
    expect(mapped.x).toBeGreaterThan(0)
    expect(mapped.x).toBeLessThan(0.5)
  })

  it('contain menghitung bar letterbox', () => {
    // Frame 4:3 di box portrait: bar atas-bawah, gambar penuh terlihat.
    const mapped = mapFaceToBox(FACE, 640, 480, 360, 440, 'contain')
    expect(mapped.x).toBeCloseTo(0.5, 5)
    expect(mapped.y).toBeCloseTo(0.5, 5)
  })

  it('aman untuk dimensi tak valid', () => {
    expect(mapFaceToBox(FACE, 0, 480, 360, 440, 'cover')).toEqual(FACE)
    expect(mapFaceToBox(FACE, 640, 480, 0, 440, 'cover')).toEqual(FACE)
  })
})
