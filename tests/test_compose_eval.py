# Unit tests for compose-mode's expression evaluator
# (spec: docs/superpowers/specs/2026-09-03-compose-mode-v1.md).
#
# The evaluator lives in extras/usdview/weftViewer/viewer_template.html
# between the `--- compose:pure begin ---` / `--- compose:pure end ---`
# markers as PURE JS (no DOM, no bridge). This test extracts that exact
# shipped block and runs it under node against a small fixture graph --
# each predicate kind, each operator, the fold order, path scope (below
# vs /*), empty results, and glob edge cases. Skipped when node is not
# on PATH.
import os
import shutil
import subprocess

import pytest

_TPL = os.path.join(os.path.dirname(__file__), "..",
                    "extras", "usdview", "weftViewer", "viewer_template.html")

_FIXTURE_AND_ASSERTS = r"""
const G={nodes:[
 {id:"/root",label:"root",type:"group"},
 {id:"/root/shelf",label:"shelf",type:"group"},
 {id:"/root/shelf/cup1",label:"decor_cup1",type:"prop"},
 {id:"/root/shelf/cup2",label:"decor_cup2",type:"prop"},
 {id:"/root/shelf/cup2/inner",label:"inner_bit",type:"prop"},
 {id:"/root/shelfmate",label:"decor_shelfmate",type:"prop"},
 {id:"/root/bench",label:"tool_bench",type:"furniture"},
 {id:"finish:translucent",label:"translucent",type:"finish"},
 {id:"shading:full",label:"full",type:"shading"},
 {id:"finish:empty",label:"empty",type:"finish"},
],edges:[
 {source:"/root",target:"/root/shelf",kind:"usd:arc"},
 {source:"/root/shelf",target:"/root/shelf/cup1",kind:"usd:arc"},
 {source:"/root/shelf/cup1",target:"finish:translucent",kind:"weft:bind:finish"},
 {source:"finish:translucent",target:"/root/bench",kind:"weft:bind:finish"},
 {source:"/root/shelf/cup2",target:"shading:full",kind:"weft:bind:shading"},
 {source:"/root/bench",target:"/root/shelf/cup1",kind:"Mount"},
 {source:"/root/shelf",target:"finish:translucent",kind:"usd:arc"},
]};

let failures=0;
function eq(name, got, want){
  const g=[...got].sort().join(","), w=[...want].sort().join(",");
  if(g!==w){ failures++; console.error("FAIL "+name+"\n  got:  ["+g+"]\n  want: ["+w+"]"); }
  else console.log("ok "+name);
}
function run(text){ const r=parseExpr(text);
  if(r.errors.length) { failures++; console.error("FAIL parse "+text+": "+r.errors.join(";")); return new Set(); }
  return evalExpr(r.terms, G); }

// --- predicates ---
eq("facet finish (both edge directions, non-loadables excluded)",
   run("finish=translucent"), ["/root/shelf/cup1","/root/bench"]);
eq("facet via facet: prefix", run("facet:finish=translucent"),
   ["/root/shelf/cup1","/root/bench"]);
eq("facet via legacy where:", run("where:shading=full"), ["/root/shelf/cup2"]);
eq("facet with no members", run("finish=empty"), []);
eq("facet that does not exist", run("finish=nosuch"), []);
eq("path below (self excluded when group, nested included, prefix respects /)",
   run("path:/root/shelf"),
   ["/root/shelf/cup1","/root/shelf/cup2","/root/shelf/cup2/inner"]);
eq("path below on a leaf includes the leaf itself",
   run("path:/root/bench"), ["/root/bench"]);
eq("path children only (direct, not nested)",
   run("path:/root/shelf/*"), ["/root/shelf/cup1","/root/shelf/cup2"]);
eq("path prefix boundary (/root/shelf does not swallow /root/shelfmate)",
   run("path:/root/shelf"),
   ["/root/shelf/cup1","/root/shelf/cup2","/root/shelf/cup2/inner"]);
eq("bare /path parses as a path predicate",
   run("/root/shelf/*"), ["/root/shelf/cup1","/root/shelf/cup2"]);
eq("name glob *", run("name:decor_*"),
   ["/root/shelf/cup1","/root/shelf/cup2","/root/shelfmate"]);
eq("bare glob is a name term", run("decor_cup*"),
   ["/root/shelf/cup1","/root/shelf/cup2"]);
eq("name glob ?", run("name:?nner_bit"), ["/root/shelf/cup2/inner"]);
eq("name glob with regex metachars escaped", run("name:inner.bit"), []);
eq("name exact", run("name:tool_bench"), ["/root/bench"]);
eq("name no match", run("name:zzz*"), []);
eq("mount depth-1 (either direction, loadable other end)",
   run("mount:/root/bench"), ["/root/shelf/cup1"]);
eq("mount from the carried side", run("mount:/root/shelf/cup1"), ["/root/bench"]);

// --- operators + fold ---
eq("union", run("path:/root/shelf + name:tool_*"),
   ["/root/shelf/cup1","/root/shelf/cup2","/root/shelf/cup2/inner","/root/bench"]);
eq("intersect", run("path:/root/shelf & name:decor_*"),
   ["/root/shelf/cup1","/root/shelf/cup2"]);
eq("difference", run("path:/root/shelf - name:*2*"),
   ["/root/shelf/cup1","/root/shelf/cup2/inner"]);
eq("flat left-to-right fold: (A + B) & C",
   run("name:decor_* + name:tool_* & path:/root/shelf"),
   ["/root/shelf/cup1","/root/shelf/cup2"]);
eq("difference then union re-adds", run("path:/root/shelf - name:decor_* + name:decor_cup1"),
   ["/root/shelf/cup2/inner","/root/shelf/cup1"]);
eq("empty expression", evalExpr([], G), []);
eq("difference to empty", run("name:decor_cup1 - name:decor_*"), []);

// --- text round-trip ---
const rt="finish=translucent + path:/root/shelf/* - name:decor_cup2";
const t1=parseExpr(rt);
if(exprToText(t1.terms)!==rt){ failures++;
  console.error("FAIL text round-trip: "+exprToText(t1.terms)); }
else console.log("ok text round-trip");
const t2=parseExpr(exprToText(t1.terms));
eq("reparse of canonical text evaluates identically",
   evalExpr(t2.terms,G), evalExpr(t1.terms,G));

if(failures){ console.error(failures+" failure(s)"); process.exit(1); }
console.log("ALL OK");
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_eval_expr_against_fixture_graph(tmp_path):
    with open(_TPL) as fh:
        html = fh.read()
    begin = html.index("--- compose:pure begin ---")
    end = html.index("--- compose:pure end ---")
    # back up to the start of the marker's comment line
    begin = html.rindex("//", 0, begin)
    pure = html[begin:end]
    assert "function evalExpr" in pure and "function parseExpr" in pure

    js = tmp_path / "compose_eval_test.js"
    js.write_text(pure + "\n" + _FIXTURE_AND_ASSERTS)
    result = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert result.returncode == 0, \
        "evalExpr unit tests failed:\n%s\n%s" % (result.stdout, result.stderr)
    assert "ALL OK" in result.stdout
