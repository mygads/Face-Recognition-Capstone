"""Audit konsistensi paket docs/diagrams (sumber: .puml + proposal).

Cara pakai: py _gen/audit_diagrams.py  ->  exit 0 bila bersih.
Memeriksa: struktur puml, integritas referensi BPMN/Draw.io/XMI,
kecocokan hitungan antar format, dan kelengkapan 1-per-1.
"""
import glob
import os
import re
import sys
import xml.dom.minidom as DOM

BASE = os.path.dirname(os.path.abspath(__file__))
D = os.path.abspath(os.path.join(BASE, ".."))
PUML = os.path.join(D, "plantuml")
issues = []


def err(msg):
    issues.append(msg)


def ids_of_puml_usecase():
    out = set()
    for ln in open(os.path.join(PUML, "uc-00-overall.puml"), encoding="utf-8"):
        m = re.match(r'\s*usecase\s+"[^"]+"\s+as\s+(\w+)\s*$', ln)
        if m:
            out.add(m.group(1))
    return out


def classes_of(path):
    cls, n_assoc = {}, 0
    cur = None
    for raw in open(path, encoding="utf-8"):
        ln = raw.strip()
        m = re.match(r'class\s+(\w+)\s*\{\s*$', ln)
        if m:
            cur = m.group(1)
            cls.setdefault(cur, [])
            continue
        if ln == "}":
            cur = None
            continue
        if cur and ln:
            cls[cur].append(ln)
            continue
        if re.match(r'^\w+\s*("[^"]*"\s*)?(-{2,}>|\.{2,}>|<\.+|<-{2,}|\*--|o--|-{2})\s*', ln):
            n_assoc += 1
    return cls, n_assoc


def main():
    # ---- 1. plantuml ----
    pumls = sorted(glob.glob(os.path.join(PUML, "*.puml")))
    for p in pumls:
        t = open(p, encoding="utf-8").read()
        if t.count("@startuml") != 1 or t.count("@enduml") != 1:
            err("puml marker rusak: %s" % os.path.basename(p))
        if "\t" in t:
            err("puml mengandung tab: %s" % os.path.basename(p))
    print("plantuml files: %d" % len(pumls))

    # ---- 2. mermaid vs proposal ----
    src = os.path.abspath(os.path.join(D, "..", "proposal"))
    total = 0
    for fname in sorted(os.listdir(src)):
        if not fname.endswith(".md"):
            continue
        text = open(os.path.join(src, fname), encoding="utf-8").read()
        blocks = re.findall(r"```mermaid\n(.*?)\n```", text, re.S)
        stem = fname[:-3]
        got = sorted(glob.glob(os.path.join(D, "mermaid", stem + "-*.mmd")))
        if len(blocks) != len(got):
            err("mermaid tak lengkap: %s blok=%d file=%d"
                % (stem, len(blocks), len(got)))
        for i, b in enumerate(blocks, 1):
            f = os.path.join(D, "mermaid", "%s-%02d.mmd" % (stem, i))
            if os.path.exists(f):
                body = open(f, encoding="utf-8").read()
                if b.strip() not in body:
                    err("isi mmd beda dari proposal: %s" % os.path.basename(f))
                if len(b.strip()) == 0:
                    err("mmd kosong: %s" % os.path.basename(f))
        total += len(blocks)
    print("mermaid blocks/files: %d" % total)

    # ---- 3. BPMN ----
    bpmns = sorted(glob.glob(os.path.join(D, "bpmn", "*.bpmn")))
    for b in bpmns:
        name = os.path.basename(b)
        doc = DOM.parse(b)
        proc = doc.getElementsByTagName("process")[0]
        node_ids, flows, starts = {}, {}, 0
        for tag in ("startEvent", "endEvent", "task",
                    "exclusiveGateway", "parallelGateway"):
            for el in proc.getElementsByTagName(tag):
                node_ids[el.getAttribute("id")] = tag
                if tag == "startEvent":
                    starts += 1
                if tag == "exclusiveGateway" and \
                        el.getAttribute("gatewayDirection") != "Exclusive":
                    err("%s: xg tanpa gatewayDirection: %s"
                        % (name, el.getAttribute("id")))
        for el in proc.getElementsByTagName("sequenceFlow"):
            fid = el.getAttribute("id")
            flows[fid] = (el.getAttribute("sourceRef"),
                          el.getAttribute("targetRef"))
        for fid, (a, c) in flows.items():
            if a not in node_ids:
                err("%s: sourceRef hilang %s -> %s" % (name, fid, a))
            if c not in node_ids:
                err("%s: targetRef hilang %s -> %s" % (name, fid, c))
        refs = set()
        for nid, tag in node_ids.items():
            for el in proc.getElementsByTagName("*"):
                if el.getAttribute("id") != nid:
                    continue
                inc = [x.firstChild.data for x in
                       el.getElementsByTagName("incoming") if x.firstChild]
                out = [x.firstChild.data for x in
                       el.getElementsByTagName("outgoing") if x.firstChild]
                for f in inc + out:
                    if f not in flows:
                        err("%s: ref flow tak ada %s.%s" % (name, nid, f))
                    refs.add(f)
                if tag == "startEvent" and inc:
                    err("%s: start punya incoming: %s" % (name, nid))
                if tag == "endEvent" and out:
                    err("%s: end punya outgoing: %s" % (name, nid))
                if tag not in ("startEvent",) and not inc:
                    err("%s: node tanpa incoming: %s" % (name, nid))
                if tag not in ("endEvent",) and not out:
                    err("%s: node tanpa outgoing: %s" % (name, nid))
        for fid in flows:
            if fid not in refs:
                err("%s: flow yatim %s" % (name, fid))
        if starts == 0:
            err("%s: tanpa startEvent" % name)
        if name != "f11-device.bpmn" and starts > 1:
            err("%s: %d startEvent" % (name, starts))
        lanes = doc.getElementsByTagName("lane")
        if lanes:
            covered = set()
            for el in doc.getElementsByTagName("flowNodeRef"):
                if el.firstChild:
                    covered.add(el.firstChild.data)
            for nid, tag in node_ids.items():
                if tag not in ("startEvent", "endEvent") and \
                        nid not in covered:
                    err("%s: node di luar lane: %s" % (name, nid))
    print("bpmn files: %d" % len(bpmns))

    # ---- 4. drawio ----
    draws = sorted(glob.glob(os.path.join(D, "drawio", "*.drawio")))
    for dr in draws:
        name = os.path.basename(dr)
        doc = DOM.parse(dr)
        cells = doc.getElementsByTagName("mxCell")
        vids = set(c.getAttribute("id") for c in cells
                   if c.getAttribute("vertex") == "1")
        for c in cells:
            if c.getAttribute("edge") == "1":
                for attr in ("source", "target"):
                    r = c.getAttribute(attr)
                    if r and r not in vids and not r.startswith("lab") \
                            and not r.startswith("srv"):
                        err("%s: edge ref hilang %s=%s" % (name, attr, r))
    print("drawio files: %d" % len(draws))

    # bpmn <-> drawio flow parity
    bnames = set(os.path.basename(b)[:-5] for b in bpmns)
    dflows = set(os.path.basename(x)[5:-7] for x in draws
                 if os.path.basename(x).startswith("flow-"))
    if bnames != dflows:
        err("bpmn/drawio flow tak par: %s" % (bnames ^ dflows))

    # ---- 5. XMI ----
    x = os.path.join(D, "xmi", "presensi-uml.xmi")
    doc = DOM.parse(x)
    xids = set()
    for el in doc.getElementsByTagName("*"):
        if el.hasAttribute("xmi:id"):
            i = el.getAttribute("xmi:id")
            if i in xids:
                err("xmi id ganda: %s" % i)
            xids.add(i)
    for el in doc.getElementsByTagName("*"):
        for attr in ("xmi:idref", "type"):
            if el.hasAttribute(attr):
                r = el.getAttribute(attr)
                if r.startswith("http"):
                    continue
                base = r.split("#")[-1]
                if base not in xids:
                    err("xmi ref hilang: %s" % r)
    cnt = {}
    for el in doc.getElementsByTagName("packagedElement"):
        cnt[el.getAttribute("xmi:type")] = \
            cnt.get(el.getAttribute("xmi:type"), 0) + 1
    exp = {"uml:Actor": 4, "uml:UseCase": 33, "uml:Association": 32 + 25,
           "uml:Dependency": 1, "uml:Include": 17, "uml:Extend": 8,
           "uml:Class": 20}
    for k, v in exp.items():
        if cnt.get(k, 0) != v:
            err("xmi %s = %d, harap %d" % (k, cnt.get(k, 0), v))
    print("xmi counts: %s" % cnt)

    # ---- 6. cross-check ----
    ucs = ids_of_puml_usecase()
    doc = DOM.parse(os.path.join(D, "drawio", "uc-overall.drawio"))
    d_ucs, e_assoc, e_dep = set(), 0, 0
    for c in doc.getElementsByTagName("mxCell"):
        style = c.getAttribute("style")
        if c.getAttribute("vertex") == "1" and "ellipse" in style:
            m = re.match(r"(\w+) ", c.getAttribute("value"))
            if m:
                d_ucs.add(m.group(1))
        if c.getAttribute("edge") == "1":
            v = c.getAttribute("value")
            if "include" in v or "extend" in v:
                e_dep += 1
            else:
                e_assoc += 1
    if d_ucs != ucs:
        err("uc drawio vs puml beda: %s" % (d_ucs ^ ucs))
    if e_assoc != 32 or e_dep != 25:
        err("uc drawio edge: assoc=%d dep=%d, harap 32/25" % (e_assoc, e_dep))
    xdoc = DOM.parse(x)
    x_ucs = set(el.getAttribute("xmi:id")[2:] for el in
                xdoc.getElementsByTagName("packagedElement")
                if el.getAttribute("xmi:type") == "uml:UseCase")
    if x_ucs != ucs:
        err("uc xmi vs puml beda: %s" % (x_ucs ^ ucs))
    all_cls = {}
    for path in sorted(glob.glob(os.path.join(PUML, "class-*.puml"))):
        cls, na = classes_of(path)
        stem = os.path.basename(path)[:-5]
        ddoc = DOM.parse(os.path.join(D, "drawio", stem + ".drawio"))
        boxes = [c for c in ddoc.getElementsByTagName("mxCell")
                 if c.getAttribute("vertex") == "1"]
        if len(boxes) != len(cls):
            err("%s: box drawio=%d class puml=%d" % (stem, len(boxes),
                                                    len(cls)))
        dedges = [c for c in ddoc.getElementsByTagName("mxCell")
                  if c.getAttribute("edge") == "1"]
        if len(dedges) != na:
            err("%s: edge drawio=%d assoc puml=%d" % (stem, len(dedges), na))
        for cn, attrs in cls.items():
            cur = all_cls.setdefault(cn, [])
            for a in attrs:
                if a not in cur:
                    cur.append(a)
    x_cls = set(el.getAttribute("name") for el in
                xdoc.getElementsByTagName("packagedElement")
                if el.getAttribute("xmi:type") == "uml:Class")
    if x_cls != set(all_cls):
        err("class xmi vs puml beda: %s" % (x_cls ^ set(all_cls)))

    # ---- 7. plantuml block balance ----
    for p in pumls:
        o = {"if": 0, "endif": 0, "repeat": 0, "repeatwhile": 0, "fork": 0,
             "forkagain": 0, "endfork": 0, "act": 0, "deact": 0, "note": 0,
             "endnote": 0, "other": []}
        for raw in open(p, encoding="utf-8"):
            ln = raw.strip()
            if re.match(r"^if(\s|$)", ln):
                o["if"] += 1
            elif re.match(r"^endif(\s|$)", ln):
                o["endif"] += 1
            elif ln.startswith("repeat while"):
                o["repeatwhile"] += 1
            elif re.match(r"^repeat(\s|$)", ln):
                o["repeat"] += 1
            elif re.match(r"^end fork(\s|$)", ln):
                o["endfork"] += 1
            elif re.match(r"^fork again(\s|$)", ln):
                o["forkagain"] += 1
            elif re.match(r"^fork(\s|$)", ln):
                o["fork"] += 1
            elif re.match(r"^end note(\s|$)", ln):
                o["endnote"] += 1
            elif re.match(r"^note(\s|$)", ln) and ":" not in ln:
                o["note"] += 1
            elif re.match(r"^activate(\s|$)", ln):
                o["act"] += 1
            elif re.match(r"^deactivate(\s|$)", ln):
                o["deact"] += 1
            elif re.match(r"^(loop|alt|opt|group|box|split|end box|"
                          r"end split|end)(\s|$)", ln):
                o["other"].append(ln[:28])
        nm = os.path.basename(p)
        for a, b in (("if", "endif"), ("repeat", "repeatwhile"),
                     ("fork", "endfork"), ("act", "deact"), ("note", "endnote")):
            if o[a] != o[b]:
                err("%s: %s=%d %s=%d" % (nm, a, o[a], b, o[b]))
        if o["fork"] and o["forkagain"] < 1:
            err("%s: fork tanpa cabang 'fork again'" % nm)
        if o["other"]:
            print("  info %s blok lain: %s" % (nm, o["other"]))

    # ---- 8. mermaid: direktif + keseimbangan kurung ----
    KNOWN = ("flowchart", "graph", "sequenceDiagram", "stateDiagram",
             "stateDiagram-v2", "classDiagram", "erDiagram")
    for f in sorted(glob.glob(os.path.join(D, "mermaid", "*.mmd"))):
        nm = os.path.basename(f)
        text = open(f, encoding="utf-8").read()
        lines = [l for l in text.splitlines()
                 if l.strip() and not l.strip().startswith("%%")]
        if not lines or lines[0].split()[0] not in KNOWN:
            err("%s: direktif diagram tak dikenal" % nm)
        body = re.sub(r'"[^"]*"', "", text)
        body = re.sub(r"%%.*", "", body)
        for a, b in (("(", ")"), ("[", "]"), ("{", "}")):
            if body.count(a) != body.count(b):
                err("%s: '%s'=%d vs '%s'=%d" % (nm, a, body.count(a),
                                                b, body.count(b)))

    # ---- 9. id use-case mermaid §4 vs puml ----
    TOK = re.compile(r"\b(UC\d+|PREV|QG|RB|CB|SR|MO|AO|DG|PI|SE|RF|WP|AG|"
                     r"U[234]|SC|ADM|TCH|LAB|DEV)\b")
    mu = set()
    for f in glob.glob(os.path.join(D, "mermaid", "04-use-case-*.mmd")):
        mu.update(TOK.findall(open(f, encoding="utf-8").read()))
    mu -= {"ADM", "TCH", "LAB", "DEV"}
    if mu != ucs:
        err("uc mermaid §4 vs puml beda: %s" % (mu ^ ucs))

    # ---- 10. xmi spot check ----
    ops = [el.getAttribute("name") for el in
           xdoc.getElementsByTagName("ownedOperation")]
    if "revoke" not in ops:
        err("xmi: operasi revoke() hilang")
    if not xdoc.getElementsByTagName("upperValue"):
        err("xmi: tanpa info multiplisitas")
    anames = set(el.getAttribute("name") for el in
                 xdoc.getElementsByTagName("packagedElement")
                 if el.getAttribute("xmi:type") == "uml:Actor")
    if anames != {"ADMIN", "TEACHER", "LABORANT", "DEVICE service"}:
        err("xmi aktor: %s" % anames)

    # ---- 11. setiap .puml menunjuk file proposal yang ada ----
    for p in pumls:
        head = "".join(open(p, encoding="utf-8").readlines()[:4])
        m = re.search(r"docs/proposal/([\w\-]+\.md)", head)
        if not m:
            err("%s: tanpa referensi proposal" % os.path.basename(p))
        elif not os.path.exists(os.path.join(src, m.group(1))):
            err("%s: referensi proposal hilang %s" % (os.path.basename(p),
                                                      m.group(1)))

    if issues:
        print("\nTEMUAN (%d):" % len(issues))
        for i in issues:
            print(" -", i)
        return 1
    print("\nAUDIT BERSIH: semua format konsisten 1-per-1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
