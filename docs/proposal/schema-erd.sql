-- ============================================================================
-- SKEMA ERD — Sistem Presensi Face Recognition + EWS tahap 1
-- Disalin dari: apps/api/src/presensi_api/db/models.py (dokumentasi, TANPA data)
-- Cara pakai: buat database PostgreSQL kosong, jalankan file ini, lalu
-- reverse-engineer (DBeaver/pgAdmin) dan screenshot sebagai gambar ERD.
-- BUKAN migrasi Alembic — perubahan skema tetap lewat Alembic.
-- UUID memakai gen_random_uuid(); waktu memakai timestamptz (timezone-aware).
-- pgvector opsional dan tidak dipakai di DDL ini (embedding disimpan terenkripsi).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ----------------------------------------------------------------------------
-- Akun & otorisasi
-- ----------------------------------------------------------------------------
CREATE TABLE roles (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code          VARCHAR(50)  NOT NULL UNIQUE,          -- ADMIN | TEACHER | LABORANT
  name          VARCHAR(100) NOT NULL,
  description   VARCHAR(255),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email               VARCHAR(320) NOT NULL UNIQUE,
  full_name           VARCHAR(200) NOT NULL,
  password_hash       VARCHAR(255) NOT NULL,
  is_active           BOOLEAN NOT NULL DEFAULT TRUE,
  must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
  auth_token_version  INTEGER NOT NULL DEFAULT 0 CHECK (auth_token_version >= 0),
  opening_mode        VARCHAR(16) NOT NULL DEFAULT 'manual'
                      CHECK (opening_mode IN ('manual','automatic')),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_roles (
  user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id            UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  granted_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, role_id)
);
CREATE INDEX ix_user_roles_role_id ON user_roles(role_id);

CREATE TABLE auth_sessions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at  TIMESTAMPTZ NOT NULL,
  last_used_at TIMESTAMPTZ,
  revoked_at  TIMESTAMPTZ,
  CHECK (expires_at > created_at)
);
CREATE INDEX ix_auth_sessions_user_id_expires_at ON auth_sessions(user_id, expires_at);

-- ----------------------------------------------------------------------------
-- Master: siswa, kelas, lab
-- ----------------------------------------------------------------------------
CREATE TABLE students (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_number VARCHAR(32)  NOT NULL UNIQUE,   -- NIS
  full_name      VARCHAR(200) NOT NULL,
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE classes (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code              VARCHAR(32) NOT NULL,
  name              VARCHAR(120) NOT NULL,
  grade             SMALLINT NOT NULL CHECK (grade BETWEEN 1 AND 12),
  academic_year     VARCHAR(9) NOT NULL,          -- mis. 2025/2026
  homeroom_teacher_id UUID REFERENCES users(id) ON DELETE SET NULL,
  is_active         BOOLEAN NOT NULL DEFAULT TRUE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (code, academic_year)
);

CREATE TABLE class_students (
  class_id    UUID NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  student_id  UUID NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (class_id, student_id)
);
CREATE INDEX ix_class_students_student_id ON class_students(student_id);

CREATE TABLE laboratories (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code       VARCHAR(32)  NOT NULL UNIQUE,
  name       VARCHAR(120) NOT NULL,
  location   VARCHAR(200),
  is_active  BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- Perangkat (PC edge / STB gateway) — jenis terikat profil deployment
-- ----------------------------------------------------------------------------
CREATE TABLE devices (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  laboratory_id             UUID NOT NULL REFERENCES laboratories(id) ON DELETE RESTRICT,
  name                      VARCHAR(120) NOT NULL,
  device_type               VARCHAR(32) NOT NULL   -- edge_pc | camera_gateway
                            CHECK (device_type IN ('edge_pc','camera_gateway')),
  deployment_profile        VARCHAR(32) NOT NULL DEFAULT 'AI_EDGE'
                            CHECK (deployment_profile IN ('AI_EDGE','STB_GATEWAY')),
  is_active                 BOOLEAN NOT NULL DEFAULT TRUE,
  app_version               VARCHAR(80),
  model_version             VARCHAR(128),
  camera_status             VARCHAR(16) NOT NULL DEFAULT 'unknown'
                            CHECK (camera_status IN ('unknown','online','offline','error','disabled')),
  camera_enabled            BOOLEAN NOT NULL DEFAULT TRUE,
  latency_summary           JSONB,
  camera_metrics            JSONB,
  last_seen_at              TIMESTAMPTZ,
  credential_hash           VARCHAR(64),
  credential_expires_at     TIMESTAMPTZ,
  previous_credential_hash  VARCHAR(64),
  previous_credential_expires_at TIMESTAMPTZ,
  config_applied_revision   INTEGER NOT NULL DEFAULT 0 CHECK (config_applied_revision >= 0),
  config_apply_status       VARCHAR(16) NOT NULL DEFAULT 'not_configured'
                            CHECK (config_apply_status IN ('not_configured','pending','applied','error')),
  config_error_code         VARCHAR(64),
  config_applied_at         TIMESTAMPTZ,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (
    (device_type = 'edge_pc' AND deployment_profile = 'AI_EDGE') OR
    (device_type = 'camera_gateway' AND deployment_profile = 'STB_GATEWAY')
  )
);
CREATE INDEX ix_devices_laboratory_id ON devices(laboratory_id);
CREATE INDEX ix_devices_last_seen_at ON devices(last_seen_at);

-- Policy berversi (AI config + ambang EWS) — tanpa migrasi baru untuk tiap policy
CREATE TABLE runtime_configuration_versions (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_key  VARCHAR(160) NOT NULL,   -- mis. 'attendance-at-risk-policy'
  revision   INTEGER NOT NULL CHECK (revision >= 1),
  settings   JSONB NOT NULL,
  actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (scope_key, revision)
);

-- ----------------------------------------------------------------------------
-- Jadwal & sesi
-- ----------------------------------------------------------------------------
CREATE TABLE practicum_schedules (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  class_id        UUID NOT NULL REFERENCES classes(id) ON DELETE RESTRICT,
  laboratory_id   UUID NOT NULL REFERENCES laboratories(id) ON DELETE RESTRICT,
  teacher_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  subject         VARCHAR(120) NOT NULL,
  weekday         SMALLINT NOT NULL CHECK (weekday BETWEEN 0 AND 6),
  start_time      TIME NOT NULL,
  end_time        TIME NOT NULL,
  timezone_name   VARCHAR(64) NOT NULL,       -- mis. Asia/Jakarta
  effective_from  DATE NOT NULL,
  effective_through DATE,
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (start_time < end_time),
  CHECK (effective_through IS NULL OR effective_through >= effective_from)
);

CREATE TABLE attendance_sessions (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  practicum_schedule_id UUID NOT NULL REFERENCES practicum_schedules(id) ON DELETE RESTRICT,
  opened_by_user_id     UUID REFERENCES users(id) ON DELETE RESTRICT,
  status                VARCHAR(16) NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','manual_override','closed','cancelled')),
  opened_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at             TIMESTAMPTZ,
  grace_period_minutes  SMALLINT NOT NULL DEFAULT 15 CHECK (grace_period_minutes >= 0),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (closed_at IS NULL OR closed_at >= opened_at)
);
-- Satu sesi aktif per jadwal (partial unique di model; di SQL polos dibuat index):
CREATE INDEX ix_attendance_sessions_opened_at ON attendance_sessions(opened_at);

-- Snapshot roster: salinan NIS/nama saat sesi dibuka (immutable)
CREATE TABLE session_students (
  session_id             UUID NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
  student_id             UUID NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  student_number_snapshot VARCHAR(32)  NOT NULL,
  full_name_snapshot     VARCHAR(200) NOT NULL,
  snapshot_taken_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, student_id)
);
CREATE INDEX ix_session_students_student_id ON session_students(student_id);

-- ----------------------------------------------------------------------------
-- Biometrik: template terenkripsi (tanpa raw image)
-- ----------------------------------------------------------------------------
CREATE TABLE face_templates (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id           UUID NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  model_name           VARCHAR(120) NOT NULL,   -- mis. SFace
  model_version        VARCHAR(80)  NOT NULL,
  enrollment_batch_id  UUID NOT NULL DEFAULT gen_random_uuid(),
  embedding_ciphertext BYTEA,                   -- AES-256-GCM; NULL hanya bila revoked
  encryption_key_id    VARCHAR(80),
  embedding_dimension  SMALLINT CHECK (embedding_dimension IS NULL OR embedding_dimension > 0),
  quality_metadata     JSONB NOT NULL DEFAULT '{}',
  created_by_user_id   UUID REFERENCES users(id) ON DELETE SET NULL,
  revoked_at           TIMESTAMPTZ,
  revoked_by_user_id   UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (
    revoked_at IS NOT NULL OR
    (embedding_ciphertext IS NOT NULL AND encryption_key_id IS NOT NULL
     AND embedding_dimension IS NOT NULL AND embedding_dimension > 0)
  )
);

-- ----------------------------------------------------------------------------
-- Bukti audit vs keputusan final (INTI SKRIPSI: dua tabel berbeda)
-- ----------------------------------------------------------------------------
CREATE TABLE recognition_events (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_uuid           UUID NOT NULL UNIQUE,   -- idempotency key retry jaringan
  session_id           UUID NOT NULL REFERENCES attendance_sessions(id) ON DELETE RESTRICT,
  device_id            UUID NOT NULL REFERENCES devices(id) ON DELETE RESTRICT,
  recognized_student_id UUID REFERENCES students(id) ON DELETE SET NULL,
  occurred_at          TIMESTAMPTZ NOT NULL,   -- capture time (adil untuk grace)
  outcome              VARCHAR(16) NOT NULL    -- matched|ambiguous|no_match|error|redacted
                       CHECK (outcome IN ('matched','ambiguous','no_match','error','redacted')),
  model_name           VARCHAR(120) NOT NULL,
  model_version        VARCHAR(80)  NOT NULL,
  confidence           NUMERIC(7,6)  CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  similarity           NUMERIC(8,6)  CHECK (similarity IS NULL OR (similarity >= -1 AND similarity <= 1)),
  margin               NUMERIC(7,6)  CHECK (margin IS NULL OR (margin >= 0 AND margin <= 1)),
  quality_metadata     JSONB NOT NULL DEFAULT '{}',
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (outcome != 'matched' OR recognized_student_id IS NOT NULL)
);

CREATE TABLE attendance_records (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id            UUID NOT NULL,
  student_id            UUID NOT NULL,
  recognition_event_id  UUID UNIQUE REFERENCES recognition_events(id) ON DELETE RESTRICT,
  recorded_by_user_id   UUID REFERENCES users(id) ON DELETE SET NULL,
  status                VARCHAR(16) NOT NULL   -- present|late|absent|excused
                        CHECK (status IN ('present','late','absent','excused')),
  source                VARCHAR(24) NOT NULL   -- face_recognition|manual|system
                        CHECK (source IN ('face_recognition','manual','system')),
  recorded_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, student_id),              -- anti penitipan/duplikat
  FOREIGN KEY (session_id, student_id)
    REFERENCES session_students(session_id, student_id) ON DELETE RESTRICT,
  CHECK (
    (source = 'face_recognition' AND recognition_event_id IS NOT NULL) OR
    (source IN ('manual','system') AND recognition_event_id IS NULL)
  )
);

CREATE TABLE attendance_corrections (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  attendance_record_id UUID NOT NULL REFERENCES attendance_records(id) ON DELETE RESTRICT,
  requested_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  decided_by_user_id   UUID REFERENCES users(id) ON DELETE RESTRICT,
  previous_status      VARCHAR(16) NOT NULL CHECK (previous_status IN ('present','late','absent','excused')),
  corrected_status     VARCHAR(16) NOT NULL CHECK (corrected_status IN ('present','late','absent','excused')),
  reason               TEXT NOT NULL CHECK (length(trim(reason)) > 0),
  decision_status      VARCHAR(16) NOT NULL DEFAULT 'pending'
                       CHECK (decision_status IN ('pending','approved','rejected')),
  decision_note        TEXT,
  decided_at           TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_logs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  action        VARCHAR(100) NOT NULL,
  entity_type   VARCHAR(100) NOT NULL,
  entity_id     UUID NOT NULL,
  request_id    UUID,
  before_state  JSONB,
  after_state   JSONB,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- USULAN EWS tahap 2 (belum diimplementasikan — perlu migrasi Alembic bila jadi)
-- ----------------------------------------------------------------------------
-- CREATE TABLE ews_follow_ups (
--   id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
--   student_id     UUID NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
--   session_id     UUID REFERENCES attendance_sessions(id) ON DELETE SET NULL,
--   stage          VARCHAR(32) NOT NULL,  -- pemanggilan|konseling|surat|selesai
--   note           TEXT NOT NULL,
--   created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
--   created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
-- );
