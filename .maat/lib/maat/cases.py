"""The casebook: recorded maintainer rulings, each tied to the rule it interprets.

A case file is Markdown with a frontmatter block between two `---` lines.
See docs/superpowers/specs/2026-11-22-casebook-design.md.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import lint as rules_lint
from .lint import Finding

STATUSES = ("good", "questioned", "overruled", "codified", "dormant")
LIVE = ("good", "questioned")
FIELDS = ("case", "headnote", "rule", "rule_sha", "status", "ruled_by", "ruled_on",
          "model_since", "source", "last_applied", "overrules")
DATES = ("ruled_on", "model_since", "last_applied")
HEADNOTE_MAX = 100
BODY_MAX = 15
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_NUMBER = re.compile(r"^[0-9]+$")
_MODEL_DATE = re.compile(r"^Current model date for `--model-since`: ([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", re.M)


class CaseError(Exception):
    """Message form: `<file>: <field>: <what>`, always one line."""

    def __init__(self, path: str, field: str, message: str):
        super().__init__("%s: %s: %s" % (path, field, message))
        self.path, self.field, self.message = path, field, message


@dataclass
class Case:
    case: str
    headnote: str
    rule: int
    rule_sha: str
    status: str
    ruled_by: str
    ruled_on: str
    model_since: str
    source: str
    last_applied: str
    overrules: List[str]
    body: str
    path: str


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def valid_date(s: str) -> bool:
    return _date(s) is not None


def current_model_date(plugin_root: str) -> Optional[str]:
    """The model date recorded in the maat-lessons skill, or None when it cannot be read.

    Every reader of the casebook uses it by default, so a ruling given under
    an older model is not read as good just because a flag was left off.
    """
    try:
        text = (Path(plugin_root) / "skills" / "maat-lessons" / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    m = _MODEL_DATE.search(text)
    return m.group(1) if m else None


def _date(s: str) -> Optional[datetime.date]:
    if not _DATE.match(s):
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def load(path: str) -> Case:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise CaseError(path, "file", str(e).replace("\n", " "))
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CaseError(path, "frontmatter", "the file must start with a `---` line")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise CaseError(path, "frontmatter", "no closing `---` line")
    raw: Dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or key not in FIELDS:
            raise CaseError(path, key or "frontmatter", "not a case field")
        raw[key] = value.strip()
    for field in FIELDS:
        if not raw.get(field):
            raise CaseError(path, field, "required")
    name = Path(path).name
    stem = name[:-3] if name.endswith(".md") else name
    if _unquote(raw["case"]) != stem:
        raise CaseError(path, "case", "must equal the file name without .md (`%s`)" % stem)
    if len(_unquote(raw["headnote"])) > HEADNOTE_MAX:
        raise CaseError(path, "headnote", "longer than %d characters" % HEADNOTE_MAX)
    if not _NUMBER.match(raw["rule"]):
        raise CaseError(path, "rule", "must be a rule number")
    if raw["status"] not in STATUSES:
        raise CaseError(path, "status", "must be one of %s" % ", ".join(STATUSES))
    for field in DATES:
        if _date(raw[field]) is None:
            raise CaseError(path, field, "must be a date as YYYY-MM-DD")
    flow = raw["overrules"]
    if not (flow.startswith("[") and flow.endswith("]")):
        raise CaseError(path, "overrules", "must be a list, `[]` when empty")
    overrules = [_unquote(p) for p in flow[1:-1].split(",") if p.strip()]
    return Case(case=stem, headnote=_unquote(raw["headnote"]), rule=int(raw["rule"]),
                rule_sha=_unquote(raw["rule_sha"]), status=raw["status"],
                ruled_by=_unquote(raw["ruled_by"]), ruled_on=raw["ruled_on"],
                model_since=raw["model_since"], source=_unquote(raw["source"]),
                last_applied=raw["last_applied"], overrules=overrules,
                body="\n".join(lines[end + 1:]).strip("\n") + "\n", path=path)


def load_all(directory: str, on_error: Optional[Callable[[CaseError], None]] = None) -> List[Case]:
    """Every case in the directory, oldest ruling first. `[]` when there is no directory.

    With `on_error`, a malformed case is reported to it and skipped; without, it raises.
    """
    d = Path(directory)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.md")):
        if p.name == "README.md":
            continue
        try:
            out.append(load(str(p)))
        except CaseError as e:
            if on_error is None:
                raise
            on_error(e)
    out.sort(key=lambda c: (c.ruled_on, c.case))
    return out


def stale_reason(case: Case, agents_text: str, *, today: str, model_since: Optional[str] = None,
                 dormant_days: int = 180) -> Optional[str]:
    """Why a case stored as good is not good today, or None when it is."""
    live = rules_lint.rule_sha(agents_text, case.rule)
    if live is None:
        return "rule %d no longer exists" % case.rule
    if live != case.rule_sha:
        return "rule %d has changed since the ruling" % case.rule
    if model_since and case.model_since < model_since:
        return "the ruling predates the current model"
    if (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(case.last_applied)).days > dormant_days:
        return "not applied in %d days" % dormant_days
    return None


def effective_status(case: Case, agents_text: str, *, today: str, model_since: Optional[str] = None,
                     dormant_days: int = 180) -> str:
    """The status a reader must use: the stored one, downgraded when the case has gone stale."""
    if case.status != "good":
        return case.status
    reason = stale_reason(case, agents_text, today=today, model_since=model_since,
                          dormant_days=dormant_days)
    if reason is None:
        return "good"
    return "dormant" if reason.startswith("not applied") else "questioned"


def good_cases(all_cases: List[Case], agents_text: str, *, today: str,
               model_since: Optional[str] = None) -> List[Case]:
    return [c for c in all_cases
            if effective_status(c, agents_text, today=today, model_since=model_since) == "good"]


def lint(all_cases: List[Case], agents_text: str, maintainers: List[str], *, today: str,
         model_since: Optional[str] = None, cap: int = 5, dormant_days: int = 180) -> List[Finding]:
    findings: List[Finding] = []
    by_name = {c.case: c for c in all_cases}
    live_per_rule: Dict[int, int] = {}
    for c in all_cases:
        eff = effective_status(c, agents_text, today=today, model_since=model_since,
                               dormant_days=dormant_days)
        if c.status == "good" and eff != "good":
            reason = stale_reason(c, agents_text, today=today, model_since=model_since,
                                  dormant_days=dormant_days)
            fix = ("mark it dormant" if eff == "dormant"
                   else "mark it questioned or have a maintainer reaffirm it")
            findings.append(Finding("error", 0, "case %s: stored as good but %s; %s" % (c.case, reason, fix)))
        if eff in LIVE:
            live_per_rule[c.rule] = live_per_rule.get(c.rule, 0) + 1
        if c.ruled_by not in maintainers:
            findings.append(Finding("error", 0, "case %s: ruled_by `%s` is not a maintainer in the charter"
                                    % (c.case, c.ruled_by)))
        for name in c.overrules:
            target = by_name.get(name)
            if target is None:
                findings.append(Finding("error", 0, "case %s: overrules `%s`, which is not a case"
                                        % (c.case, name)))
            elif target.status in LIVE:
                findings.append(Finding("error", 0, "case %s: overruled by %s but stored as %s"
                                        % (target.case, c.case, target.status)))
        body_lines = len([l for l in c.body.splitlines() if l.strip()])
        if body_lines > BODY_MAX:
            findings.append(Finding("warn", 0, "case %s: body is %d lines, keep a case to about fifteen"
                                    % (c.case, body_lines)))
    for rule in sorted(live_per_rule):
        if live_per_rule[rule] > cap:
            findings.append(Finding("error", 0, "rule %d has %d live cases, cap is %d: codify, overrule "
                                    "or let one lapse" % (rule, live_per_rule[rule], cap)))
    return findings
