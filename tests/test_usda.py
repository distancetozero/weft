import pytest

from weft.usda import UsdaError, parse

DOC = '''#usda 1.0
(
    defaultPrim = "chassis"
    customLayerData = {
        string note = "hello"
    }
)

# a comment
def Xform "chassis" (
    prepend apiSchemas = ["WeftGeneratorAPI", "WeftRequireAPI:hubs"]
)
{
    uniform token weft:costClass = "heavy"
    uniform bool  flag = true
    uniform int   count = 3
    def Scope "mounts"
    {
        def Xform "hubFL" (
            prepend apiSchemas = ["WeftOfferAPI"]
        )
        {
            uniform token  weft:offer:contract = "Mount@2"
            uniform double weft:envelope:linear = 0.0005
            double3 xformOp:translate = (1.42, 0.31, -0.78)
            uniform token[] tags = ["a", "b"]
        }
    }
}
'''


def test_parses_structure_and_metadata():
    layer = parse(DOC)
    assert layer.meta["defaultPrim"] == "chassis"
    paths = sorted(p.path for p in layer.walk())
    assert paths == ["/chassis", "/chassis/mounts", "/chassis/mounts/hubFL"]


def test_typed_values():
    hub = parse(DOC).prims["chassis"].children["mounts"].children["hubFL"]
    assert hub.attrs["weft:offer:contract"] == "Mount@2"
    assert hub.attrs["weft:envelope:linear"] == pytest.approx(0.0005)
    assert hub.attrs["xformOp:translate"] == (1.42, 0.31, -0.78)
    assert hub.attrs["tags"] == ["a", "b"]


def test_scalar_types_round_trip():
    chassis = parse(DOC).prims["chassis"]
    assert chassis.attrs["flag"] is True
    assert chassis.attrs["count"] == 3


def test_multiple_apply_instances():
    chassis = parse(DOC).prims["chassis"]
    assert chassis.has_api("WeftGeneratorAPI")
    assert chassis.has_api("WeftRequireAPI")
    assert chassis.api_instances("WeftRequireAPI") == ["hubs"]
    assert not chassis.has_api("WeftOfferAPI")


def test_rejects_non_usda():
    with pytest.raises(UsdaError):
        parse("{ not usd }")


def test_dictionary_value_after_equals():
    """`customLayerData = { ... }` -- a dict as an rvalue, not just a block."""
    layer = parse('''#usda 1.0
(
    customLayerData = {
        string weft__label = "sq040"
        string weft__context = "review"
    }
)
''')
    cld = layer.meta["customLayerData"]
    assert isinstance(cld, dict)
    assert cld["weft__label"] == "sq040"
    assert cld["weft__context"] == "review"
