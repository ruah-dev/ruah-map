"""YAML loading with a stdlib-only fallback.

Uses PyYAML when it is installed (with CloudFormation-style tags kept as
strings). Otherwise falls back to a small subset parser that understands the
YAML people actually write in compose files, k8s manifests, CI workflows,
serverless.yml and CloudFormation: block maps/lists, flow collections, quoted
scalars, block scalars, tags and anchors (aliases are not expanded).
"""
import re

try:  # pragma: no cover - depends on environment
    import yaml as _pyyaml

    class _TagLoader(_pyyaml.SafeLoader):
        pass

    def _tag(loader, tag_suffix, node):
        if isinstance(node, _pyyaml.ScalarNode):
            return f"!{tag_suffix} {loader.construct_scalar(node)}"
        if isinstance(node, _pyyaml.SequenceNode):
            return {f"Fn::{tag_suffix}": loader.construct_sequence(node, deep=True)}
        return {f"Fn::{tag_suffix}": loader.construct_mapping(node, deep=True)}

    _TagLoader.add_multi_constructor("!", _tag)
except ImportError:  # pragma: no cover
    _pyyaml = None


def load_all(text):
    """Return a list of documents. Never raises; unparsable docs are skipped."""
    if _pyyaml is not None:
        try:
            return [d for d in _pyyaml.load_all(text, Loader=_TagLoader) if d is not None]
        except Exception:
            pass  # fall through to the lenient parser
    docs = []
    for chunk in re.split(r"^---[ \t]*(?:#.*)?$|^\.\.\.[ \t]*$", text, flags=re.M):
        if not chunk.strip():
            continue
        try:
            d = _MiniParser(chunk).parse()
        except Exception:
            continue
        if d is not None:
            docs.append(d)
    return docs


def load(text):
    docs = load_all(text)
    return docs[0] if docs else None


# --------------------------------------------------------------------------
# Fallback parser
# --------------------------------------------------------------------------

def _strip_comment(s):
    q = None
    for i, ch in enumerate(s):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'" and (i == 0 or s[i - 1] in " \t:-[{,"):
            q = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s.rstrip()


def _split_key(content):
    """Split 'key: rest' -> (key, rest). Returns None if not a mapping entry."""
    if content.startswith(("\"", "'")):
        q = content[0]
        end = content.find(q, 1)
        if end == -1:
            return None
        after = content[end + 1:]
        if after.startswith(":") and (len(after) == 1 or after[1] in " \t"):
            return content[1:end], after[1:].strip()
        return None
    if content.startswith(("[", "{")):
        return None
    m = re.match(r"^([^#]*?)(?<!:):(?:[ \t]+|$)(.*)$", content)
    if not m:
        return None
    key = m.group(1).strip()
    if not key or key.startswith(("- ", "? ")):
        return None
    return key, m.group(2).strip()


def _scalar(s):
    s = s.strip()
    if s.startswith("&"):  # anchor
        parts = s.split(None, 1)
        s = parts[1] if len(parts) > 1 else ""
    if not s:
        return None
    if s[0] == '"' and s.endswith('"') and len(s) > 1:
        return bytes(s[1:-1], "utf-8").decode("unicode_escape", errors="ignore")
    if s[0] == "'" and s.endswith("'") and len(s) > 1:
        return s[1:-1].replace("''", "'")
    if s[0] in "[{":
        try:
            v, _ = _flow(s, 0)
            return v
        except Exception:
            return s
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"[-+]?\d+", s):
        try:
            return int(s)
        except ValueError:
            return s
    if re.fullmatch(r"[-+]?\d*\.\d+([eE][-+]?\d+)?", s):
        return float(s)
    return s


def _flow(s, i):
    """Parse a flow collection starting at s[i]. Returns (value, next_index)."""
    def skip_ws(j):
        while j < len(s) and s[j] in " \t\n,":
            j += 1
        return j

    opener = s[i]
    closer = "]" if opener == "[" else "}"
    i += 1
    out = [] if opener == "[" else {}
    while True:
        i = skip_ws(i)
        if i >= len(s):
            raise ValueError("unterminated flow")
        if s[i] == closer:
            return out, i + 1
        if s[i] in "[{":
            val, i = _flow(s, i)
            tok = None
        else:
            j = i
            if s[i] in "\"'":
                q = s[i]
                j = s.index(q, i + 1) + 1
            depth = 0
            while j < len(s):
                c = s[j]
                if c in "[{":
                    depth += 1
                elif c in "]}":
                    if depth == 0:
                        break
                    depth -= 1
                elif c == "," and depth == 0:
                    break
                elif c == ":" and opener == "{" and depth == 0 and (j + 1 < len(s) and s[j + 1] in " \t"):
                    break
                j += 1
            tok = s[i:j].strip()
            i = j
            val = _scalar(tok)
        if opener == "{":
            i = skip_ws(i) if i < len(s) and s[i] != ":" else i
            if i < len(s) and s[i] == ":":
                i += 1
                while i < len(s) and s[i] in " \t":
                    i += 1
                if s[i] in "[{":
                    v2, i = _flow(s, i)
                else:
                    j = i
                    depth = 0
                    while j < len(s) and not (depth == 0 and s[j] in ",}"):
                        if s[j] in "[{":
                            depth += 1
                        elif s[j] in "]}":
                            depth -= 1
                        j += 1
                    v2 = _scalar(s[i:j])
                    i = j
                out[str(val)] = v2
            else:
                out[str(val)] = None
        else:
            out.append(val)


class _MiniParser:
    def __init__(self, text):
        self.raw = text.replace("\t", "  ").split("\n")
        self.lines = []  # (indent, content, raw_index)
        for idx, line in enumerate(self.raw):
            c = _strip_comment(line)
            if not c.strip() or c.strip().startswith("%"):
                continue
            self.lines.append((len(c) - len(c.lstrip(" ")), c.strip(), idx))

    def parse(self):
        if not self.lines:
            return None
        v, _ = self._block(0, self.lines[0][0])
        return v

    def _block(self, i, indent):
        if i >= len(self.lines):
            return None, i
        content = self.lines[i][1]
        if content == "-" or content.startswith("- "):
            return self._seq(i, indent)
        if _split_key(content) is None:
            # plain multi-line scalar
            parts = []
            while i < len(self.lines) and self.lines[i][0] >= indent:
                parts.append(self.lines[i][1])
                i += 1
            return _scalar(" ".join(parts)), i
        return self._map(i, indent)

    def _seq(self, i, indent):
        out = []
        while i < len(self.lines):
            ind, content, raw = self.lines[i]
            if ind != indent or not (content == "-" or content.startswith("- ")):
                break
            rest = content[1:].lstrip()
            if not rest:
                if i + 1 < len(self.lines) and self.lines[i + 1][0] > indent:
                    v, i = self._block(i + 1, self.lines[i + 1][0])
                else:
                    v, i = None, i + 1
                out.append(v)
                continue
            offset = len(content) - len(rest)
            if rest.startswith("- ") or _split_key(rest) is not None:
                self.lines[i] = (indent + offset, rest, raw)
                v, i = self._block(i, indent + offset)
            else:
                v, i = self._value(rest, i, indent)
            out.append(v)
        return out, i

    def _map(self, i, indent):
        out = {}
        while i < len(self.lines):
            ind, content, raw = self.lines[i]
            if ind != indent or content.startswith("- ") or content == "-":
                break
            kv = _split_key(content)
            if kv is None:
                i += 1
                continue
            key, rest = kv
            out[key] = None
            out[key], i = self._value(rest, i, indent, allow_same_indent_seq=True)
        return out, i

    def _value(self, rest, i, indent, allow_same_indent_seq=False):
        # strip tag-only / anchor-only prefixes
        tag = ""
        if rest.startswith("!"):
            parts = rest.split(None, 1)
            tag = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
        if rest.startswith("&"):
            parts = rest.split(None, 1)
            rest = parts[1] if len(parts) > 1 else ""
        if not rest:
            nxt = i + 1
            if nxt < len(self.lines):
                nind, ncontent, _ = self.lines[nxt]
                if nind > indent:
                    v, j = self._block(nxt, nind)
                    return ({f"Fn::{tag[1:]}": v} if tag else v), j
                if allow_same_indent_seq and nind == indent and (ncontent.startswith("- ") or ncontent == "-"):
                    return self._seq(nxt, indent)
            return None, i + 1
        if rest[0] in "|>":
            raw_idx = self.lines[i][2]
            buf = []
            k = raw_idx + 1
            while k < len(self.raw):
                line = self.raw[k]
                if line.strip() and (len(line) - len(line.lstrip(" "))) <= indent:
                    break
                buf.append(line)
                k += 1
            j = i + 1
            while j < len(self.lines) and self.lines[j][2] < k:
                j += 1
            text = "\n".join(b.strip() for b in buf).strip("\n")
            return ((tag + " " + text) if tag else text), j
        if rest[0] in "[{":
            # flow collection may span several lines
            buf = rest
            j = i
            while buf.count(rest[0]) > buf.count("]" if rest[0] == "[" else "}") and j + 1 < len(self.lines):
                j += 1
                buf += " " + self.lines[j][1]
            return _scalar(buf), j + 1
        if rest.startswith("*"):
            return rest, i + 1  # alias, not expanded
        v = _scalar(rest)
        if tag:
            v = f"{tag} {rest}"
        return v, i + 1
