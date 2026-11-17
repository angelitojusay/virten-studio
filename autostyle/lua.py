"""Minimal parser for the Lua table literals Lightroom stores in its catalog
(Adobe_imageDevelopSettings.text looks like ``s = { Exposure2012 = 0.44, ... }``)."""
import re

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<num>-?(?:\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?))
      | (?P<str>"(?:[^"\\]|\\.)*")
      | (?P<name>[A-Za-z_]\w*)
      | (?P<sym>[\[\]{}=,;])
    )""",
    re.S | re.X,
)

_ESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def _unescape(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if nxt.isdigit():
            j = i + 1
            while j < len(s) and j < i + 4 and s[j].isdigit():
                j += 1
            out.append(chr(int(s[i + 1:j])))
            i = j
        else:
            out.append(_ESC.get(nxt, nxt))
            i += 2
    return "".join(out)


def _tokenize(text):
    toks, pos, n = [], 0, len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError(f"Unexpected character at {pos}: {text[pos:pos + 20]!r}")
        pos = m.end()
        kind = m.lastgroup
        toks.append((kind, m.group(kind)))
    return toks


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else (None, None)

    def take(self, sym=None):
        tok = self.peek()
        if sym is not None and tok != ("sym", sym):
            raise ValueError(f"Expected {sym!r}, got {tok!r}")
        self.i += 1
        return tok

    def value(self):
        kind, v = self.peek()
        if kind == "sym" and v == "{":
            return self.table()
        self.i += 1
        if kind == "num":
            f = float(v)
            return int(f) if re.fullmatch(r"-?\d+", v) else f
        if kind == "str":
            return _unescape(v[1:-1])
        if kind == "name":
            return {"true": True, "false": False, "nil": None}.get(v, v)
        raise ValueError(f"Unexpected token {v!r}")

    def table(self):
        self.take("{")
        named, positional = {}, []
        while self.peek() != ("sym", "}"):
            kind, v = self.peek()
            if kind == "name" and self.peek(1) == ("sym", "="):
                self.i += 2
                named[v] = self.value()
            elif (kind, v) == ("sym", "["):
                self.i += 1
                key = self.value()
                self.take("]")
                self.take("=")
                named[key] = self.value()
            else:
                positional.append(self.value())
            if self.peek() in (("sym", ","), ("sym", ";")):
                self.i += 1
        self.take("}")
        if not named:
            return positional
        for idx, v in enumerate(positional, 1):
            named[idx] = v
        return named


def parse_settings(text):
    """Parse ``s = { ... }`` into a Python dict. Returns {} for empty/None."""
    if not text:
        return {}
    p = _Parser(_tokenize(text))
    if p.peek()[0] == "name" and p.peek(1) == ("sym", "="):
        p.i += 2
    result = p.value()
    return result if isinstance(result, dict) else {}
