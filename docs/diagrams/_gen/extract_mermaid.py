"""Ekstrak semua blok ```mermaid dari docs/proposal menjadi file .mmd siap-import.

Cara pakai:  py _gen/extract_mermaid.py
Hasil:        docs/diagrams/mermaid/<nama-file>-<nn>.mmd
Import:       Draw.io > Arrange > Insert > Mermaid (paste isi file).
"""
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(BASE, "..", "..", "proposal"))
DST = os.path.abspath(os.path.join(BASE, "..", "mermaid"))

os.makedirs(DST, exist_ok=True)

count = 0
for fname in sorted(os.listdir(SRC)):
    if not fname.endswith(".md"):
        continue
    text = open(os.path.join(SRC, fname), encoding="utf-8").read()
    blocks = re.findall(r"```mermaid\n(.*?)\n```", text, re.S)
    stem = fname[:-3]
    for i, body in enumerate(blocks, 1):
        out = os.path.join(DST, "%s-%02d.mmd" % (stem, i))
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("%%%% sumber: docs/proposal/%s (blok mermaid #%d)\n" % (fname, i))
            fh.write(body.rstrip() + "\n")
        count += 1
        print("wrote", out)

print("total mermaid files:", count)
