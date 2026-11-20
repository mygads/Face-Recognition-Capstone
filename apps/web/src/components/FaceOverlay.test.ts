import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import FaceOverlay from './FaceOverlay.vue'

describe('FaceOverlay', () => {
  it('tidak menggambar landmark lima titik agent sebagai mesh wajah', () => {
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
    expect(wrapper.findAll('[data-testid^="face-mark-"]')).toHaveLength(0)
    expect(wrapper.findAll('.face-overlay__point')).toHaveLength(0)
    expect(wrapper.findAll('.face-overlay__skeleton')).toHaveLength(0)
    expect(wrapper.findAll('rect')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('Wajah utama')
  })

  it('aman tanpa wajah', () => {
    const wrapper = mount(FaceOverlay, { props: { faces: [] } })
    expect(wrapper.find('[data-testid="face-overlay"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid^="face-mark-"]')).toHaveLength(0)
  })

  it('menggambar mesh 478 titik melalui topology canvas yang sama untuk preview dan kiosk', () => {
    const context = {
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
      setTransform: vi.fn(),
      clearRect: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
    } as unknown as CanvasRenderingContext2D
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context)
    Object.defineProperty(Element.prototype, 'clientWidth', {
      value: 640,
      configurable: true,
    })
    Object.defineProperty(Element.prototype, 'clientHeight', {
      value: 480,
      configurable: true,
    })

    try {
      const landmarks = Array.from({ length: 478 }, (_, index) => [
        0.25 + (index % 20) * 0.02,
        0.2 + Math.floor(index / 20) * 0.01,
      ])
      const wrapper = mount(FaceOverlay, {
        props: {
          faces: [{ x: 0.2, y: 0.15, width: 0.6, height: 0.6, landmarks }],
        },
      })

      expect(getContext).toHaveBeenCalledWith('2d')
      expect(context.stroke).toHaveBeenCalled()
      expect(context.arc).toHaveBeenCalledTimes(478)
      wrapper.unmount()
    } finally {
      getContext.mockRestore()
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
          faces: [
            {
              x: 0.5,
              y: 0.5,
              width: 0.2,
              height: 0.2,
              landmarks: Array.from({ length: 478 }, () => [0.5, 0.5]),
            },
          ],
          imageWidth: 640,
          imageHeight: 480,
          fit: 'cover',
        },
      })
      // Pengukuran box terjadi di onMounted; beri kesempatan re-render reaktif.
      await wrapper.vm.$nextTick()
      const face = wrapper.get('[data-testid="face-mark-0"]')
      // Tengah frame tetap di tengah box; lebar 0.2 frame -> ~0.326 box.
      expect(Number(face.attributes('data-x'))).toBeCloseTo(0.5, 5)
      expect(Number(face.attributes('data-y'))).toBeCloseTo(0.5, 5)
      expect(Number(face.attributes('data-width'))).toBeCloseTo(0.3259, 3)
      expect(wrapper.findAll('rect')).toHaveLength(0)
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
