"""What `jitsd pull` does when usd-core is not installed at all.

`jitsd.pull` imports `deps.walk`, which imports `pxr` at module top level --
so a bare environment (no usd-core) must not surface a raw ModuleNotFoundError
from `jitsd pull`; the CLI/slice boundary is where failures become clean
diagnostics, even the failure of "the whole prim-level feature is
unavailable here". This file is the mirror image of the usual
`pytest.importorskip("pxr")` guard: it only runs where pxr is ABSENT, so it
is skipped (not failed) in the usual usd-core-equipped test environment."""

import importlib.util

import pytest

if importlib.util.find_spec("pxr") is not None:
    pytest.skip("only meaningful without usd-core installed", allow_module_level=True)

from jitsd.cli import main


def test_pull_without_usd_core_fails_cleanly(tmp_path, capsys):
    rc = main(["pull", "x", "--context", "nofile.usda"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "usd-core is required for prim-level pulls" in err
    assert "Traceback" not in err
