import os
import pytest
pytest.importorskip("pxr")
from weft import kept

# The set is keyed on an authored customData value ("set" = "hero"): the
# `where:` seed matches authored attrs/customData, not derived bindings
# (`where:material=X` does not resolve -- material is a rel / derived read), so
# the material binding is the *read* under test and can change without the
# expression itself moving.
EXPR = "where:set=hero"


def _scene(a_name="a", a_mat="glass", a_id=True, extra=False, drop_b=False):
    def mesh(name, mat, mid):
        idline = ('string "weft:id" = "%s"\n            ' % mid) if mid else ""
        return ('    def Mesh "%s" ( prepend apiSchemas = ["MaterialBindingAPI"]\n'
                '        customData = {\n            %sstring "set" = "hero"\n        } )\n'
                '    {\n        rel material:binding:full = </root/mtl/%s>\n    }\n' % (name, idline, mat))
    body = mesh(a_name, a_mat, "ID_A" if a_id else None)
    if not drop_b:
        body += mesh("b", "glass", "ID_B")
    if extra:
        body += mesh("c", "glass", "ID_C")
    return ('#usda 1.0\n( defaultPrim = "root" )\n'
            'def Xform "root"\n{\n'
            '    def Scope "mtl"\n    {\n        def Material "glass"\n        {\n        }\n'
            '        def Material "steel"\n        {\n        }\n    }\n'
            + body + '}\n')


def _write(tmp_path, text, name="s.usda"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def _stage(path):
    from pxr import Usd
    return Usd.Stage.Open(path, Usd.Stage.LoadAll)


def _keep(ctx, name="hero"):
    return kept.capture(_stage(ctx), ctx, EXPR, name)


def test_capture_then_noop_holds(tmp_path):
    ctx = _write(tmp_path, _scene())
    rec = _keep(ctx)
    assert {m["path"] for m in rec["members"]} == {"/root/a", "/root/b"}
    assert {m["read"]["material"] for m in rec["members"]} == {"/root/mtl/glass"}
    rep = kept.check(rec, _stage(ctx), ctx)
    assert rep["holds"]
    assert rep["counts"] == {"arrived": 0, "changed": 0, "gone": 0, "renamed": 0}
    assert set(rep) == {"holds", "arrived", "changed", "gone", "renamed", "counts"}


def test_rebind_is_changed(tmp_path):
    ctx = _write(tmp_path, _scene())
    rec = _keep(ctx)
    ctx2 = _write(tmp_path, _scene(a_mat="steel"), "s2.usda")
    rep = kept.check(rec, _stage(ctx2), ctx2)
    assert not rep["holds"]
    assert [c["path"] for c in rep["changed"]] == ["/root/a"]
    assert rep["changed"][0]["old"]["material"] == "/root/mtl/glass"
    assert rep["changed"][0]["new"]["material"] == "/root/mtl/steel"


def test_arrived_and_gone(tmp_path):
    ctx = _write(tmp_path, _scene())
    rec = _keep(ctx)
    ctx2 = _write(tmp_path, _scene(extra=True), "s2.usda")
    rep = kept.check(rec, _stage(ctx2), ctx2)
    assert [a["path"] for a in rep["arrived"]] == ["/root/c"] and not rep["holds"]
    ctx3 = _write(tmp_path, _scene(drop_b=True), "s3.usda")
    rep = kept.check(rec, _stage(ctx3), ctx3)
    assert [g["path"] for g in rep["gone"]] == ["/root/b"] and not rep["holds"]


def test_rename_with_id_holds(tmp_path):
    ctx = _write(tmp_path, _scene())
    rec = _keep(ctx)
    ctx2 = _write(tmp_path, _scene(a_name="a_renamed"), "s2.usda")   # keeps ID_A
    rep = kept.check(rec, _stage(ctx2), ctx2)
    assert rep["holds"]
    assert rep["renamed"] and rep["renamed"][0]["new_path"] == "/root/a_renamed"
    assert rep["renamed"][0]["old_path"] == "/root/a"


def test_kept_no_identity_rename_is_honest(tmp_path):
    ctx = _write(tmp_path, _scene(a_id=False))
    rec = _keep(ctx)
    ctx2 = _write(tmp_path, _scene(a_name="a_renamed", a_id=False), "s2.usda")
    rep = kept.check(rec, _stage(ctx2), ctx2)
    assert not rep["holds"] and not rep["renamed"]
    assert [g["path"] for g in rep["gone"]] == ["/root/a"]
    assert [a["path"] for a in rep["arrived"]] == ["/root/a_renamed"]


def test_bad_expression_does_not_raise(tmp_path):
    ctx = _write(tmp_path, _scene())
    rep = kept.check({"name": "x", "expression": "where:~~", "members": []}, _stage(ctx), ctx)
    assert rep["holds"] is False and rep.get("error")
