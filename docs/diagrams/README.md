# Diagram Siap-Import — Sistem Presensi Praktikum Face Recognition

Seluruh diagram proposal dalam 5 format siap-import. Sumber kebenaran teks:
[docs/proposal/](../proposal/) (§2–§10) dan `schema-erd.sql` untuk ERD/DDL.

| Format | Folder | Jumlah | Dibuka dengan |
|---|---|---|---|
| PlantUML | [plantuml/](plantuml/) | 33 `.puml` | Visual Paradigm, Draw.io (plugin PlantUML), plantuml.jar |
| Mermaid | [mermaid/](mermaid/) | 36 `.mmd` | Draw.io → Arrange → Insert → Mermaid (paste isi file) |
| BPMN 2.0 | [bpmn/](bpmn/) | 17 `.bpmn` | Visual Paradigm (Import XML), Draw.io (Open) |
| XMI 2.5 | [xmi/](xmi/) | 1 `presensi-uml.xmi` | Visual Paradigm (Import XMI): aktor + 33 use case + asosiasi + include/extend + 20 class + atribut + relasi |
| Draw.io | [drawio/](drawio/) | 25 `.drawio` | Draw.io (Open) |
| SQL DDL (ERD) | `../proposal/schema-erd.sql` | 18 `CREATE TABLE` | Draw.io → Arrange → Insert → SQL (paste DDL) |

Generator (jangan edit hasil generate manual — ubah `.puml`/proposal lalu regenerate):

```bash
py docs/diagrams/_gen/extract_mermaid.py  # .mmd dari blok mermaid proposal
py docs/diagrams/_gen/gen_flows.py        # .bpmn + flow-*.drawio (F-01–F-13, end-to-end, EWS tahap 2)
py docs/diagrams/_gen/gen_struct.py       # uc/class/container .drawio + .xmi (parse .puml)
```

## Isi per folder

- `plantuml/`: `uc-00` overall + `uc-01..05` per role · `act-f01..f13` + `f14-roles` + `prototype` ·
  `class-01..06` · `seq-01..03` · `state-01..02` · `deployment-container`.
- `mermaid/`: salinan 1-per-1 semua blok mermaid proposal, nama `\<file proposal>-\<nn>.mmd`.
- `bpmn/`: F-01–F-13, `f14-roles` (§5.14), `prototype-method` (§2.1),
  `e2e-business` (§6.1, memakai lane), `ews-stage2` (§9.2 usulan).
- `drawio/`: `flow-*` (17 alur), `uc-overall`, `class-01..06`, `deployment-container`.
- `xmi/`: satu model UML (4 aktor, 33 use case, 32 asosiasi aktor, 18 include, 6 extend, 20 class unik gabungan, 26 relasi class).

## Catatan import

- Posisi node `.drawio`/`.bpmn` hasil generate adalah layout otomatis yang valid —
  rapikan dengan Arrange → Layout di Draw.io bila perlu; semantik (node, edge, label, guard) sudah 1-per-1 dengan Mermaid proposal.
- `class-*.drawio` menampilkan atribut esensial per diagram; definisi kolom penuh ada di `schema-erd.sql` + §7.
- Threshold recognition tidak ada di diagram mana pun (disengaja): wajib kalibrasi dari benchmark lokal —
  `MANUAL HARDWARE TEST REQUIRED` untuk threshold, latency walk-through vs frontal, dan deployment-benchmark.
