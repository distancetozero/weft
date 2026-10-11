# Changelog

All notable changes to `weft-usd`. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are
[semantic](https://semver.org/).

## [Unreleased] — 0.1.1 (in progress)

### Added
- (planned) `type:` selector and a reverse-follow (incoming) selector — the two
  gaps the Loom currently captions as "no slice expression yet".
- (planned) The usdview plugin ships in the wheel, with a helper that prints the
  plugin path for `PXR_PLUGINPATH_NAME` / `PYTHONPATH`.
- (planned) Loom: auto-load on a `material:` query; a "hide collections" graph
  toggle; kept-set tinting in the graph (arrived green / gone ghosted); a
  coherent static `--export` (graph + card offline).

### Changed
- PyPI project summary updated from "certify slices" to the workbench framing.

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
[0.1.0]: https://pypi.org/project/weft-usd/0.1.0/
