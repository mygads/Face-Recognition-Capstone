# 07 — Data dan Class Diagram

> Class diagram di bawah digambar **per fitur**. Nama atribut disalin dari
> `apps/api/src/presensi_api/db/models.py` dan diverifikasi terhadap
> `docs/proposal/schema-erd.sql`. Nilai sensitif (password hash, credential
> hash, embedding terenkripsi, token) tersimpan sebagai hash/enkripsi dan
> **tidak dipajang** sebagai data operasional; raw image tidak disimpan.
> Kelas di luar fokus fitur diulang minimal agar tiap gambar mandiri;
> definisi penuh lihat diagram fiturnya. `created_at`/`updated_at` teknis
> dihilangkan kecuali relevan secara domain (expiry, revoke, record, audit).
> ERD lengkap: render
> [schema-erd.sql](schema-erd.sql) (18 tabel, tanpa data).

## 7.1 Akun dan otorisasi (F-01, F-13)

```mermaid
classDiagram
  class User {
    +UUID id
    +String email
    +String full_name
    +bool is_active
    +bool must_change_password
    +String opening_mode
  }
  class Role {
    +String code
    +String name
  }
  class UserRole {
    +UUID user_id
    +UUID role_id
    +UUID granted_by_user_id
  }
  class AuthSession {
    +UUID id
    +UUID user_id
    +DateTime created_at
    +DateTime expires_at
    +DateTime last_used_at
    +DateTime revoked_at
  }
  User "1" -- "*" UserRole : memiliki
  Role "1" -- "*" UserRole : dipakai
  User "1" -- "*" AuthSession : sesi login
```

`opening_mode` ∈ {manual, automatic} via CHECK (konsisten 03/F-05:
worker auto-open vs guru manual). `granted_by_user_id` nullable
(pemberi role boleh sistem).

## 7.2 Master siswa, kelas, lab (F-02, F-04)

```mermaid
classDiagram
  class Student {
    +String student_number
    +String full_name
    +bool is_active
  }
  class SchoolClass {
    +String code
    +String name
    +int grade
    +String academic_year
    +UUID homeroom_teacher_id
    +bool is_active
  }
  class ClassStudent {
    +UUID class_id
    +UUID student_id
    +DateTime enrolled_at
  }
  class Laboratory {
    +String code
    +String name
    +String location
    +bool is_active
  }
  class PracticumSchedule {
    +String subject
    +int weekday
    +Time start_time
    +Time end_time
    +String timezone_name
    +Date effective_from
    +Date effective_through
    +bool is_active
  }
  class User {
    +UUID id
    +String full_name
  }
  SchoolClass "1" -- "*" ClassStudent : roster
  Student "1" -- "*" ClassStudent : anggota
  SchoolClass "1" -- "*" PracticumSchedule : dijadwalkan
  Laboratory "1" -- "*" PracticumSchedule : dipakai
  User "1" -- "*" PracticumSchedule : diajar guru
  User "1" -- "0..*" SchoolClass : wali kelas (nullable)
```

`homeroom_teacher_id` nullable → `users` (eskalasi wali kelas U-04,
konsisten 03); `location` dan `effective_through` nullable.

## 7.3 Enrollment wajah (F-03)

```mermaid
classDiagram
  class FaceTemplate {
    +UUID student_id
    +UUID enrollment_batch_id
    +int embedding_dimension
    +String model_name
    +String model_version
    +JSON quality_metadata
    +UUID created_by_user_id
    +DateTime revoked_at
    +UUID revoked_by_user_id
    +revoke()
  }
  class Student {
    +String student_number
    +String full_name
  }
  class User {
    +UUID id
    +String full_name
  }
  Student "1" -- "*" FaceTemplate : maks 5 aktif
  User "1" -- "0..*" FaceTemplate : dibuat/mencabut (nullable)
```

Embedding tersimpan **terenkripsi (AES-256-GCM)** beserta `model
name/version` wajib; tanpa raw image; kolom hash/sandi tidak dipajang.
Batas 5 template aktif per siswa ditegakkan di API (`MAX_STORED_TEMPLATES
= 5`, `enrollment_templates.py`).

## 7.4 Sesi dan keputusan presensi (F-05, F-06, F-07)

```mermaid
classDiagram
  class AttendanceSession {
    +UUID id
    +UUID practicum_schedule_id
    +UUID opened_by_user_id
    +String status
    +DateTime opened_at
    +DateTime closed_at
    +int grace_period_minutes
  }
  class SessionStudent {
    +String student_number_snapshot
    +String full_name_snapshot
    +DateTime snapshot_taken_at
  }
  class RecognitionEvent {
    +UUID event_uuid
    +UUID session_id
    +UUID device_id
    +UUID recognized_student_id
    +DateTime occurred_at
    +String outcome
    +Decimal similarity
    +Decimal confidence
    +Decimal margin
    +String model_name
    +String model_version
    +JSON quality_metadata
  }
  class AttendanceRecord {
    +UUID session_id
    +UUID student_id
    +UUID recognition_event_id
    +UUID recorded_by_user_id
    +String status
    +String source
    +DateTime recorded_at
  }
  class AttendanceCorrection {
    +UUID attendance_record_id
    +UUID requested_by_user_id
    +String previous_status
    +String corrected_status
    +String reason
    +String decision_status
    +String decision_note
    +UUID decided_by_user_id
    +DateTime decided_at
  }
  class Device {
    +String device_type
    +String deployment_profile
  }
  class Student {
    +String student_number
    +String full_name
  }
  PracticumSchedule "1" -- "*" AttendanceSession : diinstansiasi
  AttendanceSession "1" -- "*" SessionStudent : snapshot immutable
  AttendanceSession "1" -- "*" RecognitionEvent : evidence
  AttendanceSession "1" -- "*" AttendanceRecord : keputusan
  Device "1" -- "*" RecognitionEvent : menangkap
  Student "1" -- "0..*" RecognitionEvent : dikenali (nullable)
  SessionStudent "1" -- "0..1" AttendanceRecord : FK roster
  RecognitionEvent "1" -- "0..1" AttendanceRecord : maks 1 record
  AttendanceRecord "1" -- "*" AttendanceCorrection : pending saja
```

`opened_by_user_id` **nullable** — worker auto-open berjalan tanpa guru
(konsisten 03/F-05, 06/state auto-open). `status` ∈ {active,
manual_override, closed, cancelled} (konsisten 05/06).
`recognized_student_id` nullable (wajib hanya bila `outcome = matched`);
`recognition_event_id` wajib bila `source = face_recognition`, NULL bila
`manual`/`system`; `recorded_by_user_id` nullable.

## 7.5 Perangkat dan konfigurasi (F-11, F-12)

```mermaid
classDiagram
  class Device {
    +String name
    +String device_type
    +String deployment_profile
    +bool is_active
    +String app_version
    +String model_version
    +String camera_status
    +bool camera_enabled
    +DateTime last_seen_at
    +DateTime credential_expires_at
    +int config_applied_revision
    +String config_apply_status
    +String config_error_code
  }
  class RuntimeConfigurationVersion {
    +String scope_key
    +int revision
    +JSON settings
    +UUID actor_user_id
    +DateTime created_at
  }
  class Laboratory {
    +String code
    +String name
  }
  class User {
    +UUID id
    +String full_name
  }
  Laboratory "1" -- "*" Device : terpasang
  User "1" -- "0..*" RuntimeConfigurationVersion : menerbitkan (nullable)
```

`device_type` ∈ {edge_pc, camera_gateway} terikat ke
`deployment_profile` ∈ {AI_EDGE, STB_GATEWAY} via CHECK. Kredensial
device tersimpan sebagai hash dan tidak dipajang; yang ditampilkan hanya
`credential_expires_at` operasional. `config_error_code` nullable dan hanya
terisi bila apply config gagal.

## 7.6 Laporan dan EWS (F-09, F-10, U-02)

```mermaid
classDiagram
  class RuntimeConfigurationVersion {
    +String scope_key
    +int revision
    +JSON settings
    +DateTime created_at
  }
  class AtRiskPolicy {
    +String scope_key
    +int revision
  }
  class Student {
    +String student_number
    +String full_name
  }
  class EwsFollowUp {
    +UUID student_id
    +UUID session_id
    +String stage
    +String note
    +UUID created_by_user_id
    +DateTime created_at
  }
  class AuditLog {
    +UUID actor_user_id
    +String action
    +String entity_type
    +UUID entity_id
    +UUID request_id
    +JSON before_state
    +JSON after_state
    +DateTime created_at
  }
  class User {
    +UUID id
    +String full_name
  }
  RuntimeConfigurationVersion "1" -- "0..1" AtRiskPolicy : scope attendance-at-risk-policy
  AtRiskPolicy ..> Student : menghitung flag
  Student "1" -- "0..*" EwsFollowUp : U-02 usulan (belum tabel)
  User "1" -- "0..*" AuditLog : aktor (nullable)
```

- `AtRiskPolicy` **bukan tabel mandiri** — view atas
  `runtime_configuration_versions` scope `attendance-at-risk-policy`
  (terverifikasi `AT_RISK_POLICY_SCOPE` di `runtime_configuration.py`);
  ambang (`window_days`, `absence_pct_threshold`,
  `late_count_threshold`) tersimpan di `settings` JSONB + `revision`
  beraudit (konsisten 09: default 30 hari + 20 persen + 3x bila policy
  belum tersimpan).
- `EwsFollowUp` (U-02, tabel usulan `ews_follow_ups`) **belum ada di
  database berjalan** — DDL masih komentar di `schema-erd.sql`, perlu
  migrasi Alembic bila diimplementasikan (konsisten 03/U-02, 09).
- `actor_user_id` nullable (aksi sistem OK); `request_id`,
  `before_state`/`after_state` nullable.

## 7.7 Ringkasan 18 tabel (untuk Bab "Perancangan Basis Data")

| Tabel | Peran |
|---|---|
| users, roles, user_roles, auth_sessions | Akun, role, sesi login |
| students, classes, class_students | Master + roster kelas |
| laboratories, devices | Lab + registry perangkat |
| runtime_configuration_versions | Policy berversi (AI config, ambang EWS) + penerbit |
| practicum_schedules | Jadwal mingguan |
| attendance_sessions, session_students | Sesi + snapshot roster immutable |
| face_templates | Embedding terenkripsi + model name/version |
| recognition_events | Bukti audit (matched/ambiguous/no_match/error/redacted) |
| attendance_records | Keputusan final (present/late/absent/excused) |
| attendance_corrections | Pengajuan koreksi pending |
| audit_logs | Jejak aksi |

Aturan keras: `attendance_records(session_id, student_id)` unik; record
face_recognition wajib menunjuk event; record manual/system tidak boleh
menunjuk event; satu event maksimal satu record; FK record →
`session_students` menjamin siswa di snapshot. DDL usulan EWS
(`ews_follow_ups`) tetap proposal di luar 18 tabel.
