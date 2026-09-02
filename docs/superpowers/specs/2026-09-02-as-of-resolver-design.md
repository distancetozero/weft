# The As-Of Resolver — Coordinates as Openable Worlds

Date: 2026-09-02
Status: design approved in conversation, section by section; implementation
deliberately unscheduled (queues behind the tier-1 release per the agreed
build-order discipline). The write path is explicitly out of scope and named
as the next design cycle (§8).

## 1. Principles

Two principles anchor this design, both argued to conclusion in
conversation:

1. **Time is an index, never an address.** Every address a user speaks or a
   document records is a *named coordinate* — a baseline, a channel
   snapshot, a revision pin. Wall-clock exists only as query sugar: a
   timestamp resolves through the event log to the pin set then in force
   and is immediately **reified into a name**. Nothing but names persists.
   (Precedent: git addresses by ref, not by reflog time; databases use
   AS-OF for forensics, releases for work. Names carry intent; timestamps
   carry none. Sanctification — cutting and naming a state — is what turns
   flux into referable identity, which is the project's own
   "volatility with consistency and recall.")
2. **jitsd declares and certifies worlds; it does not move files.** The
   open produces a *declaration* (what the world must be) and a *verifier*
   (proof it is). How bytes land on disk is the site's decision — their
   engineers, their infrastructure, their tools. This matches the tool's
   whole posture: the pull manifest doesn't render (usdrecord does), the
   extractor registry doesn't know team conventions (teams declare them).

## 2. The coordinate contract

A **coordinate** is a named, immutable pin set:

- `baseline:<name>` — already merkle-rooted and immutable.
- `rev:<asset>@<n>` pins layered over a base coordinate.
- **Channel snapshots**: `@approved` is a moving name, so opening at it
  snapshots the channel's current pin set and reifies it — the receipt
  records (and may cut) an ephemeral baseline (`open-<date>-<n>`), and that
  name is what the session and everything exported from it refers to. A
  promotion mid-session changes nothing visible; refresh is explicit
  ("reopen at @approved" → a *new* reified name), and drift between the two
  names reports exactly what moved.
- `--as-of <timestamp>` — sugar; resolves via the event log; answered and
  recorded as the reified name it landed on.

The **overlay** rides the slice-pin machinery: `mine:` entries (asset names
or globs), each resolving to a live local path (default: the asset's
recorded `source`; overridable), with author-and-reason recorded. Every
overlay hit is declared in the receipt.

**Untracked files pass through** to plain disk paths and are counted
(reusing the `_Untracked` discipline). Mixing pinned/live/passthrough is
normal; *undeclared* mixing is the failure mode.

Contract: `resolve(authored_path, context) → pinned content | overlay path
| passthrough path`, `context = reified coordinate + overlay set`, every
resolution class counted.

## 3. The open manifest and its executors

`jitsd open` emits an **open manifest**: the coordinate document plus a
file plan — for each relative path: the content hash it must have, its
class (pinned / overlay-live / passthrough), whether it is writable, and a
*suggested* source (store blob path, live file, disk path). The relative
topology mirrors the source tree, so authored relative references resolve
inside any faithful materialization. The manifest is the integration
surface, versioned like rule sets and extractor registries.

**Executors materialize it; jitsd ships one and mandates none:**

- **Reference executor** (`jitsd open --materialize`): plain copies,
  read-only for pinned files, correct on every filesystem ever made. The
  one-command path for users with no pipeline team. Mechanism notes
  (clone/reflink where the filesystem offers it, hardlinks same-volume,
  with their caveats — inode-coupled permissions, cross-device limits,
  SMB/exFAT absence) ship as an **advisory appendix** for site engineers,
  never as product behavior.
- **Site executors**: farm localization, Perforce sync, snapshots,
  container images — whatever already moves the site's bytes, driven by
  the manifest.
- **The future native Ar resolver (rung-1)** is just another executor of
  the same manifest — one that materializes nothing. Registered as a
  compiled USD plugin, context = the same coordinate document. Rung-1
  exists for interactive scale (per-stage contexts in one process, no
  disk churn); the materialized forms remain forever the compatibility
  and hermeticity tier (any USD consumer, shippable frozen render
  inputs).

**Verification is the product**: `jitsd verify <dir>` checks any
materialization against its manifest — content hashes, read-only pinned
files, declared overlays — regardless of how it was built. The manifest +
verifier is thereby a **conformance suite for executors**: if verify
passes, the executor is correct. This is what prevents mechanism freedom
from becoming fragmentation.

**Safety rule**: store blobs are read-only at ingest (0444) as store
policy, independent of any executor; the reference executor also sets
read-only on materialized pinned files. Writing pinned content fails at
the OS with a permission error — the correct UX: "this is sanctified;
overlay it or publish a new revision."

**Layer-cache soundness**: distinct coordinates materialize to distinct
directories (named by the reified coordinate), so layer identifiers differ
by construction and the measured `SdfLayer`-registry-not-keyed-by-context
landmine cannot fire. Reopening the same coordinate is idempotent (same
name, same content).

Generator-backed revisions in the closure are generated before the plan is
emitted, cost class declared up front.

## 4. The slice as an executable session

`jitsd open` takes a bare coordinate (whole world) or a **slice** — and a
slice open executes everything the document records, as one act:

1. Coordinate: the slice's baseline, else a reified channel snapshot;
   session name = `<slice-label>@<reified-coordinate>`.
2. Scope: the plan covers only the slice's layer closure — members, their
   untracked references, nothing else. Omits are declared absences.
3. Overlay: the slice's `mine:` entries.
4. Mask: prim selections emit the mask file and the consumer command —
   ask → closure → coordinate → overlay → mask → receipt in one gesture.
5. **The authority rule runs at open**: at the slice's own coordinate,
   recorded selection paths must equal ask replay (violation fails the
   open loudly); at any other coordinate the asks re-resolve and the
   receipt reports selection drift.

**Lifecycle**: refresh is never in-place — reopening at a moved channel
produces a new named session beside the old; `jitsd drift` between two
session names reports member, selection, and resolution differences.
Something that left the world between coordinates is *removed, declared* —
the dead-prim answer at session granularity. Sessions are cheap,
disposable, self-describing via receipts.

What a slice becomes: a shareable, versioned **way of working** — promote
`lighting.slice` and everyone who opens it gets the same pinned world,
their own declared live files, and the same threads pulled.

## 5. Probes (verified-facts discipline; run before implementation relies)

1. Reference-executor copy semantics on each target OS; advisory-appendix
   mechanisms probed where claimed (clone/reflink availability; hardlink
   realPath identity — expected safe by construction; symlink realPath
   piercing — expected, documenting the symlink ban).
2. Read-only enforcement: `Sdf.Layer.Save` through a read-only file fails
   cleanly; store blobs 0444 at ingest.
3. Two coordinates' materializations open side-by-side share no
   incorrectly-cached layers.
4. Binary/usdz files compose unchanged from a materialized plan.
5. Event-log timestamp → pin-set resolution correctness at boundaries
   (exactly at a promotion event).

## 6. Testing

Fixtures: a mini repo, two baselines differing in one revision — open
both, composed value differs; reopen idempotent; overlay wins and live
edits appear; writing pinned fails with permission error; passthrough
counted; the reify rule (open channel → ephemeral name; promote; reopen →
new name; drift names the promotion); slice-session open writes the mask
and fails loudly on an authority-rule violation; receipt
recompute-and-compare; **executor conformance**: a deliberately wrong
materialization (one file's content swapped, one pinned file writable)
fails verify with named findings.

ALab acceptance: open the workbench slice at pre- and post-promotion
coordinates from the POC flow; `usdrecord` both materializations; images
differ by exactly the raised shelf. Lifecycle: `jitsd open lighting.slice`,
promote upstream, reopen, `jitsd drift` names the change.

## 7. Rung-invariance (designed once)

The coordinate document, reify rule, overlay declaration, open-manifest
format, and receipt schema are identical across executors. Rung-1 adds an
executor; it changes no artifact and no command's meaning.

## 8. Out of scope, named

- **Authorship / the write path** — publishing from inside a session,
  write-through semantics, conflict handling, what sanctification looks
  like from within an open world. Explicitly the NEXT design cycle, per
  the owner: the open-manifest contract should be pushed "into the weeds"
  together with authorship, where its remaining questions (writable-file
  lifecycle, promotion from a session, overlay→revision flow) live.
- The native Ar plugin (rung-1) — designed for, not built.
- Frame-axis (content-time) tolerances — separate future cycle in the
  contracts layer.
- Any timestamp UI beyond reify-on-query sugar.

## 9. Relationship to existing machinery

- Consumes: ledger pins/baselines/event log; slices (coordinate ± overlay,
  selections, authority rule); pull manifests (mask + layer sets); store
  blobs (content-addressed, read-only); deps closure walks.
- Supersedes: `jitsd checkout` remains for single files; the open manifest
  is the multi-file generalization with verification.
- The measured `SdfLayer` registry finding (not keyed by resolver context)
  is defused by construction via distinct materialization paths (§3).
