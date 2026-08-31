# What USD already holds

The goal is a scene compiled on demand — versioned by intent, composed by
contract, compiled per context. Everything that does not serve that, and
everything USD already does, is effort spent in the wrong place.

Running the audit exposed a habit: reaching for ideas from Nix, git and
OpenVDB and importing them as new, when USD already had them under different
names. Sparse layers *are* tile collapse. `(path, field)` *is* per-attribute
decomposition. The list below is the corrective.

## Reused, not rebuilt

| Need | What USD already provides |
|---|---|
| Evaluation | LIVRPS composition — kept whole |
| Lazy loading | payloads, population masks, crate mmap |
| Sparse overrides | a layer contains only opinions; absence is already free |
| Per-attribute decomposition | `SdfLayer` is `(path, field) → value` (`SdfAbstractData`) |
| Intra-file value dedup | crate's token/string/path/value tables |
| Array compression | crate's LZ4 and integer encoding |
| Typed connectable interfaces | `UsdShade` — `ConnectableAPI`, `NodeGraph`, `Input`, `Output` |
| Articulation | `UsdPhysics` joints, limits, drives, articulation roots |
| Deformation rigs | `UsdSkel` |
| Volumetric fields | `UsdVol` — `Volume`, `OpenVDBAsset`, `FieldAsset` |
| Surface fields | `UsdGeomPrimvarsAPI` — typed, interpolated, per-element |
| Scatter consumption | `UsdGeomPointInstancer` |
| Bounds without loading payloads | `UsdGeomModelAPI.extentsHint`, `Boundable.extent` |
| Coarse per-consumer shaping | `purpose` (proxy / render / guide) |
| Subject time | `timeCode` |

## Genuinely absent

| Need | Status |
|---|---|
| Version identity — "as of" | **absent.** The largest gap; the reason this project exists |
| Cross-file content identity | **absent.** No hashes anywhere; layer identity is a path string |
| Canonical serialisation | **absent**, and inherited as a risk — see open question 9 |
| Offered (unbound) interfaces | **absent.** `UsdShade` connects *within* a graph; nothing declares "I offer this for something not yet chosen" |
| Tolerance envelopes on an interface | **absent** |
| Bounds as a function of parameters | **absent.** `extentsHint` is authored data, not a cheap evaluation |
| Compatibility checking | **absent** |
| Provenance beyond the layer stack | **absent** |
| Declared failure policy, cost class | **absent** |
| Effectivity | **absent** |
| Redaction | **absent** |

## Consequences for the archetypes

The four archetypes in `04-contracts.md` were written as if from nothing. Three
of them shrink.

**Kinematic chain — delete as an archetype.** `UsdPhysics` already covers
bodies, revolute / prismatic / spherical / fixed / distance joints, limits,
drives and articulation roots, across robotics, mechanisms and operable parts;
`UsdSkel` covers the deformation side. Re-specifying any of it would be pure
duplication. What remains is one thin applied schema saying *which joints of an
existing articulation are the public interface* and what their tolerance
envelopes are.

**Field / Domain — mostly already exists.** A `primvar` with a declared
interpolation is exactly a sampleable quantity over a surface; `UsdVol` covers
volumes. The contract adds only semantic naming (this primvar is
`scatterDensity`, in these units) and the declaration that it is *offered* to
consumers. Not a data model — a naming and visibility layer.

**Mount / Socket — keep, narrowed.** USD has no unbound attachment point.
`PhysicsFixedJoint` expresses a *realised* connection between two known bodies;
the contract needs an *offered* one, before a consumer is chosen. Build the
frame on `UsdGeomXformable` and, where physics matters, resolve a bound mount
into a `PhysicsFixedJoint` rather than a parallel representation.

**Envelope / Clearance — keep, narrowed.** `extent` and collision shapes
describe where a thing *is*; nothing in USD declares where things *may not be*.
The constraint is new; the geometry carrying it should reuse `extent` and
`UsdPhysics` collision shapes rather than a new volume type.

## The larger correction: follow `UsdShade`

`UsdShade`'s connectable model — typed `Input`s and `Output`s, `ConnectableAPI`,
a `NodeGraph` publishing an interface, connections binding them — is the
closest thing in USD to what contracts need, and it is proven, tooled and
familiar to every technical artist.

Contracts should generalise that pattern beyond shading rather than invent a
parallel one. What JIT-SD adds on top is the part `UsdShade` genuinely lacks:
an interface **offered** to a consumer not yet chosen, resolved by type rather
than by an authored connection, and carrying a tolerance envelope.

That is a much smaller thing to build, and it inherits twenty years of
ergonomics instead of competing with them.
