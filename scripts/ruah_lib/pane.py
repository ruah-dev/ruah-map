"""Pane data for the ruah mod: per-view SVG diagrams + markdown outlines + node details.

The mod (hooks/register.tsx) cannot run a layout engine, so the layout happens here:
a deterministic swimlane layout (CI | code | infra stacks | external services), ordered
by a few barycenter sweeps to keep edges short, drawn as compact SVG with <title>
tooltips and per-node / per-edge classes the pane can highlight by injecting a <style>.
"""
import html
import re

VIEWS = ("overview", "code", "infra", "all")
SVG_LIMIT = 128_000  # the Svg element takes at most 131072 characters
PRIORITY = ["triggers", "routes_to", "accesses", "publishes", "invokes", "deploys_to", "deploys", "calls", "connects",
            "uses", "reads", "writes", "depends_on", "imports", "configured", "instantiates", "references", "same_as"]
SEMANTIC = {"triggers", "routes_to", "accesses", "deploys", "publishes", "invokes", "reads", "writes"}

# kind -> dot colour class; nodes stay neutral so the map reads like the app around it
KIND_CLASS = {
    "app": "c", "service": "c", "package": "c", "component": "c", "module": "m", "test": "lo",
    "function": "fn", "compute": "cp", "container": "cp", "database": "db", "cache": "ca", "queue": "q",
    "bucket": "st", "gateway": "gw", "dns": "lo", "network": "lo", "iam": "lo", "secret": "lo",
    "observability": "lo", "binding": "lo", "hosting": "ho", "auth": "au", "platform": "lo", "registry": "lo",
    "workflow": "ci", "resource": "lo",
}

# Theme tokens: light by default, dark under prefers-color-scheme; the mod replaces /*THEME*/ with an
# explicit block when it knows the app's theme. No background: the host surface shows through.
STYLE = """
:root{--fg:#1f1e1d;--mut:#8a8984;--node:rgba(31,30,29,.035);--nodeb:rgba(31,30,29,.13);--grp:rgba(31,30,29,.022);
--grpb:rgba(31,30,29,.08);--edge:rgba(31,30,29,.26);--acc:#c4633f}
@media (prefers-color-scheme:dark){:root{--fg:#e8e7e2;--mut:#8f8e88;--node:rgba(255,255,255,.035);--nodeb:rgba(255,255,255,.1);
--grp:rgba(255,255,255,.018);--grpb:rgba(255,255,255,.065);--edge:rgba(255,255,255,.22);--acc:#d97757}}
/*THEME*/
text{font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
.lt{fill:var(--mut);font-size:9.5px;letter-spacing:.08em;font-weight:600}
.g rect{fill:var(--grp);stroke:var(--grpb)}.g text{fill:var(--mut);font-size:10.5px;font-weight:600}
.n rect{fill:var(--node);stroke:var(--nodeb)}.n text{fill:var(--fg);font-size:11.5px;font-weight:500}.n .t{fill:var(--mut);font-weight:400}
.n circle{fill:#8a8984}.c circle{fill:#6f93dc}.m circle{fill:#93aee6}.x circle{fill:#9b82d6}.ci circle{fill:#8a8984}
.fn circle{fill:#d98b4f}.cp circle{fill:#c9a043}.db circle{fill:#5da874}.ca circle{fill:#4aa7a1}.q circle{fill:#cc6d99}
.st circle{fill:#93b05a}.gw circle{fill:#4fa2c4}.ho circle{fill:#8c86dd}.au circle{fill:#b07ad6}.lo circle{fill:#76757a}
.e{fill:none;stroke:var(--edge);stroke-width:1.1}.e.s{stroke:var(--acc);stroke-width:1.4}.e.d{stroke-dasharray:3 3}
.el{fill:var(--mut);font-size:9.5px}.ah{fill:var(--edge)}
.dr rect{stroke:#dc5a4a;stroke-dasharray:3 2}.lv rect{stroke:#d99a3a;stroke-dasharray:1 2}
"""

# left to right: external services | code | infrastructure | CI/CD, so each kind of edge
# (code uses SaaS, code deploys to infra, CI deploys infra) runs between neighbouring lanes
LANE_ORDER = (3, 1, 2, 0)
NODE_W, NODE_H, GAP, GROUP_PAD, GROUP_HEAD, COL_GAP, LANE_HEAD = 196, 26, 6, 8, 22, 64, 22


def esc(s):
    return html.escape(str(s), quote=True)


def trunc(s, n):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


class View:
    def __init__(self, model, view, low=False, tests=False):
        self.m = model
        self.view = view
        self.by_id = {n["id"]: n for n in model["nodes"] if not n.get("removed")}
        self.low, self.tests = low, tests
        self._visible()
        self._edges()

    # same rules as the HTML page's visibleSet/rep/buildElements
    def _ok(self, n):
        if not self.low and n.get("low_level"):
            return False
        # individual DNS records are detail: the Infra view lists them, the overview keeps the zone
        if self.view == "overview" and n.get("kind") == "dns" and "zone" not in str(n.get("label", "")).lower():
            return False
        if not self.tests and n.get("kind") == "test":
            return False
        return True

    def _visible(self):
        vis = set()
        for n in self.by_id.values():
            if not self._ok(n):
                continue
            nid, layer = n["id"], n["layer"]
            if self.view == "code":
                ok = layer in ("code", "external")
            elif self.view == "infra":
                ok = layer in ("infra", "ci") or nid.startswith("pkg:")
            elif self.view == "overview":
                ok = not (layer == "code" and not nid.startswith("pkg:")) and not (n.get("kind") == "module" and layer == "infra")
            else:
                ok = True
            if ok:
                vis.add(nid)
        self.parent = {i: self.by_id[i].get("parent") for i in vis if self.by_id[i].get("parent") in vis}
        parents = set(self.parent.values())
        vis = {i for i in vis if not i.startswith("stack:") or i in parents}
        if self.view == "overview":
            vis.discard("stack:ci")
            self.parent = {k: v for k, v in self.parent.items() if v in vis}
        self.vis = vis
        self.groups = {p for p in self.parent.values() if p in vis}

    def rep(self, i):
        seen = 0
        while i and seen < 8:
            if i in self.vis:
                return i  # a visible stack/package box is a valid endpoint (CI deploys a whole stack)
            n = self.by_id.get(i)
            if not n or n.get("low_level") or n.get("kind") == "test":
                return None
            i = n.get("parent")
            if i and i.startswith("stack:"):
                return None
            seen += 1
        return None

    def _edges(self):
        edges = {}
        en = self.m.get("enrichment") or {}
        for e in self.m["edges"] + (en.get("add_edges") or []):
            s, t = self.rep(e["source"]), self.rep(e["target"])
            if not s or not t or s == t or self.parent.get(s) == t or self.parent.get(t) == s:
                continue
            key = tuple(sorted((s, t)))
            pri = PRIORITY.index(e["kind"]) if e["kind"] in PRIORITY else 99
            cur = edges.get(key)
            if cur is None or pri < cur["pri"]:
                edges[key] = {"s": s, "t": t, "kind": e["kind"], "label": e.get("label"), "pri": pri,
                              "w": (cur or {}).get("w", 0) + e.get("weight", 1)}
            else:
                cur["w"] += e.get("weight", 1)
        used = {x for e in edges.values() for x in (e["s"], e["t"])}
        leaves = {i for i in self.vis if i not in self.groups}
        drop = set()
        for i in leaves:
            n = self.by_id[i]
            if self.view == "code" and n["layer"] == "external" and i not in used:
                drop.add(i)
            if self.view == "infra" and i.startswith("pkg:") and i not in used:
                drop.add(i)
        self.leaves = sorted(leaves - drop)
        self.edges = [e for e in edges.values() if e["s"] not in drop and e["t"] not in drop]


# --------------------------------------------------------------------------- layout
def lane_of(v, n):
    if n["layer"] == "ci":
        return 0
    if n["layer"] == "external":
        return 3
    if n["layer"] == "code":
        return 1
    if n["id"].startswith("plat:"):
        return 0  # platforms only CI points at sit beside CI, not across the map
    return 2


def layout(v, max_col_h=900):
    """Returns (pos, columns): pos maps leaf and group ids to {x, y, w, h, col}."""
    units = {}
    for i in v.leaves:
        g = v.parent.get(i)
        units.setdefault(g if g else i, []).append(i)
    lanes = {0: [], 1: [], 2: [], 3: []}
    for key, members in units.items():
        lanes[lane_of(v, v.by_id[members[0]])].append(key)

    def unit_h(key):
        k = len(units[key])
        return (GROUP_HEAD + GROUP_PAD + k * (NODE_H + GAP)) if key in v.groups else NODE_H + GAP

    # split tall lanes into columns; a small max_col_h gives the wide, short band variant
    columns = []
    for lane in LANE_ORDER:
        keys = lanes[lane]
        if not keys:
            continue
        total = sum(unit_h(k) + GAP * 2 for k in keys)
        ncols = max(1, min(6, round(total / max_col_h)))
        cols = [[] for _ in range(ncols)]
        heights = [0] * ncols
        for k in sorted(keys, key=lambda k: -unit_h(k)):
            j = heights.index(min(heights))
            cols[j].append(k)
            heights[j] += unit_h(k) + GAP * 2
        columns += [(lane, c) for c in cols if c]

    adj = {}
    for e in v.edges:
        adj.setdefault(e["s"], []).append(e["t"])
        adj.setdefault(e["t"], []).append(e["s"])
    pos = {}

    def place():
        x = 12
        for ci, (lane, keys) in enumerate(columns):
            y = 12 + LANE_HEAD
            for k in keys:
                if k in v.groups:
                    pos[k] = {"x": x, "y": y, "w": NODE_W + 2 * GROUP_PAD, "h": unit_h(k) - GAP, "col": ci}
                    yy = y + GROUP_HEAD
                    for m in units[k]:
                        pos[m] = {"x": x + GROUP_PAD, "y": yy, "w": NODE_W, "h": NODE_H, "col": ci}
                        yy += NODE_H + GAP
                    y += unit_h(k) + GAP * 2
                else:
                    pos[k] = {"x": x + GROUP_PAD, "y": y, "w": NODE_W, "h": NODE_H, "col": ci}
                    y += NODE_H + GAP * 2
            x += NODE_W + 2 * GROUP_PAD + COL_GAP

    def bary(i):
        ys = [pos[j]["y"] for j in adj.get(i, []) if j in pos and pos[j]["col"] != pos[i]["col"]]
        return sum(ys) / len(ys) if ys else pos[i]["y"]

    place()
    for _ in range(4):
        for lane, keys in columns:
            for k in keys:
                if k in v.groups:
                    units[k].sort(key=bary)
            keys.sort(key=lambda k: sum(bary(m) for m in units[k]) / len(units[k]))
        place()
    return pos, columns


def edge_path(a, b):
    if a["col"] == b["col"]:
        x = a["x"] + a["w"]
        y1, y2 = a["y"] + a["h"] / 2, b["y"] + b["h"] / 2
        bend = 24 + min(48, abs(y2 - y1) / 6)
        return f"M{x:.0f} {y1:.0f}C{x + bend:.0f} {y1:.0f} {x + bend:.0f} {y2:.0f} {x:.0f} {y2:.0f}", x + bend * 0.75, (y1 + y2) / 2
    if a["x"] < b["x"]:
        x1, x2 = a["x"] + a["w"], b["x"]
    else:
        x1, x2 = a["x"], b["x"] + b["w"]
    y1, y2 = a["y"] + a["h"] / 2, b["y"] + b["h"] / 2
    dx = (x2 - x1) * 0.5
    return f"M{x1:.0f} {y1:.0f}C{x1 + dx:.0f} {y1:.0f} {x2 - dx:.0f} {y2:.0f} {x2:.0f} {y2:.0f}", (x1 + x2) / 2, (y1 + y2) / 2


def pretty_tech(t):
    """aws_lambda_function -> lambda function, Cloudflare Worker -> Worker, k8s Deployment -> Deployment."""
    t = re.sub(r"^(aws|google|azurerm|cloudflare|kubernetes|digitalocean|vercel)_", "", str(t))
    t = re.sub(r"^(Cloudflare|k8s|Supabase|Firebase|Render|Vercel|Fly|Netlify|Heroku|AWS::\w+::|Microsoft\.\w+/)\s*", "", t)
    return t.replace("_", " ").strip()


def render_svg(v, short, titles=True, labels=True, max_col_h=900):
    pos, columns = layout(v, max_col_h)
    if not pos:
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 40"></svg>', 300, 40
    W = max(p["x"] + p["w"] for p in pos.values()) + 16
    H = max(p["y"] + p["h"] for p in pos.values()) + 12
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}">',
           "<style>" + re.sub(r"\s*\n\s*", "", STYLE) + "/*HL*/</style>",
           '<defs><marker id="a" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto">'
           '<path class="ah" d="M0 0L8 4L0 8z"/></marker></defs>']
    lane_names = {0: "CI / CD", 1: "CODE", 2: "INFRASTRUCTURE", 3: "EXTERNAL"}
    seen_lane = set()
    for lane, keys in columns:
        if lane in seen_lane or not keys:
            continue
        seen_lane.add(lane)
        first = pos[keys[0]]
        out.append(f'<text class="lt" x="{first["x"] - (0 if keys[0] in v.groups else GROUP_PAD):.0f}" y="24">{lane_names[lane]}</text>')
    for g in v.groups:
        if g not in pos:
            continue
        p = pos[g]
        out.append(f'<g class="g G{short[g]}"><rect x="{p["x"]:.0f}" y="{p["y"]:.0f}" width="{p["w"]:.0f}" height="{p["h"]:.0f}" rx="9"/>'
                   f'<text x="{p["x"] + 10:.0f}" y="{p["y"] + 15:.0f}">{esc(trunc(v.by_id[g].get("label") or g, 32))}</text></g>')
    for e in v.edges:
        a, b = pos.get(e["s"]), pos.get(e["t"])
        if not a or not b:
            continue
        d, lx, ly = edge_path(a, b)
        kind = e["kind"]
        cls = "e s" if kind in SEMANTIC - {"deploys"} else "e d" if kind in ("deploys_to", "deploys") else "e"
        si, ti = short[e["s"]], short[e["t"]]
        out.append(f'<path class="{cls} E{si} E{ti}" d="{d}" marker-end="url(#a)"/>')
        if labels and kind in SEMANTIC and kind != "deploys":
            text = trunc(e.get("label") or kind.replace("_", " "), 22)
            out.append(f'<text class="el E{si} E{ti}" x="{lx:.0f}" y="{ly - 4:.0f}" text-anchor="middle">{esc(text)}</text>')
    for i in v.leaves:
        p = pos.get(i)
        if not p:
            continue
        n = v.by_id[i]
        cls = "x" if n["layer"] == "external" else ("ci" if n["layer"] == "ci" else KIND_CLASS.get(n.get("kind"), "lo"))
        st = {"not_found_live": " dr", "live_only": " lv"}.get(n.get("status"), "")
        sub = n.get("tech") or n.get("category") or n.get("kind") or ""
        label = trunc(n.get("label") or i, 22)
        room = 27 - len(label)
        sub_short = pretty_tech(sub)
        tech = trunc(sub_short, room) if room >= 5 and sub_short and sub_short.lower() != label.lower() else ""
        tip = ""
        if titles:
            desc = ((v.m.get("enrichment") or {}).get("nodes", {}).get(i, {}) or {}).get("description") or n.get("description") or ""
            tip = f"<title>{esc(n.get('label'))} · {esc(sub)}{' — ' + esc(trunc(desc, 220)) if desc else ''}</title>"
        tspan = f'<tspan class="t" dx="6">{esc(tech)}</tspan>' if tech else ""
        out.append(f'<g class="n {cls}{st} N{short[i]}">{tip}<rect x="{p["x"]:.0f}" y="{p["y"]:.0f}" width="{p["w"]:.0f}" '
                   f'height="{p["h"]:.0f}" rx="6"/><circle cx="{p["x"] + 11:.0f}" cy="{p["y"] + p["h"] / 2:.0f}" r="3"/>'
                   f'<text x="{p["x"] + 21:.0f}" y="{p["y"] + p["h"] / 2 + 4:.0f}">{esc(label)}{tspan}</text></g>')
    out.append("</svg>")
    return "".join(out), W, H



# --------------------------------------------------------------------------- text
def outline_md(v):
    """The terminal draws no Svg: a markdown outline of the same view."""
    lines = []
    names = {i: v.by_id[i].get("label") or i for i in v.by_id}
    outs = {}
    for e in v.edges:
        outs.setdefault(e["s"], []).append(e)

    def line(i, indent=""):
        n = v.by_id[i]
        sub = n.get("tech") or n.get("category") or n.get("kind")
        rel = ", ".join(f"{e['kind'].replace('_', ' ')} **{names[e['t']]}**" for e in outs.get(i, [])[:6])
        status = {"not_found_live": " ⚠ not found live", "live_only": " ⚠ live only"}.get(n.get("status"), "")
        return f"{indent}- **{names[i]}** · {sub}{status}" + (f" → {rel}" if rel else "")

    lanes = {0: "CI / CD", 1: "Code", 2: "Infrastructure", 3: "External"}
    by_lane = {}
    for i in v.leaves:
        g = v.parent.get(i)
        by_lane.setdefault(lane_of(v, v.by_id[i]), {}).setdefault(g, []).append(i)
    for lane in (1, 2, 3, 0):
        if lane not in by_lane:
            continue
        lines.append(f"### {lanes[lane]}")
        for g, members in sorted(by_lane[lane].items(), key=lambda kv: str(kv[0])):
            if g:
                lines.append(f"**{names[g]}**")
            lines += [line(i) for i in members]
        lines.append("")
    text = "\n".join(lines)
    return text if len(text) < 9500 else text[:9400] + "\n\n…(truncated)"


def node_md(model, nid, short):
    n = {x["id"]: x for x in model["nodes"]}[nid]
    en = ((model.get("enrichment") or {}).get("nodes") or {}).get(nid) or {}
    names = {x["id"]: x.get("label") or x["id"] for x in model["nodes"]}
    parts = [f"#### {n.get('label')}"]
    desc = en.get("description") or n.get("description")
    if desc:
        parts.append(desc)
    facts = [("kind", n.get("kind")), ("tech", n.get("tech")), ("platform", n.get("platform")),
             ("role", en.get("role") or n.get("role")), ("status", n.get("status")),
             ("where", n.get("file") or n.get("path"))]
    parts.append(" · ".join(f"{k}: `{v}`" for k, v in facts if v))
    edges = model["edges"] + ((model.get("enrichment") or {}).get("add_edges") or [])
    outs = [e for e in edges if e["source"] == nid][:20]
    ins = [e for e in edges if e["target"] == nid][:20]
    if outs:
        parts.append("**Out:** " + "; ".join(f"{e['kind'].replace('_', ' ')} {names.get(e['target'], e['target'])}" for e in outs))
    if ins:
        parts.append("**In:** " + "; ".join(f"{names.get(e['source'], e['source'])} {e['kind'].replace('_', ' ')}" for e in ins))
    meta = n.get("meta") or {}
    for k in ("entrypoints", "frameworks", "images", "models", "tables", "crons", "routes", "hosts"):
        if meta.get(k):
            val = meta[k] if isinstance(meta[k], str) else ", ".join(map(str, meta[k]))[:300]
            parts.append(f"{k}: {val}")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- entry
def build(model):
    short = {}
    for i, n in enumerate(model["nodes"]):
        short[n["id"]] = i
    data = {"version": 1, "repo": {k: v for k, v in (model.get("repo") or {}).items() if k != "path"},
            "generated_at": model.get("generated_at"), "stack": model.get("stack"), "views": {}, "nodes": {},
            "summary": (model.get("enrichment") or {}).get("summary"),
            "insights": [], "flows": [], "detectors": model.get("detectors"),
            "counts": {}}
    for n in model["nodes"]:
        if not n.get("removed"):
            data["counts"][n["layer"]] = data["counts"].get(n["layer"], 0) + 1
    in_any_view = set()
    for name in VIEWS:
        v = View(model, name)
        svg, w, h = render_svg(v, short)
        if len(svg) > SVG_LIMIT:
            svg, w, h = render_svg(v, short, titles=False)
        if len(svg) > SVG_LIMIT:
            svg, w, h = render_svg(v, short, titles=False, labels=False)
        band, bw, bh = render_svg(v, short, titles=False, max_col_h=330)
        data["views"][name] = {
            "svg": svg if len(svg) <= SVG_LIMIT else None, "width": round(w), "height": round(h),
            "band": band if len(band) <= SVG_LIMIT else None, "bandWidth": round(bw), "bandHeight": round(bh),
            "md": outline_md(v), "nodes": [short[i] for i in v.leaves],
            "edges": [[short[e["s"]], short[e["t"]]] for e in v.edges],
            "groups": {str(short[g]): [short[m] for m in v.leaves if v.parent.get(m) == g] for g in v.groups},
            "reps": {str(short[i]): short[r] for i in v.by_id if (r := v.rep(i))},
        }
        in_any_view.update(v.leaves)
    for nid in in_any_view:
        n = {x["id"]: x for x in model["nodes"]}[nid]
        data["nodes"][str(short[nid])] = {"id": nid, "label": n.get("label") or nid, "layer": n["layer"],
                                          "md": node_md(model, nid, short)}
    en = model.get("enrichment") or {}
    for ins in en.get("insights") or []:
        data["insights"].append({"title": ins.get("title"), "severity": ins.get("severity", "info"), "body": ins.get("body", ""),
                                 "nodes": [short[i] for i in ins.get("nodes") or [] if i in short]})
    for f in en.get("flows") or []:
        steps = [s if isinstance(s, str) else s.get("node") for s in f.get("steps") or []]
        notes = [None if isinstance(s, str) else s.get("note") for s in f.get("steps") or []]
        data["flows"].append({"name": f.get("name"), "description": f.get("description"),
                              "steps": [short[s] for s in steps if s in short],
                              "notes": [nt for s, nt in zip(steps, notes) if s in short]})
    return data
