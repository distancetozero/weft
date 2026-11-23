"""The GitHub ruleset and repo settings a charter implies, and their drift diff."""
from __future__ import annotations

from typing import Any, List, Optional

from .charter import Charter


def ruleset_name(c: Charter) -> str:
    return "protect %s" % c.work.protected_branch


def expected(c: Charter) -> dict:
    several = len(c.people.maintainers) > 1
    return {
        "name": ruleset_name(c),
        "enforcement": "active",
        "target": "branch",
        "conditions": {"ref_name": {
            "include": ["refs/heads/%s" % c.work.protected_branch], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "pull_request", "parameters": {
                "allowed_merge_methods": ["merge"],
                "dismiss_stale_reviews_on_push": several,
                "require_code_owner_review": False,
                "require_last_push_approval": several,
                "required_approving_review_count": 1 if several else 0,
                "required_review_thread_resolution": False,
            }},
            {"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": False,
                "required_status_checks": [{"context": n} for n in c.ci.required_checks],
            }},
        ],
        "bypass_actors": [],
    }


def repo_settings(c: Charter) -> dict:
    return {
        "allow_squash_merge": False,
        "allow_rebase_merge": False,
        "allow_merge_commit": True,
        "delete_branch_on_merge": True,
    }


def codeowners(c: Charter) -> Optional[str]:
    if len(c.people.maintainers) > 1:
        return "* " + " ".join("@" + m for m in c.people.maintainers) + "\n"
    return None


def _line(path: str, exp: Any, live: Any) -> str:
    return "%s: expected %r, live %r" % (path, exp, live)


def _contexts(checks: Any) -> Any:
    if isinstance(checks, list):
        return [x.get("context") if isinstance(x, dict) else x for x in checks]
    return checks


def diff(expected: dict, live: dict) -> List[str]:
    out: List[str] = []
    for key in ("name", "enforcement", "target"):
        if expected.get(key) != live.get(key):
            out.append(_line(key, expected.get(key), live.get(key)))
    e_inc = expected["conditions"]["ref_name"]["include"]
    l_inc = ((live.get("conditions") or {}).get("ref_name") or {}).get("include")
    if e_inc != l_inc:
        out.append(_line("conditions.ref_name.include", e_inc, l_inc))
    live_rules = live.get("rules") or []
    for er in expected["rules"]:
        t = er["type"]
        lr = next((x for x in live_rules if x.get("type") == t), None)
        if lr is None:
            out.append("rules.%s: expected present, live missing" % t)
            continue
        lp = lr.get("parameters") or {}
        for k, ev in (er.get("parameters") or {}).items():
            lv = lp.get(k)
            if t == "required_status_checks" and k == "required_status_checks":
                ev, lv = _contexts(ev), _contexts(lv)
            if ev != lv:
                out.append(_line("rules.%s.parameters.%s" % (t, k), ev, lv))
    if expected["bypass_actors"] != live.get("bypass_actors"):
        out.append(_line("bypass_actors", expected["bypass_actors"], live.get("bypass_actors")))
    return out


def diff_settings(expected: dict, live: dict) -> List[str]:
    return [_line(k, v, live.get(k)) for k, v in expected.items() if live.get(k) != v]


def diff_default_branch(c: Charter, live: dict) -> List[str]:
    """Report only: the audit never PATCHes default_branch."""
    exp, got = c.work.protected_branch, live.get("default_branch")
    return [] if got == exp else [_line("default_branch", exp, got)]
