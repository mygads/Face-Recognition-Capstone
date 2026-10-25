"""Paritas 1-per-1: FLOWS (sumber bpmn/drawio) dan .puml vs blok mermaid proposal.

Cara pakai: py _gen/check_parity.py  ->  exit 0 bila nol selisih.
Aturan pemetaan: stadium TANPA incoming = start; stadium TANPA outgoing = end;
rect/parallelogram = task; rhombus = gateway. Label dibandingkan ternormalisasi
(huruf kecil, alnum saja). Subgraph/partition/note = representasi, dilewati.
"""
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from gen_flows import FLOWS  # noqa: E402

D = os.path.abspath(os.path.join(BASE, ".."))
MMD = os.path.join(D, "mermaid")
PUML = os.path.join(D, "plantuml")

MAP = {
    ("05-activity", 1): "f01-login",
    ("05-activity", 2): "f02-master-import",  # puml: act-f02-master-import.puml
    ("05-activity", 3): "f03-enrollment",
    ("05-activity", 4): "f04-schedule",
    ("05-activity", 5): "f05-session",
    ("05-activity", 6): "f06-walkthrough",
    ("05-activity", 7): "f07-manual",
    ("05-activity", 8): "f08-dashboard",
    ("05-activity", 9): "f09-reports",
    ("05-activity", 10): "f10-ews",
    ("05-activity", 11): "f11-device",
    ("05-activity", 12): "f12-preview",
    ("05-activity", 13): "f13-account",
    ("05-activity", 14): "f14-roles",
    ("06-proses-bisnis-dan-alur", 1): "e2e-business",
    ("09-ews", 1): "ews-stage1",
    ("09-ews", 2): "ews-stage2",
    ("02-metode-prototype", 1): "prototype-method",
}

PUML_OF = {
    "f01-login": "act-f01-login.puml",
    "f02-master-import": "act-f02-master-import.puml",
    "f03-enrollment": "act-f03-enrollment.puml",
    "f04-schedule": "act-f04-schedule.puml",
    "f05-session": "act-f05-session.puml",
    "f06-walkthrough": "act-f06-walkthrough.puml",
    "f07-manual": "act-f07-manual.puml",
    "f08-dashboard": "act-f08-dashboard.puml",
    "f09-reports": "act-f09-reports.puml",
    "f10-ews": "act-f10-ews.puml",
    "f11-device": "act-f11-device.puml",
    "f12-preview": "act-f12-preview.puml",
    "f13-account": "act-f13-account.puml",
    "f14-roles": "act-f14-roles.puml",
    "e2e-business": "act-e2e-business.puml",
    "ews-stage1": "act-ews-stage1.puml",
    "ews-stage2": "act-ews-stage2.puml",
    "prototype-method": "act-prototype-method.puml",
}

issues = []


def err(msg):
    issues.append(msg)


def norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def parse_mmd(text):
    nodes, edges = {}, []
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("%%") or ln.startswith("flowchart") \
                or ln.startswith("subgraph") or ln == "end":
            continue
        rest = ln
        for m in re.finditer(r"(\w+)\(\[(.*?)\]\)", rest):
            nodes[m.group(1)] = ("stadium", m.group(2).strip())
        for m in re.finditer(r"(\w+)\[/(.*?)/\]", rest):
            nodes.setdefault(m.group(1), ("para", m.group(2).strip()))
        for m in re.finditer(r"(\w+)\{(.*?)\}", rest):
            nodes.setdefault(m.group(1), ("rhombus", m.group(2).strip()))
        for m in re.finditer(r"(?<!\w)(\w+)\[((?:[^\[\]]|\[[^\]]*\])*)\]", rest):
            if m.group(1) not in nodes:
                nodes[m.group(1)] = ("rect", m.group(2).strip())
        nl = re.sub(r"\(\[.*?\]\)", "", rest)
        nl = re.sub(r"\[.*?\]|\{.*?\}", "", nl)
        for m in re.finditer(r"(\w+)\s*--\s*(.*?)\s*-->\s*(\w+)", nl):
            a, g, b = m.group(1), m.group(2).strip(), m.group(3)
            if g.startswith("-") or "- " in g:
                continue
            edges.append((a, g, b))
        tmp = re.sub(r"--\s*.*?\s*-->", "-->", nl)
        for m in re.finditer(r"(\w+)\s*-->\s*(\w+)", tmp):
            if not any(e[0] == m.group(1) and e[2] == m.group(2)
                       for e in edges):
                edges.append((m.group(1), "", m.group(2)))
    return nodes, edges


def endpoints(nodes, edges):
    srcs = {a for a, _, _ in edges}
    dsts = {b for _, _, b in edges}
    return srcs, dsts


def check_flow(mid, fid, nodes, edges):
    fl = next((f for f in FLOWS if f["id"] == fid), None)
    if fl is None:
        err("%s: flow '%s' TAK ADA di gen_flows (kurang lengkap)" % (mid, fid))
        return
    flabel = {}
    for nid, kind, label in fl["nodes"]:
        flabel.setdefault(norm(label), []).append((nid, kind))
    fedges = [(a, (g or ""), b) for a, b, g in fl["edges"]]
    srcs, dsts = endpoints(nodes, edges)
    for nid, (shape, text) in nodes.items():
        want = None
        if shape == "stadium" and nid not in dsts:
            want = "start"
        elif shape == "stadium" and nid not in srcs:
            want = "end"
        elif shape == "rhombus":
            want = ("xg", "pg")
        else:
            want = "task"
        got = flabel.get(norm(text))
        if got is None:
            err("%s: node mmd '%s' [%s] tak ada di flow %s"
                % (mid, text, shape, fid))
        elif want == "start":
            # stadium entri diwakili start generik "Mulai" + task berlabel entri
            if not any(k in ("start", "task") for _, k in got):
                err("%s: '%s' harusnya start/entri di flow (dapat %s)"
                    % (mid, text, sorted({k for _, k in got})))
        elif want == "end":
            if not any(k == want for _, k in got):
                err("%s: '%s' harusnya %s di flow (dapat %s)"
                    % (mid, text, want, sorted({k for _, k in got})))
        elif want == "task":
            if not any(k == "task" for _, k in got):
                err("%s: '%s' harusnya task di flow (dapat %s)"
                    % (mid, text, sorted({k for _, k in got})))
        elif isinstance(want, tuple):
            if not any(k in want for _, k in got):
                err("%s: gateway '%s' tak ada di flow" % (mid, text))
    want_extra = {"fork", "join"}
    for nid, kind, label in fl["nodes"]:
        n = norm(label)
        if n in want_extra and kind in ("pg",):
            continue
        if n == "mulai" and kind == "start":
            continue  # start generik; stadium entri mermaid jadi task berlabel sama
        if n == "selesai" and kind == "end":
            continue  # ujung generik jalur terminal (BPMN wajibkan end)
        if not any(norm(t) == n for _, (_, t) in nodes.items()):
            err("%s: node flow '%s' (%s) tak ada di mermaid (temuan?)"
                % (mid, label, nid))
    by_label = {}
    for nid, (shape, text) in nodes.items():
        by_label.setdefault(norm(text), []).append(nid)
    for a, g, b in edges:
        ta = nodes.get(a, ("?", a))[1]
        tb = nodes.get(b, ("?", b))[1]
        na, nb, ng = norm(ta), norm(tb), norm(g)
        ok = False
        for fa, fg, fb in fedges:
            fla = next((lbl for i, k, lbl in fl["nodes"] if i == fa), "")
            flb = next((lbl for i, k, lbl in fl["nodes"] if i == fb), "")
            if norm(fla) == na and norm(flb) == nb and norm(fg) == ng:
                ok = True
                break
        if not ok:
            err("%s: edge '%s' --%s--> '%s' tak ada di flow"
                % (mid, ta, g or "(tanpa guard)", tb))


def parse_puml(path):
    texts, conds, guards = [], [], []
    in_note = False
    for raw in open(path, encoding="utf-8"):
        ln = raw.strip()
        if re.match(r"^note(\s|$)", ln) and ":" not in ln:
            in_note = True
            continue
        if in_note:
            if re.match(r"^end note(\s|$)", ln):
                in_note = False
            continue
        if ln.startswith("'") or ln.startswith("|") or \
                ln.startswith("title") or ln.startswith("@"):
            continue
        m = re.match(r"^:(.*?);\s*$", ln)
        if m:
            texts.append(m.group(1).replace("\\n", " "))
            continue
        m = re.match(r"^if\s*\((.*?)\)\s*then\s*\((.*?)\)\s*$", ln)
        if m:
            conds.append(m.group(1))
            guards.append(m.group(2))
            continue
        m = re.match(r"^elseif\s*\((.*?)\)\s*$", ln)
        if m:
            guards.append(m.group(1))
            continue
        m = re.match(r"^else\s*\((.*?)\)\s*$", ln)
        if m:
            guards.append(m.group(1))
            continue
        m = re.match(r"^repeat\s+while\s*\((.*?)\)\s*is\s*\((.*?)\)", ln)
        if m:
            conds.append(m.group(1))
            guards.append(m.group(2))
            continue
    return texts, conds, guards


def check_puml(mid, fid, nodes, edges):
    p = os.path.join(PUML, PUML_OF[fid])
    if not os.path.exists(p):
        err("%s: puml %s TAK ADA" % (mid, PUML_OF[fid]))
        return
    texts, conds, guards = parse_puml(p)
    have = [norm(t) for t in texts + conds]
    for nid, (shape, text) in nodes.items():
        if norm(text) == "mulai":
            continue
        if shape == "rhombus":
            if norm(text) not in [norm(c) for c in conds]:
                err("%s: gateway mmd '%s' tak ada di puml %s"
                    % (mid, text, PUML_OF[fid]))
        elif norm(text) not in have:
            err("%s: node mmd '%s' tak ada di puml %s"
                % (mid, text, PUML_OF[fid]))
    mg = {norm(g) for _, g, _ in edges if g}
    pg = {norm(g) for g in guards}
    for g in sorted(mg - pg):
        if g not in ("tidak",):
            err("%s: guard mmd '%s' tak ada di puml %s" % (mid, g, PUML_OF[fid]))


def main():
    mmds = sorted(f for f in os.listdir(MMD) if f.endswith(".mmd"))
    by_stem = {}
    for m in mmds:
        mt = re.match(r"^(.*)-(\d+)\.mmd$", m)
        if mt:
            by_stem.setdefault(mt.group(1), {})[int(mt.group(2))] = m
    for (stem, idx), fid in sorted(MAP.items(), key=lambda kv: str(kv[0])):
        mid = "%s-%02d" % (stem, idx)
        m = by_stem.get(stem, {}).get(idx)
        if not m:
            err("mmd tak ada untuk %s" % mid)
            continue
        n, e = parse_mmd(open(os.path.join(MMD, m), encoding="utf-8").read())
        check_flow(mid, fid, n, e)
        check_puml(mid, fid, n, e)
    covered = {s for s, _ in MAP}
    for s in sorted(by_stem):
        if s not in covered and not s.startswith(("04-use-case", "07-data",
                                                  "08-arsitektur")):
            err("stem mmd tanpa pasangan flow: %s" % s)
    if issues:
        print("SELISIH (%d):" % len(issues))
        for i in issues:
            print(" -", i)
        return 1
    print("PARITAS BERSIH: FLOWS+puml 1-per-1 vs mermaid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
