"""Render a charter into a project's files: `{{name}}` substitution, nothing more."""
from __future__ import annotations

import dataclasses
import fnmatch
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from lib.maat import rules_file
from lib.maat.charter import Charter

# template file (relative to templates/) -> published path in the project
TEMPLATE_PATHS: Dict[str, str] = {
    "githooks/pre-commit": ".githooks/pre-commit",
    "githooks/pre-push": ".githooks/pre-push",
    "scripts/start-issue.sh": "scripts/start-issue.sh",
    "claude/hooks/bd-prime.sh": ".claude/hooks/bd-prime.sh",
    "claude/settings.json": ".claude/settings.json",
    "claude/rules/README.md": ".claude/rules/README.md",
    "AGENTS.md": "AGENTS.md",
    "CLAUDE.md": "CLAUDE.md",
    "CONTRIBUTING.md": "CONTRIBUTING.md",
    "PULL_REQUEST_TEMPLATE.md": ".github/PULL_REQUEST_TEMPLATE.md",
    "docs/maat/incidents.md": "docs/maat/incidents.md",
    "docs/superpowers/README.md": "docs/superpowers/README.md",
}


def template_paths(c: Charter) -> Dict[str, str]:
    """The template -> published path set for the charter's tracker."""
    if c.work.tracker != "github-issues":
        return dict(TEMPLATE_PATHS)
    paths = {t: p for t, p in TEMPLATE_PATHS.items() if t != "claude/hooks/bd-prime.sh"}
    paths["claude/hooks/hooks-path.sh"] = ".claude/hooks/hooks-path.sh"
    if c.work.tools_dir == ".maat":
        paths["maat-README.md"] = ".maat/README.md"
        paths["maat-gitignore"] = ".maat/.gitignore"
    return paths


def template_file(templates_dir: Path, c: Charter, tpl: str) -> Path:
    """The tracker's own template when it has one, else the shared template."""
    if c.work.tracker == "github-issues":
        own = Path(templates_dir) / "github-issues" / tpl
        if own.is_file():
            return own
    return Path(templates_dir) / tpl


CARRIED_PATHS = ("AGENTS.md", "CLAUDE.md")

PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")


def stamp(version: str, template_bytes: bytes) -> str:
    return "maat %s %s" % (version, hashlib.sha256(template_bytes).hexdigest()[:12])


def _shell_name(name: str) -> str:
    """A valid shell variable name from a project name: upper case, `_` for the rest."""
    env = re.sub(r"[^A-Z0-9]", "_", name.upper())
    return "_" + env if env[:1].isdigit() else env


def variables(c: Charter, version: str) -> Dict[str, str]:
    return {
        "project_name": c.project.name,
        "project_purpose": c.project.purpose,
        "repo": c.project.repo,
        "visibility": c.project.visibility,
        "bead_prefix": c.work.bead_prefix,
        "bead_prefix_upper": re.sub(r"[^A-Z0-9]", "_", c.work.bead_prefix.upper()),
        "protected_branch": c.work.protected_branch,
        "worktree_root": c.work.worktree_root,
        "setup_command": c.work.setup_command,
        # Prose only (AGENTS.md rule 2); code blocks and start-issue.sh keep setup_command.
        "setup_command_prose": ("nothing (no setup step)" if c.work.setup_command == "true"
                                else "`%s`" % c.work.setup_command),
        "beads_mode": c.work.beads_mode,
        "required_checks_list": ", ".join(c.ci.required_checks),
        "maintainers_list": ", ".join(c.people.maintainers),
        "agents_list": ", ".join(c.people.agents),
        "project_rules": "\n".join("%d. %s" % (i, r) for i, r in enumerate(c.rules.project, 10)),
        "maat_version": version,
        "project_env": _shell_name(c.project.name),
    }


def substitute(text: str, values: Dict[str, str], template: str) -> str:
    def one(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name not in values:
            raise KeyError("%s: unknown placeholder {{%s}}" % (template, name))
        return values[name]
    return PLACEHOLDER.sub(one, text)


STAMP_LINE = re.compile(r"<!-- maat \S+ [0-9a-f]{12} -->")


def _is_maat_file(repo_root: Path, path: str, current: str) -> bool:
    """A file maat itself rendered: tracked in the manifest, or opening with a stamp."""
    first = current.split("\n", 1)[0].strip()
    if STAMP_LINE.fullmatch(first):
        return True
    return path in Manifest.load(repo_root / MANIFEST_PATH).files


PROJECT_SKILLS = ("maat-method/SKILL.md", "maat-lessons/SKILL.md",
                  "maat-lessons/server-lock.md", "maat-update/SKILL.md")

_UNSET_SENTENCE = re.compile(
    r" If `\$\{CLAUDE_PLUGIN_ROOT\}`\s+is unset,[^`]*`\.claude-plugin/plugin\.json`\.")
_DEFERRAL = re.compile(r"^> If this repository has `\.claude/skills/.*\n\n?", re.M)


def _project_skill(entry: str, raw: bytes, tools_dir: str, version: str) -> str:
    text = raw.decode("utf-8")
    text = _UNSET_SENTENCE.sub("", text)
    text = text.replace("${CLAUDE_PLUGIN_ROOT}/bin/",
                        ".maat/bin/" if tools_dir == ".maat" else "bin/")
    text = _DEFERRAL.sub("", text)
    line = "<!-- %s -->\n" % stamp(version, raw)
    if entry.endswith("SKILL.md"):
        close = text.find("\n---\n", 4)
        if not text.startswith("---\n") or close < 0:
            raise ValueError("%s: no frontmatter to stamp" % entry)
        cut = close + len("\n---\n")
        text = text[:cut] + line + text[cut:]
    else:
        text = line + text
    if "CLAUDE_PLUGIN_ROOT" in text:
        raise ValueError("%s: a plugin-root reference survived the rewrite" % entry)
    return text


def skill_files(c: Charter, source: Path, version: str
                ) -> Tuple[Dict[str, str], Dict[str, str]]:
    """The project copies of maat's skills: (path -> text, path -> sha256 of the source bytes)."""
    out: Dict[str, str] = {}
    shas: Dict[str, str] = {}
    if c.work.tracker != "github-issues":
        return out, shas
    for entry in PROJECT_SKILLS:
        raw = (Path(source) / "skills" / entry).read_bytes()
        published = ".claude/skills/" + entry
        out[published] = _project_skill(entry, raw, c.work.tools_dir, version)
        shas[published] = hashlib.sha256(raw).hexdigest()
    return out, shas


def render_with_covered(c: Charter, templates_dir: Path, version: str,
                        repo_root: Optional[Path] = None, *, source: Optional[Path] = None
                        ) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, List[str]]]:
    """Return (path -> content, path -> template sha256, path -> covered existing lines).

    With repo_root, an existing AGENTS.md or CLAUDE.md is carried below the maat section.
    """
    base = variables(c, version)
    out = {}
    shas = {}
    covered_lines = {}
    # A repo whose only rules file is CLAUDE.md: its rules belong below the
    # maat section of AGENTS.md, the canonical file; CLAUDE.md is rendered thin.
    lone_claude = lone_claude_md(repo_root) if repo_root is not None else None
    for tpl, published in template_paths(c).items():
        raw = template_file(templates_dir, c, tpl).read_bytes()
        values = dict(base, stamp=stamp(version, raw))
        text = substitute(raw.decode("utf-8"), values, tpl)
        if repo_root is not None and published in CARRIED_PATHS:
            existing = Path(repo_root) / published
            if published == "AGENTS.md" and lone_claude is not None:
                text, covered_lines[published] = rules_file.merge_existing(text, lone_claude)
            elif published == "CLAUDE.md" and lone_claude is not None:
                pass  # carried into AGENTS.md above; CLAUDE.md stays thin
            elif existing.is_file():
                current = existing.read_bytes().decode("utf-8")
                kept = rules_file.keep_below_marker(text, current)
                if kept is not None:
                    text = kept
                elif rules_file.HEADING in current or not _is_maat_file(
                        Path(repo_root), published, current):
                    text, covered_lines[published] = rules_file.merge_existing(text, current)
        out[published] = text
        shas[published] = hashlib.sha256(raw).hexdigest()
    if source is not None:
        skills, skill_shas = skill_files(c, source, version)
        out.update(skills)
        shas.update(skill_shas)
    return out, shas, covered_lines


def lone_claude_md(repo_root: Path) -> Optional[str]:
    """The text of a foreign CLAUDE.md when the repo has no AGENTS.md, else None.

    Foreign means not written by maat: no end marker, no carried-section
    heading, no stamp, not in the manifest.
    """
    repo_root = Path(repo_root)
    claude = repo_root / "CLAUDE.md"
    if (repo_root / "AGENTS.md").is_file() or not claude.is_file():
        return None
    current = claude.read_bytes().decode("utf-8")
    if rules_file.MARKER in current or rules_file.HEADING in current:
        return None
    if _is_maat_file(repo_root, "CLAUDE.md", current):
        return None
    return current


def render_with_meta(c: Charter, templates_dir: Path, version: str,
                     repo_root: Optional[Path] = None, *, source: Optional[Path] = None
                     ) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return (path -> content, path -> sha256 hex of the template bytes)."""
    return render_with_covered(c, templates_dir, version, repo_root, source=source)[:2]


def render(c: Charter, templates_dir: Path, version: str,
           repo_root: Optional[Path] = None, *, source: Optional[Path] = None) -> Dict[str, str]:
    return render_with_covered(c, templates_dir, version, repo_root, source=source)[0]


COPY_GLOBS = (".claude-plugin/plugin.json", "bin/*", "lib/**/*.py", "templates/**/*",
              "skills/**/*.md")
COPY_DIR = ".maat"


def _is_junk(rel: Path) -> bool:
    parts = rel.parts
    return any(p == "__pycache__" or (p.startswith(".") and not (i == 0 and p == ".claude-plugin"))
               for i, p in enumerate(parts))


def copy_files(c: Charter, source: Path) -> Dict[str, str]:
    """The tools copied into an adopting repository: .maat/<path> -> text, byte for byte."""
    out: Dict[str, str] = {}
    if c.work.tracker != "github-issues" or c.work.tools_dir != COPY_DIR:
        return out
    source = Path(source)
    for pattern in COPY_GLOBS:
        for path in sorted(source.glob(pattern)):
            rel = path.relative_to(source)
            if not path.is_file() or _is_junk(rel):
                continue
            try:
                text = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("%s: not UTF-8; the copy holds text only" % rel.as_posix())
            out[COPY_DIR + "/" + rel.as_posix()] = text
    return out


def edited_copy(copied: Dict[str, str], repo_root: Path, manifest: Manifest) -> List[str]:
    """The copied paths under .maat/ whose bytes on disk are not what maat last wrote."""
    out = []
    for path in copied:
        if not path.startswith(COPY_DIR + "/"):
            continue
        dest = Path(repo_root) / path
        if not dest.is_file():
            continue
        entry = manifest.files.get(path)
        if entry is None or hashlib.sha256(dest.read_bytes()).hexdigest() != entry["rendered_sha"]:
            out.append(path)
    return sorted(out)


def source_version(source: Path) -> str:
    with open(Path(source) / ".claude-plugin" / "plugin.json", encoding="utf-8") as f:
        return json.load(f)["version"]


def copy_version(repo_root: Path) -> Optional[str]:
    path = Path(repo_root) / COPY_DIR / ".claude-plugin" / "plugin.json"
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)["version"]


def _version_key(v: str) -> Tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def older_than(a: str, b: str) -> bool:
    return _version_key(a) < _version_key(b)


MANIFEST_PATH = "docs/maat/manifest.json"
EXECUTABLE_PATTERNS = [".githooks/*", "scripts/*.sh", ".claude/hooks/*.sh", ".maat/bin/*"]
STAMP_VERSION = re.compile(r"maat \S+ ([0-9a-f]{12})")


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_executable_path(path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, pat) for pat in EXECUTABLE_PATTERNS)


@dataclasses.dataclass
class Manifest:
    maat_version: str
    files: Dict[str, Dict[str, str]]

    @classmethod
    def empty(cls) -> "Manifest":
        return cls(maat_version="", files={})

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        p = Path(path)
        if not p.is_file():
            return cls.empty()
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return cls(maat_version=data["maat_version"], files=data["files"])

    def save(self, path: Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            json.dump({"maat_version": self.maat_version, "files": self.files},
                      f, indent=2, sort_keys=True)
            f.write("\n")


@dataclasses.dataclass
class Piles:
    new: List[str]
    unchanged: List[str]
    maat_changed: List[str]
    hand_changed: List[str]
    retired: List[str] = dataclasses.field(default_factory=list)


def _normalise(text: str) -> str:
    """Drop the version from the stamp: a version bump alone is not a change."""
    return STAMP_VERSION.sub(r"maat VERSION \1", text)


def section_sha(text: str) -> Optional[str]:
    """sha of the maat-owned part (up to the end marker), version-normalised."""
    parts = rules_file.split_at_marker(text)
    return None if parts is None else sha_text(_normalise(parts[0]))


def _is_first_merge(rendered: str, current: str) -> bool:
    """True when rendered is the maat section plus current, kept verbatim."""
    tail = rules_file.HEADING + "\n\n" + current.rstrip("\n") + "\n"
    return bool(current.strip()) and rendered.endswith("\n\n" + tail)


def _carried_elsewhere(rendered: Dict[str, str], path: str, current: str) -> bool:
    """A lone CLAUDE.md whose text the rendered AGENTS.md carries verbatim."""
    return path == "CLAUDE.md" and _is_first_merge(rendered.get("AGENTS.md", ""), current)


def plan(rendered: Dict[str, str], repo_root: Path, manifest: Manifest) -> Piles:
    piles = Piles([], [], [], [])
    piles.retired = sorted(p for p in manifest.files if p not in rendered)
    for path in sorted(rendered):
        dest = Path(repo_root) / path
        if not dest.is_file():
            piles.new.append(path)
            continue
        current = dest.read_bytes().decode("utf-8", errors="replace")
        entry = manifest.files.get(path)
        if entry is None or sha_text(current) != entry["rendered_sha"]:
            # Untracked or edited since maat wrote it: only an exact match is safe.
            if current == rendered[path]:
                piles.unchanged.append(path)
            elif (entry is not None and entry.get("section_sha")
                  and section_sha(current) == entry["section_sha"]):
                # Edited only below the end marker, which the render keeps.
                piles.maat_changed.append(path)
            elif entry is None and (_is_first_merge(rendered[path], current)
                                    or _carried_elsewhere(rendered, path, current)):
                piles.new.append(path)
            else:
                piles.hand_changed.append(path)
        elif _normalise(current) == _normalise(rendered[path]):
            piles.unchanged.append(path)
        else:
            piles.maat_changed.append(path)
    return piles


def write(rendered: Dict[str, str], repo_root: Path, manifest: Manifest, *,
          include: List[str], template_shas: Optional[Dict[str, str]] = None,
          version: Optional[str] = None, retire: Sequence[str] = ()) -> List[str]:
    """Write the included paths; return the retired .maat/ files deleted as unedited."""
    if ("CLAUDE.md" in include and "AGENTS.md" not in include
            and lone_claude_md(Path(repo_root)) is not None):
        # The thin CLAUDE.md only makes sense once its rules are in AGENTS.md.
        raise ValueError("CLAUDE.md's rules are carried into AGENTS.md; write both")
    for path in include:
        if path not in rendered:
            raise KeyError("not a rendered path: %s" % path)
        dest = Path(repo_root) / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="") as f:
            f.write(rendered[path])
        if is_executable_path(path):
            os.chmod(dest, 0o755)
        manifest.files[path] = {
            "template_sha": (template_shas or {}).get(path, ""),
            "rendered_sha": sha_text(rendered[path]),
        }
        sec = section_sha(rendered[path]) if path in CARRIED_PATHS else None
        if sec is not None:
            manifest.files[path]["section_sha"] = sec
    removed = []
    for path in retire:
        entry = manifest.files.pop(path, None)
        if path.startswith(COPY_DIR + "/") and entry is not None:
            dest = Path(repo_root) / path
            if (dest.is_file()
                    and hashlib.sha256(dest.read_bytes()).hexdigest() == entry["rendered_sha"]):
                dest.unlink()
                removed.append(path)
                top = Path(repo_root) / COPY_DIR
                parent = dest.parent
                while parent != top and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
    if version is not None:
        manifest.maat_version = version
    manifest.save(Path(repo_root) / MANIFEST_PATH)
    return removed
