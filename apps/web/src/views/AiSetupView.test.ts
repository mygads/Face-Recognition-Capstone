import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AiSetupView from './AiSetupView.vue'

const api = vi.hoisted(() => ({
  getAiReadiness: vi.fn(),
  getCentralRecognitionConfiguration: vi.fn(),
  getDeviceRuntimeConfiguration: vi.fn(),
  getEnrollmentQualityConfiguration: vi.fn(),
  listDevices: vi.fn(),
  saveCentralRecognitionConfiguration: vi.fn(),
  saveEdgeDeviceConfiguration: vi.fn(),
  saveEnrollmentQualityConfiguration: vi.fn(),
  saveGatewayDeviceConfiguration: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    code?: string
    details?: { field: string; message: string }[]
  },
  ...api,
}))

const edgeDevice = {
  device_id: '76f1f10d-df24-4ffc-a5bc-6ff273dc8e2b',
  name: 'PClab1',
  device_type: 'edge_pc',
  deployment_profile: 'AI_EDGE',
  laboratory_id: 'lab-1',
  laboratory_code: 'LAB-1',
  laboratory_name: 'Laboratorium 1',
  is_active: true,
  app_version: '0.1.0',
  model_version: 'opencv-zoo-sface-2021dec',
  camera_status: 'online',
  last_seen_at: '2026-11-20T12:00:00Z',
  heartbeat_timeout_seconds: 60,
  latency_summary: null,
  health_status: 'online',
  config_applied_revision: 2,
  config_apply_status: 'applied',
  config_error_code: null,
}

const edgeRuntimeConfiguration = {
  device_id: edgeDevice.device_id,
  deployment_profile: 'AI_EDGE',
  camera_enabled: true,
  revision: 2,
  settings: {
    min_face_pixels: 80,
    min_laplacian_variance: 45,
    min_brightness: 25,
    max_brightness: 235,
    min_top1_similarity: null,
    min_top1_top2_margin: null,
    yunet_score_threshold: 0.9,
    yunet_nms_threshold: 0.3,
    minimum_agreeing_frames: 3,
    sample_every_n_frames: 5,
    best_frame_count: 5,
    max_history_frames: 10,
    calibration_reference: null,
  },
  applied_revision: 2,
  apply_status: 'applied',
  error_code: null,
  updated_at: '2026-11-20T12:00:00Z',
}

function mountAiSetup() {
  return mount(AiSetupView, {
    global: {
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a :href="to"><slot /></a>',
        },
      },
    },
  })
}

describe('AI_EDGE recognition setup', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getAiReadiness.mockResolvedValue({
      deployment_profile: 'AI_EDGE',
      enrollment_models_ready: true,
      enrollment_model_version: 'opencv-zoo-sface-2021dec',
      enrollment_quality_revision: 2,
      central_ai_status: 'disabled',
      central_ai_models_ready: null,
      central_ai_model_version: null,
      central_ai_thresholds_configured: null,
      central_ai_recognition_ready: null,
      central_ai_config_desired_revision: null,
      central_ai_config_applied_revision: null,
      central_ai_config_sync_status: null,
    })
    api.listDevices.mockResolvedValue({
      items: [edgeDevice],
      pagination: { total: 1, limit: 100, offset: 0 },
    })
    api.getEnrollmentQualityConfiguration.mockResolvedValue({
      revision: 2,
      settings: {
        min_face_pixels: 80,
        min_sharpness: 45,
        min_brightness: 25,
        max_brightness: 235,
      },
    })
    api.getDeviceRuntimeConfiguration.mockResolvedValue(edgeRuntimeConfiguration)
    api.saveEdgeDeviceConfiguration.mockResolvedValue({
      ...edgeRuntimeConfiguration,
      revision: 3,
      applied_revision: 2,
      apply_status: 'pending',
    })
  })

  it('explains each field and fills a clearly marked local test preset', async () => {
    const wrapper = mountAiSetup()
    await flushPromises()
    await wrapper.get('[aria-label="Kelompok pengaturan"] button:nth-child(2)').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="edge-preset-note"]').text()).toContain(
      'Preset bukan hasil kalibrasi',
    )
    expect(wrapper.get('#edge-top1-hint').text()).toContain('Nilai awal uji: 0,65')
    expect(wrapper.get('#edge-sample-every-hint').text()).toContain('bukan FPS kamera')

    await wrapper.get('[data-testid="edge-default-preset"]').trigger('click')

    expect((wrapper.get('#edge-top1-threshold').element as HTMLInputElement).value).toBe('0.65')
    expect((wrapper.get('#edge-margin-threshold').element as HTMLInputElement).value).toBe('0.2')
    expect(
      (wrapper.get('#edge-calibration-reference').element as HTMLInputElement).value,
    ).toContain('DEFAULT-AMAN-SEMENTARA')
    expect(wrapper.text()).toContain('Preset sementara aktif')
    expect(wrapper.text()).toContain('harus ada sesi aktif dengan siswa terdaftar di roster')
    wrapper.unmount()
  })

  it('publishes the test preset only after the admin submits it', async () => {
    const wrapper = mountAiSetup()
    await flushPromises()
    await wrapper.get('[aria-label="Kelompok pengaturan"] button:nth-child(2)').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="edge-default-preset"]').trigger('click')

    expect(api.saveEdgeDeviceConfiguration).not.toHaveBeenCalled()
    await wrapper.get('form.ai-setup-view__form').trigger('submit')
    await flushPromises()

    expect(api.saveEdgeDeviceConfiguration).toHaveBeenCalledWith(
      edgeDevice.device_id,
      expect.objectContaining({
        min_top1_similarity: 0.65,
        min_top1_top2_margin: 0.2,
        yunet_score_threshold: 0.9,
        yunet_nms_threshold: 0.3,
        minimum_agreeing_frames: 3,
        sample_every_n_frames: 5,
        best_frame_count: 5,
        max_history_frames: 10,
      }),
    )
    wrapper.unmount()
  })
})
