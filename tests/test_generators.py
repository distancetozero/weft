import pytest

from jitsd.generators import Context, get, known
from jitsd.generators import vehicle  # noqa: F401  registers the built-ins


def test_registry():
    assert "chassis@1.0.0" in known() and "wheelset@1.0.0" in known()


def test_parameter_domain_is_enforced():
    """A domain describes a space; values outside it are not representable."""
    c = get("chassis")
    assert c.bind_params({})["wheelbase"] == pytest.approx(2.84)
    with pytest.raises(ValueError, match="above maximum"):
        c.bind_params({"wheelbase": 9.0})
    with pytest.raises(ValueError, match="below minimum"):
        c.bind_params({"wheelbase": 0.1})
    with pytest.raises(ValueError, match="no parameter"):
        c.bind_params({"nonesuch": 1})


def test_offers_are_computed_from_parameters():
    """The chassis does not author hub positions -- it derives them."""
    c = get("chassis")
    narrow = {o.path: o.frame for o in c.offers(c.bind_params({"wheelbase": 2.5}))}
    wide = {o.path: o.frame for o in c.offers(c.bind_params({"wheelbase": 3.5}))}
    assert narrow.keys() == wide.keys()
    assert narrow["/chassis/mounts/hubFL"][0] == pytest.approx(1.25)
    assert wide["/chassis/mounts/hubFL"][0] == pytest.approx(1.75)


def test_bounds_need_no_geometry():
    """bounds() answers 'where will you be' without answering 'what will you
    look like' -- the obligation that makes spatial queries possible."""
    c = get("chassis")
    p = c.bind_params({"wheelbase": 3.0, "track": 1.8})
    lo, hi = c.bounds(p)
    assert hi[0] - lo[0] >= 3.0     # conservative: covers the wheelbase
    assert hi[2] - lo[2] >= 1.8     # ...and the track
    assert lo[1] == 0.0


def test_bounds_are_conservative_against_generated_geometry():
    import re
    c = get("chassis")
    p = c.bind_params({"wheelbase": 3.1})
    lo, hi = c.bounds(p)
    text = c.generate(p, Context("hero", {"fidelity": "hero"}), {})
    pts = [tuple(map(float, m.groups())) for m in
           re.finditer(r"\(([-\d.e+]+), ([-\d.e+]+), ([-\d.e+]+)\)", text)]
    assert pts
    for pt in pts:
        for i in range(3):
            assert lo[i] - 1e-9 <= pt[i] <= hi[i] + 1e-9


def test_tessellation_follows_the_context_claim():
    w = get("wheelset")
    p = w.bind_params({})
    offer = get("chassis").offers(get("chassis").bind_params({}))[0]
    counts = {}
    for name in ("hero", "review", "proxy", "collision"):
        text = w.generate(p, Context(name, {"fidelity": name}), {"hubs": [offer]})
        counts[name] = text.count("(")
    assert counts["hero"] > counts["review"] > counts["proxy"] > counts["collision"]


def test_generation_is_deterministic():
    c = get("chassis")
    p = c.bind_params({"wheelbase": 2.9})
    ctx = Context("review", {"fidelity": "review"})
    assert c.generate(p, ctx, {}) == c.generate(p, ctx, {})
