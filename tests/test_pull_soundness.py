import pytest

pxr = pytest.importorskip("pxr")

from jitsd.pull import pull
from jitsd.registry import MEANING_CHANGING, omission_class


def test_omission_classes():
    assert omission_class("physics:body1") == MEANING_CHANGING
    assert omission_class("material:binding") == "inert"
    assert omission_class("skel:skeleton") == MEANING_CHANGING


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_foreign_instance_target_widens_to_instance_root(tmp_path):
    _write(tmp_path, "proto.usda", """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "geo"
    {
        def Cube "glass"
        {
        }
    }
}
""")
    ctx = _write(tmp_path, "world.usda", """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Xform "a" (
        instanceable = true
        references = @./proto.usda@
    )
    {
    }
    def Xform "b"
    {
        rel custom:uses = </World/a/geo/glass>
    }
}
""")
    p = pull(ctx, ["name:b"], follow=["custom:uses"])
    m = {m.path: m for m in p.members}
    assert "/World/a" in m
    assert "instance" in m["/World/a"].note


def test_joint_whole_or_declared(tmp_path):
    ctx = _write(tmp_path, "sim.usda", """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "gripper"
    {
        def PhysicsRevoluteJoint "hinge"
        {
            rel physics:body0 = </root/gripper>
            rel physics:body1 = </root/wrist>
        }
    }
    def Xform "wrist"
    {
    }
}
""")
    p = pull(ctx, ["name:gripper"], follow=[])
    paths = [m.path for m in p.members]
    # wrist not followed -> the joint may not ride along silently:
    assert "/root/gripper/hinge" not in paths or "/root/wrist" in paths
    declared = [b for b in p.boundary if b.omission == MEANING_CHANGING]
    assert declared, "joint exclusion must be declared meaning-changing"
    assert p.fitness["statement"] == "contact-incomplete by construction"
    assert p.fitness["contact_unevaluated"] >= 1
