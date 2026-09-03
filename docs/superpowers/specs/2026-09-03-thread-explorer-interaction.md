# Weft Threads panel — exploration interaction model

**Status:** approved by owner 2026-09-03, for build into the embedded
QWebEngineView panel (`extras/usdview/weftViewer/viewer_template.html` +
`_stagebridge.py`). Native `QGraphicsView` panel is unchanged (fallback).

## Principle

A **moving focus**, not an accumulating tree. At any moment the view holds:
the current focus, its immediate relationships (as cheap bounding boxes), and
anything pinned — never the whole stage. You walk a focus through the
relationship graph; loading follows focus; the graph re-centers so there is
always a "you are here." This is weft's founding claim made literal: explore a
stage without holding the whole thing in your head, and loading is driven by
relationships/rules, not blind subtree expansion.

## Gestures

- **Single-click = PEEK.** Select the prim in usdview, highlight *its* bbox and
  frame the camera to it, show its threads in the inspector. **No load. No
  re-center.** Peeking is a quick look around your current spot; clicking
  neighbours must not yank the graph or load anything.
- **Double-click = PULL.** Behaviour depends on node kind:
  - **Leaf** (a payload-bearing asset / no children under the active lens):
    materialize **only that leaf** (`stage.Load` on the leaf), and **re-center**
    the graph on it. The previously-pulled focus **unloads** unless pinned.
  - **Group** (has children under the active lens): **only re-center** on it —
    reveal its children as bounding boxes. **Load nothing.** Groups are
    navigational; you drill through them to leaves. This is what makes bulk
    "load the world" impossible.

## Buttons (in the focused node's inspector)

- **Pin.** Toggle. A pinned node stays loaded (if a leaf) and stays drawn in the
  graph across re-centers, so you can deliberately assemble a set (pin the
  workbench, go inspect a tool, both stay).
- **Expand one level.** Reveal the focus's immediate children as bounding boxes,
  in place (no load, no re-center).
- **Expand from here.** Reveal the whole subtree under the focus as bounding
  boxes (no load). The power move for "show me everything under this" without
  materializing any geometry.

Expands are buttons, not triple/quadruple-click: click-count detection forces
single/double to wait for a timeout, which would make peek/pull feel laggy.

## Orientation

- **Breadcrumb trail** of the focuses pulled through; **Back** re-centers to the
  previous focus (and unloads the current per the same rules).
- The active **lens** decides what "immediate relationships" means: hierarchy →
  children; Mount → what is carried (`weft:offer:carrier`); shading/finish →
  siblings sharing that material/finish. "Load based on the rules" = a pull
  follows the active lens's edges.

## Loading invariants

- Only **leaves** ever load, only on **double-click pull** (or a pinned leaf).
- Groups never load their geometry; they re-center / expand as bboxes only.
- Moving focus unloads the previous non-pinned focus. Loaded set at any time =
  {current leaf focus if leaf} ∪ {pinned leaves}. Bounded by construction.
- `stage.Load` uses default (with descendants) so a pulled leaf's own geometry
  (which may sit behind nested payloads) actually appears; but since only leaves
  are ever pulled, this never cascades into a whole group/scene.

## Out of scope this pass

Weft-ask bar behaviour under re-center (keep existing for now); multi-select;
persistence of pins across sessions.
