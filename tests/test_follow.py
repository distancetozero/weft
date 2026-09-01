import pytest

from jitsd.follow import FollowTerm, format_term, parse_follow, parse_term


def test_bare_kind_defaults():
    t = parse_term("Mount")
    assert t == FollowTerm(kind="Mount")
    assert (t.direction, t.depth, t.contract, t.major) == ("down", None, False, None)


def test_direction_prefixes():
    assert parse_term("up:electrical:feeds").direction == "up"
    assert parse_term("up:electrical:feeds").kind == "electrical:feeds"
    assert parse_term("both:Mount").direction == "both"


def test_per_term_depth_and_major():
    t = parse_term("up:electrical:feeds*8")
    assert t.depth == 8
    t = parse_term("contract:Mount@2")
    assert t.contract and t.major == 2 and t.kind == "Mount"


def test_reserved_syntax_refused():
    for bad in ("Mount->shading", "Mount|binding", "(Mount)", "Mount*"):
        with pytest.raises(ValueError, match="reserved"):
            parse_term(bad)


def test_roundtrip():
    for s in ("Mount", "up:electrical:feeds*8", "both:Mount", "contract:Mount@2"):
        assert format_term(parse_term(s)) == s


def test_parse_follow_accepts_string_and_list():
    assert parse_follow("Mount,up:x:y") == [parse_term("Mount"), parse_term("up:x:y")]
    assert parse_follow(["Mount"]) == [parse_term("Mount")]
