"""Architecture graph model shared by all detectors."""
import json
import os
import re
import subprocess

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "out", ".next", ".nuxt",
    ".svelte-kit", ".output", ".vercel", ".netlify", ".turbo", ".cache", "coverage",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache", ".pytest_cache",
    "target", ".gradle", ".idea", ".vscode", ".terraform", ".serverless",
    ".aws-sam", "cdk.out", ".wrangler", ".ruah", "Pods", "DerivedData",
    "bower_components", ".expo", ".dart_tool",
}

MAX_FILE_BYTES = 1_000_000


class Model:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.nodes = {}
        self.edges = {}
        self.detectors = set()
        self.warnings = []
        self.stack = {"languages": {}, "frameworks": set(), "package_managers": set()}
        self.env_keys = {}

    # -- graph ------------------------------------------------------------
    def node(self, id, label=None, layer="code", kind="component", **attrs):
        n = self.nodes.get(id)
        if n is None:
            n = {"id": id, "label": label or id, "layer": layer, "kind": kind}
            self.nodes[id] = n
        elif label and n.get("label") == n["id"]:
            n["label"] = label
        evidence = attrs.pop("evidence", None)
        meta = attrs.pop("meta", None)
        for k, v in attrs.items():
            if v is not None and k not in n:
                n[k] = v
        if meta:
            n.setdefault("meta", {}).update({k: v for k, v in meta.items() if v not in (None, "", [], {})})
        if evidence:
            ev = n.setdefault("evidence", [])
            if evidence not in ev and len(ev) < 12:
                ev.append(evidence)
        return n

    def edge(self, source, target, kind, label=None, weight=1):
        if source == target or source is None or target is None:
            return
        key = (source, target, kind)
        e = self.edges.get(key)
        if e is None:
            e = {"source": source, "target": target, "kind": kind, "weight": 0}
            if label:
                e["label"] = label
            self.edges[key] = e
        e["weight"] += weight

    # -- files ------------------------------------------------------------
    def rel(self, path):
        return os.path.relpath(path, self.root).replace(os.sep, "/")

    def abspath(self, rel):
        return os.path.join(self.root, rel)

    def read(self, rel):
        p = self.abspath(rel)
        try:
            if os.path.getsize(p) > MAX_FILE_BYTES:
                return ""
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except OSError:
            return ""

    def to_json(self):
        nodes = list(self.nodes.values())
        ids = {n["id"] for n in nodes}
        # drop dangling edges, drop parents that don't exist
        for n in nodes:
            if n.get("parent") and n["parent"] not in ids:
                n.pop("parent")
        edges = [e for e in self.edges.values() if e["source"] in ids and e["target"] in ids]
        return {
            "version": 1,
            "repo": repo_info(self.root),
            "stack": {
                "languages": dict(sorted(self.stack["languages"].items(), key=lambda kv: -kv[1])),
                "frameworks": sorted(self.stack["frameworks"]),
                "package_managers": sorted(self.stack["package_managers"]),
            },
            "env_keys": self.env_keys,
            "detectors": sorted(self.detectors),
            "warnings": self.warnings,
            "nodes": nodes,
            "edges": edges,
        }


def repo_info(root):
    info = {"name": os.path.basename(os.path.abspath(root)), "path": os.path.abspath(root)}

    def git(*args):
        try:
            return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return ""

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch:
        info["git"] = {"branch": branch, "commit": git("rev-parse", "--short", "HEAD"),
                       "remote": re.sub(r"//[^@/]+@", "//", git("config", "--get", "remote.origin.url"))}
    return info


def list_files(root):
    """Repo-relative file list. Uses git (respects .gitignore) when possible."""
    files = []
    try:
        r = subprocess.run(["git", "-C", root, "ls-files", "-co", "--exclude-standard", "-z"],
                           capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout:
            for f in r.stdout.decode("utf-8", "ignore").split("\0"):
                if f and not any(p in SKIP_DIRS for p in f.split("/")[:-1]) and os.path.isfile(os.path.join(root, f)):
                    files.append(f)
            return files
    except Exception:
        pass
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") or d in (".github", ".circleci")]
        for fn in filenames:
            files.append(os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/"))
        if len(files) > 200_000:
            break
    return files


def strip_jsonc(text):
    """Remove // and /* */ comments and trailing commas (outside strings)."""
    out, i, n, q = [], 0, len(text), None
    while i < n:
        c = text[i]
        if q:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == q:
                q = None
        elif c == '"':
            q = c
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_json(text, jsonc=False):
    try:
        return json.loads(strip_jsonc(text) if jsonc else text)
    except Exception:
        try:
            return json.loads(strip_jsonc(text))
        except Exception:
            return None


def load_toml(text):
    try:
        import tomllib
        return tomllib.loads(text)
    except Exception:
        return None
