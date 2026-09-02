"""Two generators that exercise the whole thesis.

The chassis does not author where its hubs are. It computes them from
wheelbase and track, so changing a parameter MOVES THE MOUNT POINTS -- and the
wheelset, which never names the chassis, follows automatically or is told
loudly that the move broke the envelope. That is the scenario this project
opened with, made executable.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ..contracts import Offer, Requirement
from . import (Context, Generator, Param, Vec3, box, cylinder, mesh_prim,
               register)

# Fidelity is a declared variation point, not a hard-coded ladder. Same query,
# different context, different derivation -- and the collision context is a
# different SEMANTIC result, not merely a coarser one.
TESSELLATION = {"hero": 64, "review": 24, "proxy": 12, "collision": 8}


class Chassis(Generator):
    id = "chassis"
    version = "1.0.0"
    cost_class = "heavy"
    variation_points = ("tessellation", "internals")
    params = (
        Param("wheelbase", 2.84, 2.0, 3.6, "m"),
        Param("track", 1.56, 1.2, 2.0, "m"),
        Param("rideHeight", 0.31, 0.1, 0.6, "m"),
        Param("bodyHeight", 1.10, 0.8, 1.8, "m"),
    )

    # -- computed contract surface ----------------------------------------
    def hub_frames(self, p: Dict[str, float]) -> List[Tuple[str, Vec3]]:
        x, z, y = p["wheelbase"] / 2.0, p["track"] / 2.0, p["rideHeight"]
        return [
            ("hubFL", (x, y, z)), ("hubFR", (x, y, -z)),
            ("hubRL", (-x, y, z)), ("hubRR", (-x, y, -z)),
        ]

    def offers(self, p: Dict[str, float]) -> List[Offer]:
        out = [
            Offer(path="/chassis/mounts/%s" % name, contract="Mount@2",
                  archetype="mount", role="wheelHub", frame=frame,
                  envelope_linear=0.0005)
            for name, frame in self.hub_frames(p)
        ]
        out.append(Offer(
            path="/chassis/mounts/aeroRail", contract="Mount@2", archetype="mount",
            role="panelClip", frame=(0.0, p["rideHeight"] + p["bodyHeight"], 0.0),
            envelope_linear=0.002))
        return out

    # -- cheap, no geometry ------------------------------------------------
    def bounds(self, p: Dict[str, float]) -> Tuple[Vec3, Vec3]:
        hx = p["wheelbase"] / 2.0 + 0.45
        hz = p["track"] / 2.0 + 0.10
        return ((-hx, 0.0, -hz), (hx, p["rideHeight"] + p["bodyHeight"], hz))

    # -- the expensive call ------------------------------------------------
    def generate(self, p: Dict[str, float], ctx: Context,
                 bindings: Dict[str, List[Offer]]) -> str:
        lo, hi = self.bounds(p)
        body_len = p["wheelbase"] + 0.60
        body = box(center=(0.0, p["rideHeight"] + p["bodyHeight"] / 2.0, 0.0),
                   size=(body_len, p["bodyHeight"], p["track"] - 0.10))
        out = ['    def Xform "chassis"\n    {\n']
        out.append(mesh_prim("body", *body, indent="        "))

        # Internals are a declared variation point: a semantic difference, not
        # a coarser one. Only contexts claiming them get them at all.
        if ctx.get("internals"):
            cell = box(center=(0.0, p["rideHeight"] + 0.18, 0.0),
                       size=(p["wheelbase"] * 0.45, 0.22, p["track"] * 0.55))
            out.append(mesh_prim("batteryCell", *cell, indent="        "))

        out.append('        def Scope "mounts"\n        {\n')
        for name, frame in self.hub_frames(p):
            out.append(
                '            def Xform "%s" (\n'
                '                prepend apiSchemas = ["JitsdOfferAPI", "JitsdMountAPI", "JitsdEnvelopeAPI"]\n'
                '            )\n'
                '            {\n'
                '                uniform token  jitsd:offer:contract  = "Mount@2"\n'
                '                uniform token  jitsd:mount:role      = "wheelHub"\n'
                '                uniform double jitsd:envelope:linear = 0.0005\n'
                '                double3 xformOp:translate = (%.6g, %.6g, %.6g)\n'
                '            }\n' % (name, frame[0], frame[1], frame[2]))
        out.append('        }\n    }\n')
        return "".join(out)


class WheelSet(Generator):
    id = "wheelset"
    version = "1.0.0"
    variation_points = ("tessellation",)
    params = (
        Param("diameter", 0.66, 0.4, 0.9, "m"),
        Param("width", 0.245, 0.1, 0.4, "m"),
    )

    def requires(self, p: Dict[str, float]) -> List[Requirement]:
        # Names a contract and a role. Never a provider, never a path.
        return [Requirement(path="/wheelset", instance="hubs", contract="Mount@2",
                            role="wheelHub", cardinality="many",
                            failure_policy="required")]

    def bounds(self, p: Dict[str, float]) -> Tuple[Vec3, Vec3]:
        # Without bindings a wheelset does not know where it will be, so the
        # honest answer is its own extent about the origin. The assembler
        # unions this with the frames it resolves.
        r, w = p["diameter"] / 2.0, p["width"] / 2.0
        return ((-r, -r, -w), (r, r, w))

    def generate(self, p: Dict[str, float], ctx: Context,
                 bindings: Dict[str, List[Offer]]) -> str:
        segs = TESSELLATION.get(ctx.get("fidelity", "review"), 24)
        hubs = bindings.get("hubs", [])
        out = ['    def Xform "wheelset"\n    {\n']
        for i, hub in enumerate(hubs):
            # The wheel is placed at the frame the CHASSIS computed. Change the
            # wheelbase and this follows, with no edit here.
            pts, counts, idx = cylinder(
                center=hub.frame, radius=p["diameter"] / 2.0, width=p["width"],
                segments=segs, axis=2)
            out.append(mesh_prim("wheel_%d" % i, pts, counts, idx, indent="        "))
        out.append('    }\n')
        return "".join(out)


register(Chassis())
register(WheelSet())
