"""Charter parser: a fixed YAML subset plus validation against the v1 schema.

Subset: `key: value` lines, one level of nesting (two-space indent), scalars
(bool, int, str, quotes optional), flow lists `[a, "b, c"]`, `#` comments
outside quotes. Nothing else.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


class CharterError(Exception):
    """Message form: `<file>:<line>: <what>` (line 0 when no single line applies)."""


def _fail(filename: str, line: int, what: str) -> CharterError:
    return CharterError("%s:%d: %s" % (filename, line, what))


def _strip_comment(s: str) -> str:
    quote = None
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'" and s[:i].rstrip()[-1:] in (":", "[", ","):
            quote = ch
        elif ch == "#" and (i == 0 or s[i - 1].isspace()):
            return s[:i]
    return s


def _split_flow(s: str) -> List[str]:
    parts, cur, quote = [], [], None
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'" and not "".join(cur).strip():
            quote = ch
            cur.append(ch)
        elif ch == ",":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if quote:
        raise ValueError("unterminated quote")
    parts.append("".join(cur))
    return [p.strip() for p in parts]


def _scalar(s: str) -> Any:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    if s[:1] in "\"'":
        raise ValueError("unterminated quote")
    if s == "true":
        return True
    if s == "false":
        return False
    if s.lstrip("-").isdigit():
        return int(s)
    return s


def _value(s: str) -> Any:
    if s.startswith("["):
        if not s.endswith("]"):
            raise ValueError("unterminated list")
        inner = s[1:-1].strip()
        if not inner:
            return []
        items = _split_flow(inner)
        if any(i == "" for i in items):
            raise ValueError("empty list item")
        return [_scalar(i) for i in items]
    return _scalar(s)


def _parse(text: str, filename: str) -> Tuple[Dict[str, Any], Dict[str, int]]:
    data: Dict[str, Any] = {}
    lines: Dict[str, int] = {}  # dotted key -> line number
    section: Optional[str] = None  # open top-level mapping
    for n, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise _fail(filename, n, "tab in indentation; use spaces")
        body = _strip_comment(raw).rstrip()
        if not body.strip():
            continue
        indent = len(body) - len(body.lstrip(" "))
        if indent not in (0, 2):
            raise _fail(filename, n, "indentation must be 0 or 2 spaces (only one level of nesting)")
        key, sep, rest = body.strip().partition(":")
        key, rest = key.strip(), rest.strip()
        if not sep or not key or " " in key:
            raise _fail(filename, n, "expected `key: value`")
        if indent == 2:
            if section is None:
                raise _fail(filename, n, "indented key `%s` has no parent key" % key)
            if rest == "":
                raise _fail(filename, n, "`%s.%s` has no value (nesting is limited to two levels)" % (section, key))
            target, dotted = data[section], section + "." + key
        else:
            section = None
            target, dotted = data, key
        if key in target:
            raise _fail(filename, n, "duplicate key `%s`" % dotted)
        if rest == "" and indent == 0:
            target[key] = {}
            section = key
        else:
            try:
                target[key] = _value(rest)
            except ValueError as e:
                raise _fail(filename, n, "`%s`: %s" % (dotted, e))
        lines[dotted] = n
    return data, lines


def parse(text: str) -> Dict[str, Any]:
    """Parse the charter subset into a dict (no schema validation)."""
    return _parse(text, "charter.yaml")[0]


@dataclass
class Project:
    name: str
    purpose: str
    repo: str
    visibility: str


@dataclass
class Work:
    protected_branch: str
    worktree_root: str
    setup_command: str
    tracker: str = "beads"
    bead_prefix: str = ""
    beads_mode: str = ""
    tools_dir: str = ""


@dataclass
class CI:
    required_checks: List[str]


@dataclass
class People:
    maintainers: List[str]
    agents: List[str]


@dataclass
class Guards:
    server_lock: bool


@dataclass
class Rules:
    project: List[str]


@dataclass
class Charter:
    project: Project
    work: Work
    ci: CI
    people: People
    guards: Guards
    rules: Rules


_STR, _BOOL, _LIST = "str", "bool", "list of strings"
_ENUMS = {
    "project.visibility": ("public", "private"),
    "work.beads_mode": ("single-clone", "dolt-remote"),
    "work.tracker": ("beads", "github-issues"),
    "work.tools_dir": (".maat", "."),
}
_SECTIONS = [
    ("project", Project), ("work", Work), ("ci", CI),
    ("people", People), ("guards", Guards), ("rules", Rules),
]
_TYPES = {
    "project.name": _STR, "project.purpose": _STR, "project.repo": _STR,
    "project.visibility": _STR, "work.bead_prefix": _STR,
    "work.protected_branch": _STR, "work.worktree_root": _STR,
    "work.setup_command": _STR, "work.beads_mode": _STR,
    "work.tracker": _STR, "work.tools_dir": _STR,
    "ci.required_checks": _LIST, "people.maintainers": _LIST,
    "people.agents": _LIST, "guards.server_lock": _BOOL, "rules.project": _LIST,
}


def _type_ok(v: Any, t: str) -> bool:
    if t == _BOOL:
        return isinstance(v, bool)
    if t == _STR:
        return isinstance(v, str) and v != ""
    return isinstance(v, list) and all(isinstance(i, str) for i in v)


def parse_charter(text: str, filename: str = "charter.yaml") -> Charter:
    data, lines = _parse(text, filename)

    def at(dotted: str) -> int:
        return lines.get(dotted, 0)

    allowed = {"maat"} | {s for s, _ in _SECTIONS}
    for k in data:
        if k not in allowed:
            raise _fail(filename, at(k), "unknown key `%s`" % k)
    if "maat" not in data:
        raise _fail(filename, 0, "missing key `maat` (expected `maat: 1`)")
    if data["maat"] != 1 or isinstance(data["maat"], bool):
        raise _fail(filename, at("maat"), "`maat` must be 1")

    built = {}
    for name, cls in _SECTIONS:
        if name not in data:
            raise _fail(filename, 0, "missing section `%s`" % name)
        sec = data[name]
        if not isinstance(sec, dict):
            raise _fail(filename, at(name), "`%s` must be a mapping" % name)
        fields = [f.name for f in dataclasses.fields(cls)]
        for k in sec:
            if k not in fields:
                raise _fail(filename, at(name + "." + k), "unknown key `%s.%s`" % (name, k))
        for f in fields:
            d = name + "." + f
            if f not in sec:
                if d in ("work.tracker", "work.tools_dir") or (
                        d in ("work.bead_prefix", "work.beads_mode")
                        and sec.get("tracker") == "github-issues"):
                    continue
                raise _fail(filename, 0, "missing key `%s`" % d)
            if d == "work.tools_dir" and sec.get("tracker", "beads") != "github-issues":
                raise _fail(filename, at(d), "`work.tools_dir` needs `work.tracker: github-issues`")
            t = _TYPES[d]
            if not _type_ok(sec[f], t):
                raise _fail(filename, at(d), "`%s` must be %s" % (d, "a non-empty string" if t == _STR else "true or false" if t == _BOOL else "a list of strings"))
            if d in _ENUMS and sec[f] not in _ENUMS[d]:
                raise _fail(filename, at(d), "`%s` must be one of %s, got `%s`" % (d, ", ".join(_ENUMS[d]), sec[f]))
        if name == "work" and sec.get("tracker") == "github-issues":
            sec = dict(sec)
            sec.setdefault("tools_dir", ".maat")
        built[name] = cls(**sec)
    if not built["people"].maintainers:
        raise _fail(filename, at("people.maintainers"), "`people.maintainers` needs at least one maintainer")
    return Charter(**built)


def load(path: str) -> Charter:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return parse_charter(text, str(path))
