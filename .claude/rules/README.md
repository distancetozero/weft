<!-- maat 0.1.0 80fb5956871d -->
# Path-bound rules

A rule that only matters for some files lives here, one file per topic, so it
stays out of the always-on budget in AGENTS.md. Start each file with `paths:`
frontmatter listing the globs it applies to (for example `paths: ["src/io/**"]`
between `---` lines); the rule loads only when the agent works on a matching
file. AGENTS.md keeps at most a one-line pointer to it.

The deny list in `.claude/settings.json` is a speed bump, not a boundary: the
only boundary is the server-side ruleset.
