# 09 — Early Warning System (EWS)

## 9.1 Status: tahap 1 SUDAH berjalan (F-10)

Watchlist "Siswa perlu perhatian" — human watchlist, **bukan sanksi, tanpa
notifikasi**. Bukti: `GET /reports/attendance/at-risk[/policy]`, panel
`DashboardView` (`data-testid="at-risk-panel"`), endpoint tindak lanjut
`GET/POST /reports/attendance/at-risk/{student_id}/follow-ups` (+ `PATCH
…/follow-ups/{follow_up_id}`), drawer EWS di `EwsView`. Tindak lanjut
(U-02) SUDAH menjadi bagian F-10 berjalan (bukan usulan).

```mermaid
flowchart TD
  S([Buka panel atau API at-risk]) --> P{Policy tersimpan?}
  P -- Tidak --> D0[Pakai default: 30 hari + 20 persen + 3x]
  P -- Ya --> P1[Pakai policy revisi terakhir + audit]
  D0 --> W
  P1 --> W[Override opsional via query tervalidasi]
  W --> G[Agregat sesi non-cancelled dalam jendela]
  G --> R{absence_pct >= ambang ATAU late >= ambang?}
  R -- Tidak --> B[Tidak masuk daftar]
  R -- Ya --> F[Flag + reasons + ambang efektif + policy_revision]
  F --> E([Tindak lanjut manual di luar sistem])
  B --> E
```

Aturan agregat (terverifikasi `reports.py`): `cancelled` dikecualikan; sesi
closed tanpa record = absen (pakai `closed_at`/`recorded_at`/`opened_at`
berurutan); sesi open tanpa record = `not_recorded`, tidak dihitung absen;
`excused` bukan absen; guru hanya melihat jadwal miliknya; urut
absence_pct desc → late desc → nama; paginasi in-memory; respons selalu
menggemakan ambang efektif + revisi agar flag bisa dijelaskan.

## 9.2 Usulan tahap 2 (U-01, U-03–U-04) — tanpa ubah arsitektur

> U-02 (riwayat tindak lanjut) SUDAH jalan sebagai F-10 — tersisa U-01
> (berita acara kalibrasi ambang), U-03 (notifikasi in-app), U-04 (eskalasi).

```mermaid
flowchart TD
  F([Flag at-risk]) --> N{Ambang hasil kalibrasi sekolah? U-01}
  N -- Belum --> BA[Berita acara kalibrasi]
  BA --> N
  N -- Sudah --> T[Tindak lanjut U-02: pemanggilan-konseling-surat-selesai]
  T --> G1{Guru tangani?}
  G1 -- Ya --> S1[Catat stage + note beraudit]
  G1 -- Tidak --> ES[Eskalasi U-04: wali kelas lalu BK]
  ES --> S1
  S1 --> NT{Kirim notifikasi U-03?}
  NT -- Ya --> IN[In-app; kanal luar hanya bila sekolah opt-in]
  NT -- Tidak --> DONE([Selesai dicatat])
  IN --> DONE
```

Skema berjalan (`ews_follow_ups`, via migrasi Alembic; DDL penuh di
`schema-erd.sql`):

```sql
CREATE TABLE ews_follow_ups (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id     UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  author_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  status         VARCHAR(16) NOT NULL DEFAULT 'open' CHECK (status IN ('open','done')),
  resolved_at    TIMESTAMPTZ,
  note           TEXT NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Bukan tujuan: sanksi otomatis, blokir presensi, notifikasi eksternal default,
skor risiko yang tidak bisa dijelaskan.
