import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import FaceOverlay from './FaceOverlay.vue'

describe('FaceOverlay', () => {
  it('menyorot wajah terbesar dan menggambar lima titik landmark', () => {
    const wrapper = mount(FaceOverlay, {
      props: {
        label: 'Wajah utama',
        faces: [
          {
            x: 0.05,
            y: 0.05,
            width: 0.1,
            height: 0.1,
            landmarks: [
              [0.07, 0.08],
              [0.1, 0.08],
              [0.085, 0.11],
              [0.07, 0.13],
              [0.1, 0.13],
            ],
          },
          {
            x: 0.4,
            y: 0.2,
            width: 0.3,
            height: 0.4,
            landmarks: [
              [0.45, 0.3],
              [0.6, 0.3],
              [0.52, 0.4],
              [0.47, 0.5],
              [0.58, 0.5],
            ],
          },
        ],
      },
    })
    const marks = wrapper.findAll('[data-testid^="face-box-"]')
    expect(marks).toHaveLength(2)
    expect(marks[1].classes()).toContain('is-primary')
    expect(marks[0].classes()).toContain('is-secondary')
    expect(wrapper.findAll('.face-overlay__point')).toHaveLength(10)
    expect(wrapper.text()).toContain('Wajah utama')
  })

  it('aman tanpa wajah', () => {
    const wrapper = mount(FaceOverlay, { props: { faces: [] } })
    expect(wrapper.find('[data-testid="face-overlay"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid^="face-box-"]')).toHaveLength(0)
  })
})

describe('FaceOverlay cover mapping', () => {
  it('memetakan koordinat mengikuti crop object-fit cover', async () => {
    Object.defineProperty(Element.prototype, 'clientWidth', {
      value: 360,
      configurable: true,
    })
    Object.defineProperty(Element.prototype, 'clientHeight', {
      value: 440,
      configurable: true,
    })
    try {
      const wrapper = mount(FaceOverlay, {
        props: {
          faces: [{ x: 0.5, y: 0.5, width: 0.2, height: 0.2 }],
          imageWidth: 640,
          imageHeight: 480,
          fit: 'cover',
        },
      })
      // Pengukuran box terjadi di onMounted; beri kesempatan re-render reaktif.
      await wrapper.vm.$nextTick()
      const rect = wrapper.find('[data-testid="face-box-0"] rect')
      // Tengah frame tetap di tengah box; lebar 0.2 frame -> ~0.326 box.
      expect(Number(rect.attributes('x'))).toBeCloseTo(0.5, 5)
      expect(Number(rect.attributes('y'))).toBeCloseTo(0.5, 5)
      expect(Number(rect.attributes('width'))).toBeCloseTo(0.3259, 3)
    } finally {
      Object.defineProperty(Element.prototype, 'clientWidth', {
        value: 0,
        configurable: true,
      })
      Object.defineProperty(Element.prototype, 'clientHeight', {
        value: 0,
        configurable: true,
      })
    }
  })
})
