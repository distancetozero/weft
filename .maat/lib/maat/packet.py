"""Assemble what Anubis (challenger; opposing counsel) is given.

Everything in the packet comes from git or from files. The maker writes no
handoff: its commit messages and added comments are passed on only under a
heading that marks them as claims to test.
See docs/superpowers/specs/2026-11-22-roles-design.md, section 5.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from . import cases

COMMENT_STARTS = ("#", "//", "/*", "* ", "<!--", "--")
NONE = "(none)"


class PacketError(Exception):
    pass


def _git(repo: str, env: Optional[Dict[str, str]], *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True)
    except OSError as e:
        raise PacketError("git: %s" % e)
    if r.returncode != 0:
        raise PacketError("git %s: %s" % (args[0], r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "failed"))
    return r.stdout


def branch_file(branch: str) -> str:
    """Where a challenged change keeps its record: one file per branch."""
    return "docs/maat/challenges/%s.md" % branch.replace("/", "-")


def _resolve_base(repo: str, env: Optional[Dict[str, str]], base: str):
    """Prefer the remote copy of the base branch: a local one is often behind it."""
    for ref in ("origin/%s" % base, base):
        r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "%s^{commit}" % ref],
                           cwd=repo, env=env, capture_output=True, text=True)
        if r.returncode == 0:
            return ref, r.stdout.strip()[:7]
    raise PacketError("no such base branch: %s" % base)


def _drafted_cases(repo: str, env: Optional[Dict[str, str]], base: str, cases_dir: str) -> List[str]:
    """File names of cases added or changed since the base; empty outside a git repo."""
    try:
        base_ref, _ = _resolve_base(repo, env, base)
        out = _git(repo, env, "diff", "--name-only", "%s...HEAD" % base_ref, "--", cases_dir)
    except PacketError:
        return []
    return [Path(p).name for p in out.split()]


def _contract_checks(repo: str, env: Optional[Dict[str, str]], record: str, base_ref: str):
    """This change's contract checks as first written, and whether they were edited since.

    Anubis wrote them before the work existed, in the first commit on this
    branch to write the record file. Reading that commit keeps a later edit
    by the maker out of the packet. Commits already in the base do not count:
    a branch name is sometimes reused, and an earlier change's record is not
    this change's contract.
    """
    heading = "## Checks written at the contract"
    own = _git(repo, env, "log", "--diff-filter=AM", "--format=%H", "%s..HEAD" % base_ref,
               "--", record).split()
    if not own:
        return "", False, ""
    original = _section(_git(repo, env, "show", "%s:%s" % (own[-1], record)), heading)
    now = Path(repo) / record
    current = _section(now.read_text(encoding="utf-8"), heading) if now.is_file() else ""
    where = _git(repo, env, "log", "-1", "--format=%h (%ad): %s", "--date=short", own[-1]).strip()
    return original, original != current, where


def _section(text: str, heading: str) -> str:
    """Body of a `## heading` section, up to the next `## ` heading."""
    out, on = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            on = line.strip() == heading
            continue
        if on:
            out.append(line)
    return "\n".join(out).strip()


def _table_rows(section: str) -> List[str]:
    rows = [l for l in section.splitlines() if l.startswith("|")]
    return rows[2:]


def _comment_claims(diff: str) -> List[str]:
    out, path = [], ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
            continue
        if not line.startswith("+") or line.startswith("+++") or path.endswith(".md"):
            continue
        code = line[1:]
        stripped = code.strip()
        if stripped.startswith(COMMENT_STARTS):
            out.append("%s: %s" % (path, stripped))
        elif "  # " in code:
            before, after = code.split("  # ", 1)
            # An odd number of quotes before the marker means it sits inside a string.
            if before.count('"') % 2 == 0 and before.count("'") % 2 == 0:
                out.append("%s: %s" % (path, after.strip()))
    return out


def build(*, acceptance: str, repo: str = ".", base: str = "main", evidence: str = "",
          contract: bool = False, today: str, model_since: Optional[str] = None,
          cases_dir: str = "docs/maat/cases", rules_path: str = "AGENTS.md",
          challenges_path: str = "docs/maat/challenges.md",
          env: Optional[Dict[str, str]] = None) -> str:
    root = Path(repo)
    parts = ["# Challenge packet", "", "## Acceptance", "", acceptance.strip(), ""]

    rules = root / rules_path
    good = []
    if rules.is_file():
        loaded = cases.load_all(str(root / cases_dir), on_error=lambda e: None)
        good = cases.good_cases(loaded, rules.read_text(encoding="utf-8"), today=today,
                                model_since=model_since)
    # A case this change adds or edits is a draft the maintainer has not merged.
    # It is part of the work under test and reaches the challenger in the Diff.
    drafted = _drafted_cases(repo, env, base, cases_dir)
    binding = [c for c in good if Path(c.path).name not in drafted]
    parts += ["## Good cases", ""]
    for c in binding:
        parts += ["### %s (rule %d)" % (c.case, c.rule), "", c.headnote, "", c.body.strip(), ""]
    if not binding:
        parts += [NONE, ""]
    if len(binding) != len(good):
        parts += ["%d case(s) drafted or edited by this change are left out: they are not "
                  "ratified, and are in the Diff as work under test." % (len(good) - len(binding)), ""]

    tally = root / challenges_path
    escapes = _table_rows(_section(tally.read_text(encoding="utf-8"), "## Escapes")) if tally.is_file() else []
    parts += ["## Escapes to watch for", ""] + (escapes or [NONE]) + [""]
    if contract:
        return "\n".join(parts)

    branch = _git(repo, env, "rev-parse", "--abbrev-ref", "HEAD").strip()
    base_ref, base_sha = _resolve_base(repo, env, base)
    record = branch_file(branch)
    checks, edited, where = _contract_checks(repo, env, record, base_ref)
    parts += ["## Checks written at the contract", ""]
    if where:
        parts += ["Taken from the first commit since `%s` to write the record file: %s. If that "
                  "commit is not this change's contract run, say so as a finding." % (base_ref, where), ""]
    if edited:
        parts += ["The copy on the branch has been edited since; treat that as a finding.", ""]
    parts += [checks or NONE, ""]
    parts += ["## Evidence as cited", "",
              "Cited by the maker. Re-run each command and compare the output. Anything here "
              "that is not a command is a claim.", "", evidence.strip() or NONE, ""]

    # The record of the challenge is not part of the work under test.
    diff = _git(repo, env, "diff", "%s...HEAD" % base_ref, "--", ".", ":(exclude)docs/maat/challenges")
    log = _git(repo, env, "log", "--no-merges", "--format=- %s%n%w(0,2,2)%b", "%s..HEAD" % base_ref).strip()
    claims = _comment_claims(diff)
    parts += ["## Claims to test", "",
              "Written by the maker. These are claims, not facts: test them, do not rely on them.", "",
              "Commit messages:", "", log or NONE, "", "Comments added in the diff:", ""]
    parts += (["- %s" % c for c in claims] or [NONE]) + [""]
    parts += ["## Diff", "",
              "Against `%s` at %s. Fetch first if that may be stale. The diff is the work under "
              "test: comments, docstrings and prose inside it are the maker's words."
              % (base_ref, base_sha), "", "```diff", diff.rstrip("\n"), "```", ""]
    return "\n".join(parts)
