#!/usr/bin/env python3
"""ruah renderer: model.json (+ enrich.json) -> interactive HTML (+ Mermaid markdown).

Usage:
  render.py [DIR_OR_MODEL] [--enrich FILE] [--out FILE.html] [--md FILE.md] [--open] [--validate]

DIR defaults to ./.ruah. If DIR/enrich.json exists it is merged automatically.

enrich.json schema (every key optional; ids are model node ids):
{
  "summary":   "markdown narrative of the system",
  "nodes":     {"<id>": {"description": "...", "role": "api|ui|worker|domain|data|infra|...", "label": "nicer name"}},
  "add_nodes": [{"id": "...", "label": "...", "layer": "code|infra|external|ci", "kind": "...", "parent": "...", "description": "..."}],
  "add_edges": [{"source": "<id>", "target": "<id>", "kind": "calls|uses|deploys_to|triggers|reads|writes|same_as", "label": "..."}],
  "remove_nodes": ["<id>"],
  "flows":     [{"name": "Checkout", "description": "...", "steps": ["<id>", {"node": "<id>", "note": "..."}]}],
  "insights":  [{"title": "...", "body": "...", "severity": "info|warn|risk", "nodes": ["<id>"]}]
}
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_inputs(target, enrich_path):
    model_path = os.path.join(target, "model.json") if os.path.isdir(target) else target
    with open(model_path) as f:
        model = json.load(f)
    base = os.path.dirname(model_path)
    enrich_path = enrich_path or os.path.join(base, "enrich.json")
    enrich = {}
    if os.path.exists(enrich_path):
        with open(enrich_path) as f:
            enrich = json.load(f)
    return model, enrich, base, model_path


def merge(model, enrich):
    """Apply enrichment to the model in place. Returns a list of problems."""
    problems = []
    nodes = {n["id"]: n for n in model["nodes"]}
    for n in enrich.get("add_nodes") or []:
        if not n.get("id"):
            problems.append(f"add_nodes entry without id: {n}")
            continue
        n.setdefault("layer", "code")
        n.setdefault("kind", "component")
        n.setdefault("label", n["id"])
        n["added_by"] = "enrichment"
        if n["id"] in nodes:
            nodes[n["id"]].update({k: v for k, v in n.items() if k != "id"})
        else:
            model["nodes"].append(n)
            nodes[n["id"]] = n
    for nid, patch in (enrich.get("nodes") or {}).items():
        if nid not in nodes:
            problems.append(f"nodes: unknown id {nid}")
            continue
        for k in ("label", "description", "role", "kind"):
            if patch.get(k):
                nodes[nid][k] = patch[k]
    for nid in enrich.get("remove_nodes") or []:
        if nid in nodes:
            nodes[nid]["removed"] = True
        else:
            problems.append(f"remove_nodes: unknown id {nid}")
    for e in enrich.get("add_edges") or []:
        for end in ("source", "target"):
            if e.get(end) not in nodes:
                problems.append(f"add_edges: unknown {end} {e.get(end)}")
    model["enrichment"] = {
        "summary": enrich.get("summary"),
        "nodes": {k: v for k, v in (enrich.get("nodes") or {}).items() if k in nodes},
        "add_edges": [e for e in enrich.get("add_edges") or [] if e.get("source") in nodes and e.get("target") in nodes],
        "flows": [],
        "insights": enrich.get("insights") or [],
    }
    for f in enrich.get("flows") or []:
        steps = []
        for s in f.get("steps") or []:
            sid = s if isinstance(s, str) else (s or {}).get("node")
            if sid in nodes:
                steps.append(s)
            else:
                problems.append(f"flow '{f.get('name')}': unknown step {sid}")
        if steps:
            model["enrichment"]["flows"].append({**f, "steps": steps})
    for ins in model["enrichment"]["insights"]:
        for nid in ins.get("nodes") or []:
            if nid not in nodes:
                problems.append(f"insight '{ins.get('title')}': unknown node {nid}")
    return problems


def redact(model, base):
    """Apply <dir>/redact.json, for maps shown publicly:
    {"replace": {"RealName": "Generic", ...}, "patterns": [{"pattern": "regex", "replace": "…"}],
     "hide_git": true, "hide_paths": true, "name": "public repo name"}
    Replacements are case-insensitive, whole-word where the word is alphanumeric, over every string."""
    path = os.path.join(base, "redact.json")
    if not os.path.exists(path):
        return model
    with open(path) as f:
        rules = json.load(f)
    pairs = sorted((rules.get("replace") or {}).items(), key=lambda kv: -len(kv[0]))
    # whole word, where hyphens and dots count as separators: "acme" matches in "@acme/web" and "acme-api"
    rxs = [(re.compile((r"(?<![A-Za-z0-9])" if re.match(r"\w", k) else "") + re.escape(k) +
                       (r"(?![A-Za-z0-9])" if re.search(r"\w$", k) else ""), re.I), v) for k, v in pairs]

    rxs += [(re.compile(pat["pattern"], re.I), pat.get("replace", "…")) for pat in rules.get("patterns") or []]

    def walk(x):
        if isinstance(x, str):
            for rx, v in rxs:
                x = rx.sub(v, x)
            return x
        if isinstance(x, list):
            return [walk(i) for i in x]
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        return x

    model = walk(model)
    repo = model.setdefault("repo", {})
    if rules.get("hide_git"):
        repo.pop("git", None)
    if rules.get("hide_paths", True):
        repo.pop("path", None)
    if rules.get("name"):
        repo["name"] = rules["name"]
    return model


def write_html(model, out, artifact=False):
    """Write the interactive page. artifact=True writes a fragment for the Claude Artifact viewer
    (it supplies the html/head/body skeleton), hides local-only controls and drops absolute paths."""
    with open(os.path.join(HERE, "template.html")) as f:
        tpl = f.read()
    if artifact:
        model = json.loads(json.dumps(model, default=list))
        model["artifact"] = True
        model.get("repo", {}).pop("path", None)
        tpl = re.sub(r"(?is)<!doctype html>|</?html[^>]*>|</?head>|</?body>|<meta [^>]*>", "", tpl).lstrip()
        # file downloads don't work inside the Artifact viewer: drop the PNG export
        tpl = re.sub(r"(?s)<!--LOCAL-ONLY-->.*?<!--/LOCAL-ONLY-->|/\*LOCAL-ONLY\*/.*?/\*/LOCAL-ONLY\*/", "", tpl)
    payload = json.dumps(model, separators=(",", ":"), default=list).replace("</", "<\\/")
    name = model.get("repo", {}).get("name", "repo")
    title = f"{name[:1].upper()}{name[1:]} Architecture"
    html = tpl.replace("__MODEL__", payload).replace("__TITLE__", title.replace("<", "&lt;"))
    with open(out, "w") as f:
        f.write(html)


# ---------------------------------------------------------------- Mermaid
SHAPES = {
    "database": ("[(", ")]"), "cache": ("[(", ")]"), "bucket": ("[(", ")]"), "queue": (">", "]"),
    "function": ("{{", "}}"), "gateway": ("[/", "/]"), "workflow": ("([", "])"),
}


def mermaid_overview(model, max_nodes=140):
    nodes = {n["id"]: n for n in model["nodes"] if not n.get("removed")}
    keep = {}
    for n in nodes.values():
        if n.get("low_level") or n.get("kind") == "test":
            continue
        if n["layer"] == "code" and not n["id"].startswith("pkg:"):
            continue
        if n["id"].startswith("stack:") or n.get("kind") == "module":
            continue
        keep[n["id"]] = n
    if len(keep) > max_nodes:
        keep = dict(list(keep.items())[:max_nodes])

    def rep(i):
        seen = 0
        while i and seen < 6:
            if i in keep:
                return i
            n = nodes.get(i)
            if not n or n.get("low_level"):
                return None
            i = n.get("parent")
            if i and i.startswith("stack:"):
                return None
            seen += 1
        return None

    ids = {}

    def mid(i):
        if i not in ids:
            ids[i] = f"n{len(ids)}"
        return ids[i]

    def label(n):
        t = (n.get("label") or n["id"]).replace('"', "'")
        sub = n.get("tech") or n.get("category") or n.get("kind")
        return f'"{t}<br/>{sub}"' if sub and sub != t else f'"{t}"'

    lines = ["flowchart LR"]
    groups = {}
    for n in keep.values():
        if n["layer"] == "code":
            g = "Code"
        elif n["layer"] == "external":
            g = "External services"
        elif n["layer"] == "ci":
            g = "CI/CD"
        else:
            g = nodes.get(n.get("parent"), {}).get("label") or n.get("platform") or "Infrastructure"
        groups.setdefault(g, []).append(n)
    for gi, (g, members) in enumerate(groups.items()):
        lines.append(f'  subgraph g{gi}["{g}"]')
        for n in members:
            a, b = SHAPES.get(n.get("kind"), ("[", "]"))
            lines.append(f"    {mid(n['id'])}{a}{label(n)}{b}")
        lines.append("  end")
    seen = set()
    edges = model["edges"] + ((model.get("enrichment") or {}).get("add_edges") or [])
    for e in edges:
        s, t = rep(e["source"]), rep(e["target"])
        if not s or not t or s == t or (s, t) in seen:
            continue
        seen.add((s, t))
        kind = e["kind"]
        if kind in ("imports", "references", "depends_on", "configured"):
            lines.append(f"  {mid(s)} --> {mid(t)}")
        elif kind in ("deploys_to", "deploys"):
            lines.append(f"  {mid(s)} -.->|{kind.replace('_', ' ')}| {mid(t)}")
        else:
            lines.append(f"  {mid(s)} -->|{kind.replace('_', ' ')}| {mid(t)}")
    return "\n".join(lines)


def write_md(model, out):
    repo = model.get("repo", {})
    en = model.get("enrichment") or {}
    st = model.get("stack", {})
    parts = [f"# {repo.get('name', 'Repository')} — architecture", "",
             f"_Generated by ruah on {datetime.date.today().isoformat()}"
             + (f" from `{repo['git']['branch']}@{repo['git']['commit']}`" if repo.get("git") else "") + "._", ""]
    if en.get("summary"):
        parts += [en["summary"], ""]
    parts += ["## Stack", "",
              "- **Languages:** " + ", ".join(f"{k} ({v} files)" for k, v in list(st.get("languages", {}).items())[:6]),
              "- **Frameworks:** " + (", ".join(st.get("frameworks", [])) or "—"),
              "- **Tooling:** " + (", ".join(st.get("package_managers", [])) or "—"), "",
              "## System overview", "", "```mermaid", mermaid_overview(model), "```", ""]
    if en.get("flows"):
        parts += ["## Key flows", ""]
        names = {n["id"]: n.get("label", n["id"]) for n in model["nodes"]}
        for f in en["flows"]:
            parts.append(f"### {f['name']}")
            if f.get("description"):
                parts.append(f["description"])
            for i, s in enumerate(f["steps"], 1):
                nid = s if isinstance(s, str) else s["node"]
                note = "" if isinstance(s, str) else (f" — {s['note']}" if s.get("note") else "")
                parts.append(f"{i}. **{names.get(nid, nid)}**{note}")
            parts.append("")
    if en.get("insights"):
        parts += ["## Insights", ""]
        for ins in en["insights"]:
            parts.append(f"- **[{ins.get('severity', 'info')}] {ins['title']}** — {ins.get('body', '')}")
        parts.append("")
    parts += ["## Components", "", "| Component | Kind | Where | Description |", "|---|---|---|---|"]
    for n in model["nodes"]:
        if n.get("removed") or n.get("low_level") or n["id"].startswith(("stack:", "mod:")) or n.get("kind") == "test":
            continue
        desc = ((en.get("nodes") or {}).get(n["id"]) or {}).get("description") or n.get("description") or ""
        where = n.get("path") or n.get("file") or ""
        parts.append(f"| {n.get('label')} | {n.get('tech') or n.get('kind')} | `{where}` | {desc.replace('|', '/').splitlines()[0] if desc else ''} |")
    with open(out, "w") as f:
        f.write("\n".join(parts) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", default=".ruah")
    ap.add_argument("--enrich")
    ap.add_argument("--out")
    ap.add_argument("--md", help="also write a Mermaid markdown doc to this path")
    ap.add_argument("--open", action="store_true", help="open the HTML in the default browser")
    ap.add_argument("--validate", action="store_true", help="only validate enrich.json ids, write nothing")
    ap.add_argument("--view", choices=["overview", "code", "infra", "all"], default="overview", help="initial tab")
    ap.add_argument("--artifact", action="store_true",
                    help="also write artifact.html: a fragment for publishing as a Claude Artifact (desktop/web app)")
    ap.add_argument("--pane", action="store_true",
                    help="also write pane.json (per-view SVG + outlines) for the ruah mod's in-app pane")
    args = ap.parse_args()

    model, enrich, base, model_path = load_inputs(args.target, args.enrich)
    problems = merge(model, enrich)
    model = redact(model, base)
    if args.validate:
        print("\n".join(problems) if problems else "enrich.json OK")
        sys.exit(1 if problems else 0)
    model["generated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    model["initial_view"] = args.view
    out = args.out or os.path.join(base, "architecture.html")
    write_html(model, out)
    print(f"html → {out}")
    if args.pane:
        sys.path.insert(0, HERE)
        from ruah_lib.pane import build
        pane_path = os.path.join(os.path.dirname(os.path.abspath(out)), "pane.json")
        with open(pane_path, "w") as f:
            json.dump(build(model), f, separators=(",", ":"))
        print(f"pane → {pane_path}")
    if args.artifact:
        art = os.path.join(os.path.dirname(os.path.abspath(out)), "artifact.html")
        write_html(model, art, artifact=True)
        print(f"artifact page → {art}")
    if args.md:
        write_md(model, args.md)
        print(f"markdown → {args.md}")
    if problems:
        print("enrichment problems (ignored):\n  " + "\n  ".join(problems[:30]))
    url_hash = f"#{args.view}"
    if args.open:
        if args.view != "overview":
            out = "file://" + os.path.abspath(out) + url_hash
        opener = "open" if sys.platform == "darwin" else "xdg-open" if sys.platform.startswith("linux") else None
        if opener:
            subprocess.run([opener, out], check=False)
        elif sys.platform.startswith("win"):
            os.startfile(out)  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
