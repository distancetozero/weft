# Changelog

All notable changes to `weft-usd`. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are
[semantic](https://semver.org/).

## [Unreleased]

### Added
- (deferred to 0.1.2) Kept-set tinting in the graph (arrived green / gone
  ghosted); a coherent static `--export` (graph + card offline).

## [0.1.1] — 2026-10-11

### Added
- **`type:` selector** — slice by prim type (`type:Mesh`, `type:*Light`),
  closing the Loom's "organize by Type — no slice expression yet" caption.
- **`who:` / `incoming:` reverse selector** — the prims that point *at* a set
  (`who:name:glass`), reusing the `weft who` reverse index.
- **The usdview plugin ships in the wheel** (`weft/usdview_plugin/`), with
  `weft usdview-plugin-path` to print the directory for `PXR_PLUGINPATH_NAME` /
  `PYTHONPATH`.
- **Loom: "hide collections" graph toggle** — drops `usd:collection` edges
  (`lightLink`/`shadowLink`) so a big container's material/hierarchy graph
  renders past the cap instead of showing "too large".
- **Loom: auto-load on a `material:` query** — offers to load payloads (where
  bindings live) rather than quietly returning nothing.

### Changed
- PyPI project summary updated from "certify slices" to the workbench framing.
- Release automation: a GitHub Actions workflow publishes to PyPI via Trusted
  Publishing on a `v*` tag.

## [0.1.0] — 2026-10-11

First public release — on [PyPI](https://pypi.org/project/weft-usd/).

### Added
- **The Loom** (`weft loom <stage>`) — a read-only browser workbench that treats
  a USD stage as a pivot table: organize by any dimension (hierarchy, type,
  payload, purpose, bbox, bound material, any attribute), click a prim for its
  card (data + inheritance-aware material bindings), a live expression bar that
  teaches the slice language, and surgical certifiable slices. Graph pane ships
  in the wheel.
- **Kept sets** (`weft keep` / `check` / `forget`, and in the Loom) — keep a set
  you care about and weft reports, in plain terms, when it has *moved*:
  **arrived / changed / gone**, ignoring renames (it tracks identity, not bytes).
- **`weft data`** — the stage as a prim-level numeric table (cheap tier loads
  nothing; expensive columns load on demand).
- **`weft rels`** — the native relationship kinds on a stage, with counts.
- **`material:` selector** — slice by bound material (`material:glass`,
  `material:/path`, `material:gl*`), full or preview purpose, instance-proxy
  aware.
- **Surgical pull** — address by name, identity, attribute, place, path, or path
  glob; follow any relationship; declared boundaries; stat-based pull cache.
- **The engine** — content-addressed store, immutable revisions, channels,
  baselines, and a measured promotion gate.
- Apache-2.0; the core runs dependency-free, `[usd]` adds `usd-core`.

[Unreleased]: https://github.com/distancetozero/weft/commits/main
[0.1.1]: https://pypi.org/project/weft-usd/0.1.1/
[0.1.0]: https://pypi.org/project/weft-usd/0.1.0/
