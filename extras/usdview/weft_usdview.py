#!/usr/bin/env python
"""weft's usdview launch shim -- run this in place of the `usdview` binary
(identical arguments) so the embedded "Weft Threads..." panel
(a QWebEngineView docked in usdview, see weftViewer/webenginepanel.py)
actually PAINTS on macOS.

## What this fixes -- and what it doesn't

The launch shim is one of TWO independent fixes the embedded panel needs
(the round-7 investigation in .superpowers/threadpanel-report.md separated
them empirically):

1. **The crash** (exit 139 the moment the page loaded) was NOT a graphics
   conflict at all: it is a PySide 6.11 wrapper-creation re-entrancy bug
   triggered by usdview's app-wide Python event filter receiving Qt events
   posted to QtWebEngine's internal C++ QObjects. That fix lives in the
   PLUGIN (weftViewer/webenginepanel.py removes the filter before creating
   the view) and needs no launcher: even a plain `usdview` no longer
   crashes when the panel opens.

2. **Painting.** usdview's viewport is a `QOpenGLWidget`, which forces the
   main window's backing store onto an OpenGL QRhi. QtWebEngine presents
   its frames through a `QQuickWidget`, which requires the QtQuick
   scenegraph's graphics API to MATCH the window it composites into -- and
   on macOS that API defaults to Metal. Mismatch means no QRhi, which
   means the panel loads, runs its JS, and round-trips the bridge, but
   draws a single flat nothing ("Failed to get a QRhi from the top-level
   widget's window" warnings; verified by pixel-grabbing the widget).
   Matching them needs two settings Qt requires BEFORE the `QApplication`
   is constructed -- and usdview builds its own deep inside
   `Usdviewq.Launcher().Run()`, well before any plugin can run code. Only
   a launcher standing in front of the real entry point can set them in
   time:

   - `QSG_RHI_BACKEND=opengl` -- QtQuick's scenegraph (and so the
     QQuickWidget presenting WebEngine's frames) uses OpenGL, matching
     the backing store usdview's own viewport forces.
   - `Qt.AA_ShareOpenGLContexts` -- WebEngine's GL resources are shared
     with the rest of the process, the standard prerequisite for
     embedding WebEngine in an OpenGL app.

Verified (see the report, "Round 7"): with only fix 1, the panel is
alive-but-invisible (widget grab: 1 unique color); with both, the full d3
viewer renders and the QWebChannel bridge round-trips, 3/3 real onscreen
runs, exit 0.

## Usage

Run this instead of `usdview`, with the same arguments:

    python weft_usdview.py --unloaded --bboxStandin /path/to/stage.usda

See extras/usdview/README.md for the full launch invocation alongside
`PXR_PLUGINPATH_NAME`/`PYTHONPATH`.
"""
from __future__ import annotations

import os
import sys


def _match_quick_scenegraph_to_usdviews_opengl():
    # Respect an explicit override from the environment, otherwise pin the
    # QtQuick scenegraph to OpenGL so QQuickWidget can composite into
    # usdview's OpenGL-backed main window (see module docstring).
    os.environ.setdefault("QSG_RHI_BACKEND", "opengl")


def _share_opengl_contexts_before_qapplication_exists():
    # The same Qt binding module usdview itself will resolve to -- setting
    # the attribute on a DIFFERENT binding's QCoreApplication class would
    # not affect the one usdview actually constructs.
    from pxr.Usdviewq.qt import QtCore
    QtCore.QCoreApplication.setAttribute(
        QtCore.Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)


def main():
    _match_quick_scenegraph_to_usdviews_opengl()
    _share_opengl_contexts_before_qapplication_exists()

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
