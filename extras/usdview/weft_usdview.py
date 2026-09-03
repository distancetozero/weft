#!/usr/bin/env python
"""weft's usdview launch shim -- run this in place of the `usdview` binary
(identical arguments) to make the embedded "Weft Threads..." browser panel
(a QWebEngineView docked in usdview, see weftViewer/threadpanel.py) survive
on macOS.

## Why a launcher, not something the plugin itself can do

QtWebEngine's Chromium compositor needs OpenGL context sharing set up via
`Qt.AA_ShareOpenGLContexts` -- and Qt requires that attribute be set BEFORE
the `QApplication` is constructed; setting it after has no effect. usdview
constructs its own `QApplication` deep inside `Usdviewq.Launcher().Run()`
(see `pxr/usdImaging/usdviewq/__init__.py`), and a usdview PLUGIN (this
project's own `weftViewer`) is only loaded and given a chance to run code
well AFTER that `QApplication` -- and the main window built on top of it --
already exist. There is no hook available to a plugin that runs early
enough. A launcher that sets the attribute and THEN calls usdview's own
entry point is the only place in the process's lifetime where this is
possible at all.

This is the actual, load-bearing difference between an app like Houdini
(which sets this attribute itself before ever embedding a WebEngine view)
and a bare usdview process (which never does) -- not a difference in this
project's own plugin code, which cannot reach far enough upstream to set
it on its own. See `.superpowers/threadpanel-report.md` for the full
history of what was tried before landing on this fix, including why a
scripted/headless test harness gave false confidence about a crash that
only reproduced on a real, onscreen, interactively-composited GUI.

## What this shim does, in order

1. Forces QtWebEngine onto CPU compositing
   (`QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`, merged into any value
   already present in the environment rather than clobbering it) --
   removes the Chromium-Metal-compositor-vs-usdview's-own-OpenGL-surface
   conflict this whole crash history traces back to. Nil practical cost
   for a 2D UI page like the thread viewer.
2. Sets `Qt.AA_ShareOpenGLContexts` via
   `QCoreApplication.setAttribute(...)`, using the SAME Qt binding module
   usdview itself resolves to (`pxr.Usdviewq.qt`) -- this MUST happen
   before step 4 constructs the `QApplication`.
3. Imports `PySide6.QtWebEngineWidgets` (best-effort; silently skipped if
   unavailable) before the `QApplication` exists, so its own Chromium
   resource initialization runs on the same terms a from-scratch
   WebEngine application would use, rather than lazily inside an
   already-running usdview process the first time the panel opens.
4. Runs usdview's own real entry point (`pxr.Usdviewq.Launcher().Run()`,
   the exact same call `<usd-install>/bin/usdview`'s own `__main__` block
   makes) with `sys.argv` untouched, so every ordinary usdview argument
   (`--unloaded`, `--bboxStandin`, a stage path, ...) passes through
   exactly as it would to the real binary.

## Usage

Run this instead of `usdview`, with the same arguments:

    python weft_usdview.py --unloaded --bboxStandin /path/to/stage.usda

See extras/usdview/README.md for the full launch invocation alongside
`PXR_PLUGINPATH_NAME`/`PYTHONPATH`.
"""
from __future__ import annotations

import os
import sys


def _force_cpu_compositing():
    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--disable-gpu" in existing:
        return
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (existing + " --disable-gpu").strip()


def _share_opengl_contexts_before_qapplication_exists():
    # The same Qt binding module usdview itself will resolve to -- setting
    # the attribute on a DIFFERENT binding's QCoreApplication class would
    # not affect the one usdview actually constructs.
    from pxr.Usdviewq.qt import QtCore
    QtCore.QCoreApplication.setAttribute(
        QtCore.Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)


def _preimport_webengine_best_effort():
    try:
        from PySide6 import QtWebEngineWidgets  # noqa: F401
    except ImportError:
        pass


def main():
    _force_cpu_compositing()
    _share_opengl_contexts_before_qapplication_exists()
    _preimport_webengine_best_effort()

    import signal
    import pxr.Usdviewq as Usdviewq

    # Let Ctrl-C kill the app -- identical to the real usdview binary.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        Usdviewq.Launcher().Run()
    except Usdviewq.InvalidUsdviewOption as e:
        print("ERROR: " + str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
