"""Generate Draw.io struktur + XMI 2.5 dari file .puml (sumber tunggal kebenaran).

Sumber : docs/diagrams/plantuml/uc-00-overall.puml,
         class-*.puml, deployment-container.puml
Cara   : py _gen/gen_struct.py
Hasil  : drawio/uc-overall.drawio, drawio/class-*.drawio,
         drawio/deployment-container.drawio, xmi/presensi-uml.xmi
"""
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
PUML = os.path.abspath(os.path.join(BASE, "..", "plantuml"))
DRAWIO_DIR = os.path.abspath(os.path.join(BASE, "..", "drawio"))
XMI_DIR = os.path.abspath(os.path.join(BASE, "..", "xmi"))
os.makedirs(DRAWIO_DIR, exist_ok=True)
os.makedirs(XMI_DIR, exist_ok=True)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def nl(s):
    return esc(s.replace("\\n", "\n")).replace("\n", "&#10;")


def read(name):
    with open(os.path.join(PUML, name), encoding="utf-8") as fh:
        return fh.read().splitlines()


# ---------- parser use-case ----------
def parse_uc(lines):
    actors, ucs, assoc, inc, ext = {}, {}, [], [], []
    for ln in (l.strip() for l in lines):
        m = re.match(r'actor\s+(?:"([^"]+)"\s+as\s+(\w+)|(\w+)\s+as\s+(\w+)|(\w+))\s*$', ln)
        if m:
            aid = m.group(2) or m.group(4) or m.group(5)
            actors[aid] = m.group(1) or m.group(3) or aid
            continue
        m = re.match(r'usecase\s+"([^"]+)"\s+as\s+(\w+)$', ln)
        if m:
            raw = m.group(1).replace("\\n", " ")
            uid = m.group(2)
            # Normalisasi: label puml UC1..UC16 sudah mengandung ID
            # ("UC1 Login ...") -> simpan bare desc agar prefix ID
            # ditambahkan tepat satu kali saat emit drawio/XMI.
            if raw == uid:
                bare = ""
            elif raw.startswith(uid + " "):
                bare = raw[len(uid) + 1:]
            else:
                bare = raw
            ucs[uid] = bare
            continue
        m = re.match(r'(\w+)\s*--\s*(\w+)$', ln)
        if m:
            assoc.append((m.group(1), m.group(2)))
            continue
        m = re.match(r'(\w+)\s*\.\.>\s*(\w+)\s*:\s*<<(include|extend)>>$', ln)
        if m:
            (inc if m.group(3) == "include" else ext).append(
                (m.group(1), m.group(2)))
    return actors, ucs, assoc, inc, ext


# ---------- parser class ----------
CLS_RE = re.compile(
    r'^(\w+)\s*(?:"([^"]*)"\s*)?(--+>|\.\.+>|<\.\.+|<--+|\*--|o--|--)\s*'
    r'(?:"([^"]*)"\s*)?(\w+)\s*(?::\s*(.+))?\s*$')


def parse_class(lines):
    classes, assocs, cur = {}, [], None
    for raw in lines:
        ln = raw.strip()
        m = re.match(r'class\s+(\w+)\s*\{\s*$', ln)
        if m:
            cur = m.group(1)
            classes.setdefault(cur, [])
            continue
        if ln == "}" and cur:
            cur = None
            continue
        if cur and ln:
            classes[cur].append(ln)
            continue
        m = CLS_RE.match(ln)
        if m:
            a, ma, op, mb, b, lab = (m.group(1), m.group(2) or "",
                                     m.group(3), m.group(4) or "",
                                     m.group(5), (m.group(6) or "").strip())
            assocs.append((a, ma, b, mb, lab, op.startswith(".")))
    return classes, assocs


# ---------- parser deployment ----------
def parse_deploy(lines):
    elems, edges, container, cmap = {}, [], None, {}
    for ln in (l.strip() for l in lines):
        m = re.match(r'node\s+"([^"]+)"\s*\{\s*$', ln)
        if m:
            container = m.group(1)
            continue
        if ln == "}":
            container = None
            continue
        m = re.match(r'(component|database)\s+"([^"]+)"\s+as\s+(\w+)$', ln)
        if m:
            elems[m.group(3)] = (m.group(1), m.group(2).replace("\\n", "\n"))
            cmap[m.group(3)] = container
            continue
        m = re.match(r'(\w+)\s*(<--?>|--+>)\s*(\w+)(?:\s*:\s*(.+))?$', ln)
        if m:
            edges.append((m.group(1), m.group(2), m.group(3),
                          (m.group(4) or "").strip()))
    return elems, edges, cmap


# ---------- drawio helpers ----------
def dhead(name):
    return ('<mxfile><diagram id="D_%s" name="%s"><mxGraphModel dx="0" dy="0" '
            'grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
            'fold="1" page="1" pageScale="1" pageWidth="1600" pageHeight="1200">'
            '<root><mxCell id="0"/><mxCell id="1" parent="0"/>' % (name, esc(name)))


DTAIL = '</root></mxGraphModel></diagram></mxfile>'

UC_STYLE = ("ellipse;whiteSpace=wrap;html=1;fontSize=12;")
ACT_STYLE = ("shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;"
             "html=1;fontSize=12;")
ASSOC_STYLE = "endArrow=none;html=1;fontSize=11;"
DEP_STYLE = "dashed=1;endArrow=open;html=1;fontSize=11;"


def drawio_uc(actors, ucs, assoc, inc, ext):
    L = [dhead("UC Overall")]
    ids, i = {}, 0
    for r, (aid, alab) in enumerate(actors.items()):
        ids[aid] = "v%d" % i
        i += 1
        L.append('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
                 '<mxGeometry x="40" y="%d" width="70" height="100" as="geometry"/>'
                 '</mxCell>' % (ids[aid], nl(alab), ACT_STYLE, 60 + r * 150))
    names = list(ucs)
    for c, uid in enumerate(names):
        col, row = c % 5, c // 5
        ids[uid] = "v%d" % i
        i += 1
        L.append('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
                 '<mxGeometry x="%d" y="%d" width="180" height="75" '
                 'as="geometry"/></mxCell>'
                 % (ids[uid], nl(uid + " " + ucs[uid]) if ucs[uid] else nl(uid),
                    UC_STYLE,
                    220 + col * 210, 40 + row * 120))
    e = 0
    for a, b in assoc:
        if a in ids and b in ids:
            L.append('<mxCell id="e%d" style="%s" edge="1" parent="1" '
                     'source="%s" target="%s">'
                     '<mxGeometry relative="1" as="geometry"/></mxCell>'
                     % (e, ASSOC_STYLE, ids[a], ids[b]))
            e += 1
    for a, b in inc:
        L.append('<mxCell id="e%d" value="&lt;&lt;include&gt;&gt;" style="%s" '
                 'edge="1" parent="1" source="%s" target="%s">'
                 '<mxGeometry relative="1" as="geometry"/></mxCell>'
                 % (e, DEP_STYLE, ids[a], ids[b]))
        e += 1
    for a, b in ext:
        L.append('<mxCell id="e%d" value="&lt;&lt;extend&gt;&gt;" style="%s" '
                 'edge="1" parent="1" source="%s" target="%s">'
                 '<mxGeometry relative="1" as="geometry"/></mxCell>'
                 % (e, DEP_STYLE, ids[a], ids[b]))
        e += 1
    L.append(DTAIL)
    return "\n".join(L) + "\n"


def drawio_class(stem, classes, assocs):
    L = [dhead("Class " + stem)]
    names = list(classes)
    box, i = {}, 0
    for c, cn in enumerate(names):
        col, row = c % 3, c // 3
        body = "&#10;".join(nl(a) for a in classes[cn])
        val = nl(cn) + "&#10;------&#10;" + body if body else nl(cn)
        h = 40 + 18 * max(len(classes[cn]), 1)
        vid = "v%d" % i
        i += 1
        box[cn] = vid
        L.append('<mxCell id="%s" value="%s" '
                 'style="rounded=1;whiteSpace=wrap;html=1;align=left;fontSize=11;" '
                 'vertex="1" parent="1"><mxGeometry x="%d" y="%d" width="260" '
                 'height="%d" as="geometry"/></mxCell>'
                 % (vid, val, 20 + col * 310, 20 + row * (h + 90), h))
    e = 0
    for a, ma, b, mb, lab, dashed in assocs:
        if a not in box or b not in box:
            continue
        mult = ("&#10;[%s..%s]" % (esc(ma), esc(mb))) if (ma or mb) else ""
        style = ("dashed=1;endArrow=open;html=1;fontSize=11;" if dashed
                 else "endArrow=none;html=1;fontSize=11;")
        L.append('<mxCell id="e%d" value="%s%s" style="%s" edge="1" parent="1" '
                 'source="%s" target="%s">'
                 '<mxGeometry relative="1" as="geometry"/></mxCell>'
                 % (e, nl(lab) if lab else "", mult, style, box[a], box[b]))
        e += 1
    L.append(DTAIL)
    return "\n".join(L) + "\n"


def drawio_deploy(elems, edges, cmap):
    L = [dhead("Deployment Container")]
    pos = {"CAM": (60, 90), "PC": (310, 90), "STB": (560, 90),
           "AI": (60, 400), "API": (280, 400), "DB": (500, 400),
           "WEB": (720, 400)}
    L.append('<mxCell id="lab" value="Lab" style="rounded=1;html=1;fontSize=14;" '
             'vertex="1" parent="1"><mxGeometry x="30" y="30" width="800" '
             'height="220" as="geometry"/></mxCell>')
    L.append('<mxCell id="srv" value="Server" style="rounded=1;html=1;fontSize=14;" '
             'vertex="1" parent="1"><mxGeometry x="30" y="290" width="800" '
             'height="250" as="geometry"/></mxCell>')
    for eid, (kind, lab) in elems.items():
        x, y = pos.get(eid, (60, 90))
        style = ("shape=cylinder3;whiteSpace=wrap;html=1;fontSize=12;"
                 if kind == "database"
                 else "rounded=1;whiteSpace=wrap;html=1;fontSize=12;")
        L.append('<mxCell id="n_%s" value="%s" style="%s" vertex="1" parent="1">'
                 '<mxGeometry x="%d" y="%d" width="200" height="120" '
                 'as="geometry"/></mxCell>' % (eid, nl(lab), style, x, y))
    e = 0
    for a, op, b, lab in edges:
        if a not in elems or b not in elems:
            continue
        style = ("endArrow=block;startArrow=block;html=1;fontSize=11;"
                 if op.startswith("<") else "endArrow=block;html=1;fontSize=11;")
        val = (' value="%s"' % nl(lab)) if lab else ""
        L.append('<mxCell id="d%d" style="%s" edge="1" parent="1" '
                 'source="n_%s" target="n_%s"%s>'
                 '<mxGeometry relative="1" as="geometry"/></mxCell>'
                 % (e, style, a, b, val))
        e += 1
    L.append(DTAIL)
    return "\n".join(L) + "\n"


# ---------- XMI 2.5 ----------
VIS = {"+": "public", "-": "private", "#": "protected", "~": "package"}
MEM_RE = re.compile(r'^([+#\-~])(?:(\S+)\s+)?(\w+)(\(\))?$')


def mult_tags(m):
    if m == "1":
        return ('<lowerValue xmi:type="uml:LiteralInteger" xmi:id="%s_L" value="1"/>'
                '<upperValue xmi:type="uml:LiteralInteger" xmi:id="%s_U" value="1"/>')
    if m == "*":
        return ('<lowerValue xmi:type="uml:LiteralInteger" xmi:id="%s_L" value="0"/>'
                '<upperValue xmi:type="uml:LiteralUnlimitedNatural" xmi:id="%s_U" value="*"/>')
    mm = re.match(r'(\d+)\.\.(\*|\d+)$', m or "")
    if mm:
        lo, hi = mm.group(1), mm.group(2)
        ut = ("uml:LiteralUnlimitedNatural" if hi == "*"
              else "uml:LiteralInteger")
        return ('<lowerValue xmi:type="uml:LiteralInteger" xmi:id="%%s_L" value="%s"/>'
                '<upperValue xmi:type="%s" xmi:id="%%s_U" value="%s"/>' % (lo, ut, hi))
    return ""


def xmi_assoc(aid, aname, atype, bid, bname, btype, ma="", mb=""):
    t = mult_tags(ma)
    la = t % (aid + "A", aid + "A") if t else ""
    t = mult_tags(mb)
    lb = t % (aid + "B", aid + "B") if t else ""
    return ('<packagedElement xmi:type="uml:Association" xmi:id="%s" name="%s">'
            '<memberEnd xmi:idref="%s_A"/><memberEnd xmi:idref="%s_B"/>'
            '<ownedEnd xmi:id="%s_A" name="%s" type="%s" association="%s">%s</ownedEnd>'
            '<ownedEnd xmi:id="%s_B" name="%s" type="%s" association="%s">%s</ownedEnd>'
            '</packagedElement>'
            % (aid, esc(aname), aid, aid, aid, esc(bname), atype, aid, la,
               aid, esc(bname), btype, aid, lb))


def gen_xmi(actors, ucs, assoc, inc, ext, all_classes, class_assocs):
    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<xmi:XMI xmlns:xmi="http://www.omg.org/spec/XMI/20131001" '
         'xmlns:uml="http://www.omg.org/spec/UML/20131001">',
         '<uml:Model xmi:id="M1" name="Sistem Presensi Praktikum Face Recognition">']
    for aid, alab in actors.items():
        L.append('<packagedElement xmi:type="uml:Actor" xmi:id="A_%s" name="%s"/>'
                 % (aid, esc(alab)))
    for uid, ulab in ucs.items():
        disp = (uid + " " + ulab) if ulab else uid
        L.append('<packagedElement xmi:type="uml:UseCase" xmi:id="U_%s" name="%s"/>'
                 % (uid, esc(disp)))
    for i, (a, b) in enumerate(assoc):
        at = ("A_" + a) if a in actors else ("U_" + a)
        bt = ("A_" + b) if b in actors else ("U_" + b)
        L.append(xmi_assoc("AS%d" % i, "%s_%s" % (a, b), at, "", "", bt))
    for i, (a, b) in enumerate(inc):
        L.append('<packagedElement xmi:type="uml:Include" xmi:id="IN%d" '
                 'name="%s_includes_%s"><client xmi:idref="U_%s"/>'
                 '<supplier xmi:idref="U_%s"/><addition xmi:idref="U_%s"/>'
                 '<includingCase xmi:idref="U_%s"/></packagedElement>'
                 % (i, a, b, a, b, b, a))
    for i, (a, b) in enumerate(ext):
        L.append('<packagedElement xmi:type="uml:Extend" xmi:id="EX%d" '
                 'name="%s_extends_%s"><client xmi:idref="U_%s"/>'
                 '<supplier xmi:idref="U_%s"/><extendedCase xmi:idref="U_%s"/>'
                 '</packagedElement>' % (i, a, b, a, b, b))
    for cn, attrs in all_classes.items():
        L.append('<packagedElement xmi:type="uml:Class" xmi:id="C_%s" name="%s">'
                 % (cn, cn))
        seen = set()
        for j, mem in enumerate(attrs):
            m = MEM_RE.match(mem)
            if m and m.group(4):
                if mem not in seen:
                    seen.add(mem)
                    L.append('<ownedOperation xmi:id="C_%s_o%d" name="%s"/>'
                             % (cn, j, m.group(3)))
            elif m:
                key = m.group(3)
                if key not in seen:
                    seen.add(key)
                    if m.group(2):
                        L.append('<ownedAttribute xmi:id="C_%s_a%d" name="%s" '
                                 'visibility="%s"><type xmi:type="uml:PrimitiveType" '
                                 'href="http://www.omg.org/spec/UML/20131001/PrimitiveTypes.xmi#%s"/>'
                                 '</ownedAttribute>'
                                 % (cn, j, key, VIS[m.group(1)], m.group(2)))
                    else:
                        L.append('<ownedAttribute xmi:id="C_%s_a%d" name="%s" '
                                 'visibility="%s"/>'
                                 % (cn, j, key, VIS[m.group(1)]))
            elif mem not in seen:
                seen.add(mem)
                L.append('<ownedAttribute xmi:id="C_%s_a%d" name="%s"/>'
                         % (cn, j, esc(mem)))
        L.append('</packagedElement>')
    for i, (a, ma, b, mb, lab, dashed) in enumerate(class_assocs):
        if dashed:
            L.append('<packagedElement xmi:type="uml:Dependency" xmi:id="CD%d" '
                     'name="%s"><client xmi:idref="C_%s"/>'
                     '<supplier xmi:idref="C_%s"/></packagedElement>'
                     % (i, esc(lab or (a + "_uses_" + b)), a, b))
        else:
            L.append(xmi_assoc("CA%d" % i, lab or ("%s_%s" % (a, b)),
                               "C_" + a, "", "", "C_" + b, ma, mb))
    L.append('</uml:Model></xmi:XMI>')
    return "\n".join(L) + "\n"


def main():
    actors, ucs, assoc, inc, ext = parse_uc(read("uc-00-overall.puml"))
    with open(os.path.join(DRAWIO_DIR, "uc-overall.drawio"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(drawio_uc(actors, ucs, assoc, inc, ext))
    print("wrote drawio uc-overall:", len(ucs), "usecase,", len(assoc), "assoc")

    all_classes, all_assocs = {}, []
    import glob
    for path in sorted(glob.glob(os.path.join(PUML, "class-*.puml"))):
        stem = os.path.basename(path)[:-5]
        with open(path, encoding="utf-8") as fh:
            classes, assocs = parse_class(fh.read().splitlines())
        with open(os.path.join(DRAWIO_DIR, stem + ".drawio"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(drawio_class(stem, classes, assocs))
        print("wrote drawio", stem, ":", len(classes), "class")
        for cn, attrs in classes.items():
            cur = all_classes.setdefault(cn, [])
            for a in attrs:
                if a not in cur:
                    cur.append(a)
        for a in assocs:
            if a not in all_assocs:
                all_assocs.append(a)
    with open(os.path.join(XMI_DIR, "presensi-uml.xmi"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(gen_xmi(actors, ucs, assoc, inc, ext, all_classes, all_assocs))
    print("wrote xmi: %d class, %d class-assoc" % (len(all_classes),
                                                   len(all_assocs)))

    elems, edges, _cmap = parse_deploy(read("deployment-container.puml"))
    with open(os.path.join(DRAWIO_DIR, "deployment-container.drawio"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(drawio_deploy(elems, edges, _cmap))
    print("wrote drawio deployment-container:", len(elems), "elemen")


if __name__ == "__main__":
    main()
