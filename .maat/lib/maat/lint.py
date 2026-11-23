"""Lint the always-on rules in a rendered AGENTS.md."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional

RULE = re.compile(r"^(\d+)\. ")


@dataclass
class Finding:
    level: str
    line: int
    message: str


@dataclass
class Rule:
    number: int
    line: int
    text: str
    why: Optional[str]
    since: Optional[str]
    retire: Optional[str]


def _parse_comment(lines: List[str], start: int):
    """Parse an HTML comment beginning on lines[start]; return fields or None."""
    # The comment sits among the rule's indented continuation lines.
    while start < len(lines) and lines[start][:1] in (" ", "\t") and lines[start].strip():
        if lines[start].lstrip().startswith("<!--"):
            break
        start += 1
    if start >= len(lines) or not lines[start].lstrip().startswith("<!--"):
        return None
    buf = []
    for i in range(start, len(lines)):
        buf.append(lines[i])
        if "-->" in lines[i]:
            break
    body = " ".join(buf).strip()
    body = body[4:]
    body = body.split("-->", 1)[0]
    fields = {}
    for part in body.split("|"):
        key, sep, value = part.partition(":")
        if sep:
            fields[key.strip().lower()] = value.strip()
    return fields


def always_on_rules(text: str) -> List[Rule]:
    lines = text.splitlines()
    rules = []
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = RULE.match(line)
        if not m:
            continue
        fields = _parse_comment(lines, i + 1)
        if fields is None:
            fields = {}
            has_comment = False
        else:
            has_comment = True
        rule = Rule(int(m.group(1)), i + 1, line[m.end():].strip(),
                    fields.get("why"), fields.get("since"), fields.get("retire"))
        rule._has_comment = has_comment  # type: ignore[attr-defined]
        rules.append(rule)
    return rules


def lint(text: str, *, budget: int = 12, model_since: Optional[str] = None) -> List[Finding]:
    rules = always_on_rules(text)
    findings = []
    if len(rules) > budget:
        findings.append(Finding("error", 0, "%d always-on rules, budget is %d" % (len(rules), budget)))
    for r in rules:
        if not getattr(r, "_has_comment", False):
            findings.append(Finding("warn", r.line, "rule %d has no rationale comment" % r.number))
            continue
        if not r.why:
            findings.append(Finding("warn", r.line, "rule %d comment lacks why" % r.number))
        if not r.retire:
            findings.append(Finding("warn", r.line, "rule %d comment lacks retire" % r.number))
        if model_since and r.since and r.since < model_since:
            findings.append(Finding("warn", r.line,
                                    "rule %d predates the current model; re-evaluate" % r.number))
        if r.retire and r.retire.strip().lower() == "enforced":
            findings.append(Finding("warn", r.line, "rule %d retire condition met?" % r.number))
    return findings


_COMMENT = re.compile(r"<!--.*?-->", re.S)
_HEADING = re.compile(r"^#{1,6} ")


def _rule_body(lines: List[str], start: int) -> str:
    """Text of the rule on lines[start], minus its HTML comments.

    The rule runs to the next rule or the next heading, whatever the
    indentation and across blank lines, so a paragraph added to a rule, or a
    line added under it, is part of what gets hashed.
    """
    parts = [lines[start][RULE.match(lines[start]).end():]]
    in_fence = False
    for line in lines[start + 1:]:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and (RULE.match(line) or _HEADING.match(line)):
            break
        parts.append(line)
    return " ".join(_COMMENT.sub(" ", "\n".join(parts)).split())


def rule_sha(text: str, number: int) -> Optional[str]:
    """Short hash of one always-on rule's text; None when there is no such rule.

    The rationale comment and the wrapping are left out, so only a change to
    the rule's words moves the hash.
    """
    lines = text.splitlines()
    for r in always_on_rules(text):
        if r.number == number:
            body = _rule_body(lines, r.line - 1)
            return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    return None
