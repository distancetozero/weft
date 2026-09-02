import pytest

pxr = pytest.importorskip("pxr")

from weft.pull import pull
from weft.registry import Extractor, emit_extractors_document, parse_extractors


def test_document_roundtrip():
    items = [Extractor("game:spawnRef", "game:spawns", "primPath")]
    doc = emit_extractors_document(items, "game.extractors")
    assert parse_extractors(doc) == items


def test_extractor_makes_string_attr_a_followable_edge(tmp_path):
    f = tmp_path / "g.usda"
    f.write_text("""#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "enemy"
    {
        string game:spawnRef = "/root/tables/spawn01"
    }
    def Xform "tables"
    {
        def Xform "spawn01"
        {
        }
    }
}
""")
    ex = [Extractor("game:spawnRef", "game:spawns", "primPath")]
    p = pull(str(f), ["name:enemy"], follow=["game:spawns"], extractors=ex)
    assert "/root/tables/spawn01" in [m.path for m in p.members]
    # without the extractor the edge is invisible AND the scope is declared
    q = pull(str(f), ["name:enemy"], follow=["game:spawns"])
    assert "/root/tables/spawn01" not in [m.path for m in q.members]
    assert any("registered extractors" in d for d in q.declarations)
