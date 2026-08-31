# Versioning, collaboration and handoff

## The founding correction

An earlier draft of this design made the evaluation coordinate a wall-clock
timestamp. That was wrong.

> **Versions are acts of intent, not moments in time.**

Wall-clock records *when* but carries no meaning. Systems that version by clock
(autosave, document revision history) are excellent for recovery and useless
for collaboration, because there is no way to say "use the good one." Every
system people actually hand work off through versions by **deliberate act**: a
git tag, a release, a PLM state change, an issued drawing set.

Time survives only as an index for looking those up afterwards.

## Three layers — and exactly one is mutable

**Revisions** — immutable, content-addressed, never typed by a human. Every
save produces one. Never mutated, never reused. Cheap: content addressing
dedupes.

**Channels** — mutable names owned by a team. `chassis@wip`,
`chassis@review`, `chassis@approved`. A pointer to a revision. Moving it is a
deliberate, attributed, audited act. Consumers subscribe to a *channel*.

**Baselines** — immutable, named, complete resolution maps. The whole world
pinned, frozen at creation. A lockfile. Created by a decision, never by a clock.

> **There is exactly one mutable object in the system: the channel pointer.**
> All volatility is confined to a single small surface that is human-controlled,
> attributed and auditable.

Rollback is therefore a pointer move. No data migration, no un-publishing.

## Channels are not a new idea

| | The ladder they already use |
|---|---|
| Film/TV | work → publish → approved |
| Games | dev → main → cert → live |
| Manufacturing (PLM) | In Work → Under Review → Released → Superseded |
| AEC | ISO 19650 standardises it: Work in Progress → Shared → Published → Archived |
| Software | dev → staging → stable; npm `next` → `latest` |

Every one of these converged on a promotion ladder of named states, and every
one implements it as a status field beside files that resolution ignores.
JIT-SD's contribution is making the pointer *be* the resolution mechanism.

## Float on compatibility, pin on breakage

Two failure modes to design against:

- **Everyone floats on latest** → nothing is stable, renders flicker, nobody
  trusts anything.
- **Everyone pins hard** → everything is stale, upgrades are terrifying,
  integration debt compounds until someone loses a month.

The way out: **couple to the contract, not the revision.** A generator declares
which contract version it satisfies. A consumer declares what it needs and
floats freely across any revision still satisfying it. Compatible changes flow
automatically; breaking changes stop at the boundary and need an explicit act.

## Compatibility is measured, not asserted

In npm and Cargo, semver is a human promise, and maintainers are frequently
wrong. Here it can be **checked**, because every consumer ships exemplars
(canonical parameter bindings — see `04-contracts.md`).

Publishing a revision triggers re-evaluation of every affected consumer's
exemplars. Manifests either match structurally or they do not. A "compatible"
change that breaks a downstream exemplar is reclassified as breaking and the
promotion is refused.

This is one of the two or three most valuable properties in the design.

## Floating always leaves a receipt

**You never ask for a baseline; you receive one.** Resolving against floating
channels mints a baseline as a side effect and returns it — same as
`npm install` writing a lockfile unasked. Reproducibility is a byproduct of
working normally, not a discipline anyone must remember.

Baselines are cut two ways, and both are needed:

- **Automatically**, by CI, whenever an `@approved` channel moves and the
  exemplar suite passes. Without this, cutting becomes a bottleneck, a
  supervisor becomes the gate, and everyone quietly reverts to floating.
- **Deliberately**, named, by a person: `seq040/client_review`.

## The handoff unit

**A baseline reference + a sparse overlay + a context.** Kilobytes. Pasteable
into a chat. Because everything it names is immutable, it means the identical
thing on any machine, forever.

The overlay is what makes it powerful: `sh0120 @ baseline118 + hero_car@wip` is
a one-line, shareable, reproducible, disposable experiment. Compare with
duplicating a shot setup and hand-repointing references. This mirrors `npm
overrides`, Cargo `[patch]`, Nix overlays, `--override_repository` — all of
which exist because "the known-good world, except one thing" is the most common
experiment anyone runs.

**Saving and publishing separate cleanly again.** Today publish is expensive —
copies files, mutates a database, kicks off jobs — so people batch it and work
goes dark in between. Here every save is already an immutable revision;
publishing is only a pointer move. A colleague can watch your in-progress work
without you doing anything, and without affecting anyone on `@approved`.

## Naming — what people actually say

Nobody says a hash out loud. Hashes fail at both jobs a spoken version name
does: **ordering** ("v37" is obviously after v36; `8f2c` vs `3a91` says
nothing) and **pronounceability**.

Register, in rough order of frequency in speech:

| How people refer to it | Example |
|---|---|
| a channel / state | "the approved car", "the latest" |
| a named event | "the car from the client review" |
| relative to something | "the one before Dave's change" |
| a monotonic number | `v037`, `Rev C`, "CL 887431", "build 41209" |
| a hash | essentially never spoken |

Note the only spoken number form is always **monotonic** and assigned by a
single authority. Film publish versions, PLM revision letters, Perforce
changelists, CI build numbers.

> **People name inputs and decisions. Machines identify outputs.**

`hero_car v37` names what a person made and promoted — an act, with an owner
and an intent. The compiled result a lighter receives is an *output*:
context-specific, possibly never produced in that exact form again. It needs a
coordinate saying which inputs produced it, not a name of its own:

```
hero_car  v37 · baseline 118 · lighting
```

Speakable, ordered, diagnostic. Two people seeing different pictures locate the
disagreement in seconds. The hash sits underneath, in the receipt and the
metadata, never in anyone's mouth.

### Three naming modes are required, not one

- **By channel or baseline** — things a team maintains and promotes.
- **By revision number** — things a single author published in sequence.
- **By distinguishing parameters** — one-off compilations that will never
  recur ("my car, Sport trim, Nardo grey"; "the wet version of the hero").
  At the consumer end of a JIT system this is the *normal* case, not an edge
  case.

If only the first two exist, everyone ends up saying "the one I'm looking at,"
and communication is worse than filenames — the failure mode this paradigm is
most exposed to.

### Consequences

- **Monotonic numbers cost a sequencer.** The one genuinely centralised
  component. Scope keeps it cheap: it orders only *published* things
  (per-asset revisions, per-project baselines). WIP stays hash-only.
- **Relative references are first-class query syntax**, because that is the
  register people speak in. `hero_car@approved`, `seq040~1`,
  `baseline 118 - aero`. A system accepting only absolute identifiers is
  fighting how humans talk, and will lose.
- **Labels beat numbers when a decision is involved.** People say "pull up the
  client review," not "pull up baseline 118."
- **Hashes belong in written contexts that outlive the conversation**: render
  burn-ins, export manifests, bug reports, sign-off records. A frame found on a
  drive in two years has no conversation around it.

## Live WIP

Live sync is a **transport attached to a channel**, never a requirement. Git is
fully functional alone and offline; the network is pure opt-in. Same here.

### One live sublayer per participant

Each participant authors into their own sublayer of the WIP layer stack, and
everyone subscribes to everyone else's deltas.

**Conflict resolution comes free from LIVRPS.** No CRDT, no OT, no merge
algorithm. If two people author the same attribute, layer strength decides —
deterministically, by an order declared up front and visible to everyone.

Better than last-writer-wins, which is *invisible*: your edit silently vanishes
and you cannot tell why. Under layer strength the UI can say exactly what
happened. It also matches how these teams already work — film has had
layer-per-department for years; this is that, at session granularity.

### Sessions are not revisions

```
live session (volatile, ms latency)
      ↓ checkpoint — automatic every N seconds, or explicit
   revision (immutable, hashed)
      ↓ promote
   channel move
```

A live session is the one mutable, unversioned thing in the system, and always
disposable. Auto-checkpointing bounds the volatility: a crash loses seconds,
which is what any DCC's autosave already gives. Cheap, because unchanged blobs
cost nothing to re-checkpoint.

Use **checkpoint**, not "commit" — it is the word Nucleus and manufacturing
both already use, without git's merge connotations.

### Two classes of live traffic

- **Layer deltas** — transforms, parameters, structure, relationships. Bytes,
  sub-frame. Covers layout, look tweaks, assembly positioning: the majority of
  real-time collaboration.
- **Blob updates** — new geometry, new textures. Sent as "here is a new hash",
  data transferring out of band.

**The live protocol never blocks on a big transfer.** Notification is
immediate; until data arrives the previous version stays on screen with an
indicator. A layout artist's changes appear instantly, a sculptor's with lag
proportional to mesh size. That is physics; being honest about it in the
protocol beats stalling everyone's viewport.

Presence rides the delta channel, is ephemeral, never persisted.

### Three invariants

1. **Live is viewable, never citable.** A downstream consumer may *watch* a
   live session — genuinely valuable and impossible today. But nothing with a
   receipt may be built from it. **Only revisions can be resolved against.**
   This keeps the dependency graph acyclic and every baseline reproducible.
2. **Losing the live server degrades to solo, never to a blocked session.**
   Work continues locally against the last checkpoint; resync on return. If a
   server outage can stop someone working, the thing being escaped has been
   rebuilt.
3. **Ownership is advisory, not enforced.** No locks by default — LIVRPS
   resolves it. Surface a hint ("Dana is also editing this prim"). Hard locking
   is a team policy, not a system property; locking-by-default is how you get
   people emailing each other to release files.

### Pluggable transport

```
channels/wip:
  points_to: v041
  sync: none | relay | nucleus
```

`none` is the default. A WebSocket delta relay is the reference
implementation. Nucleus live layers drop in for shops already on Omniverse —
turning that comparison into an integration.

### Known hazard

Live sessions create a two-speed mental model — "what I see now" vs "what is
checkpointed" — and people **will** confuse them. "I approved what I was
looking at, but what got recorded was the last checkpoint" is real and
expensive. Therefore: **never allow an approval, export or promotion directly
from a live view.** Force an explicit checkpoint first, so the thing being
signed off always has a name.
