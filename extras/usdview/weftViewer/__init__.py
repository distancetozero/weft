#
# The weft usdview plugin: "the ask bar in the viewer" -- v1.
#
# Four commands on a "Weft" menu:
#   Ask...              resolve_seeds() against the LIVE stage, live-select
#   Solo threads        pull() the selection's threads, view-solo the rest
#   Restore world        reactivate whatever Solo threads deactivated
#   Who depends on this?  incoming edges onto the selection
#
# Qt is used only in this file (via pxr.Usdviewq.qt, which picks the PySide
# module usdview itself is running on). All weft/pxr-heavy imports are
# deferred into the command callbacks so loading this plugin at usdview
# startup stays cheap. Every callback is guarded: a ValueError from weft
# (a malformed ask, an unparseable follow term, ...) is reported through
# usdviewApi.PrintStatus rather than raised into the UI.
#
from __future__ import annotations

import os
import sys

try:
    from pxr import Tf
    from pxr.Usdviewq.plugin import PluginContainer
    from pxr.Usdviewq.qt import QtCore, QtGui, QtWidgets
except ImportError as _e:
    # pxr.Usdviewq (and the Qt binding usdview itself runs on) isn't
    # available in this environment. Most likely this module is being
    # imported only for its pure-logic sibling, core.py -- Python always
    # runs a package's __init__.py before a submodule import, so
    # "import weftViewer.core" hits this file first. Define a harmless
    # stand-in so that import still succeeds and core.py stays reachable;
    # inside a real usdview process pxr.Usdviewq is always present, so this
    # branch is never taken there, and the Weft menu is registered normally.
    print("weftViewer: pxr.Usdviewq unavailable (%s); the Weft menu will not "
          "be registered by this import" % _e, file=sys.stderr)
    Tf = None
    PluginContainer = object
    QtCore = QtGui = QtWidgets = None

_MARKER_KEY = "weft:solo"


class WeftViewerContainer(PluginContainer):
    """Usdview plugin container for weft's Ask/Solo/Restore/Who commands."""

    def __init__(self):
        # stageIdentifier -> set(paths) deactivated by the last Solo threads
        # call on that stage, so Restore world can undo exactly that.
        self._deactivated = {}
        self._lastPull = None
        self._receiptDock = None
        self._receiptText = None
        # Held onto so PySide doesn't garbage-collect a dialog out from under
        # its own signal connections while it's still on screen.
        self._openDialogs = []

    # -- registration -------------------------------------------------

    def registerPlugins(self, plugRegistry, plugCtx):
        self._askCmd = plugRegistry.registerCommandPlugin(
            "WeftViewerContainer.ask", "Ask...", self._onAsk,
            description="Resolve a weft ask against the live stage and select the results.")
        self._soloCmd = plugRegistry.registerCommandPlugin(
            "WeftViewerContainer.solo", "Solo threads", self._onSolo,
            description="Pull the selection's threads and view-solo everything else.")
        self._restoreCmd = plugRegistry.registerCommandPlugin(
            "WeftViewerContainer.restore", "Restore world", self._onRestore,
            description="Reactivate whatever Solo threads deactivated.")
        self._whoCmd = plugRegistry.registerCommandPlugin(
            "WeftViewerContainer.who", "Who depends on this?", self._onWho,
            description="Incoming edges onto the selection.")

    def configureView(self, plugRegistry, plugUIBuilder):
        menu = plugUIBuilder.findOrCreateMenu("Weft")
        menu.addItem(self._askCmd)
        menu.addItem(self._soloCmd)
        menu.addItem(self._restoreCmd)
        menu.addItem(self._whoCmd)

    # -- Ask... ---------------------------------------------------------

    def _onAsk(self, api):
        try:
            self._showAskDialog(api)
        except Exception as e:
            api.PrintStatus("Weft Ask: %s" % e)

    def _showAskDialog(self, api):
        dialog = QtWidgets.QDialog(api.qMainWindow)
        dialog.setWindowTitle("Weft: Ask")
        layout = QtWidgets.QVBoxLayout(dialog)

        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText(
            "name:*, id:..., role:..., offers:..., requires:..., "
            "where:attr=value, near:SEED,R, within:6-floats, path:...")
        layout.addWidget(edit)

        declLabel = QtWidgets.QLabel("")
        declLabel.setWordWrap(True)
        layout.addWidget(declLabel)

        listWidget = QtWidgets.QListWidget()
        listWidget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        layout.addWidget(listWidget)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.close)
        buttons.accepted.connect(dialog.close)
        layout.addWidget(buttons)

        def runAsk():
            from . import core as _core

            text = edit.text().strip()
            listWidget.clear()
            if not text:
                declLabel.setText("")
                return
            try:
                paths, declaration = _core.ask_rows(api.stage, text)
            except ValueError as e:
                declLabel.setText("error: %s" % e)
                api.PrintStatus("Weft Ask: %s" % e)
                return
            declLabel.setText(declaration)
            for path in paths:
                listWidget.addItem(path)
            api.PrintStatus("Weft Ask: %s" % declaration)

        def onSelectionChanged():
            paths = [item.text() for item in listWidget.selectedItems()]
            api.ClearPrimSelection()
            for path in paths:
                prim = api.stage.GetPrimAtPath(path)
                if prim:
                    api.AddPrimToSelection(prim)
            api.UpdateGUI()

        edit.returnPressed.connect(runAsk)
        listWidget.itemSelectionChanged.connect(onSelectionChanged)

        dialog.resize(560, 420)
        dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        dialog.destroyed.connect(lambda *_: self._openDialogs.remove(dialog)
                                  if dialog in self._openDialogs else None)
        self._openDialogs.append(dialog)
        dialog.show()

    # -- Solo threads / Restore world ------------------------------------

    def _onSolo(self, api):
        try:
            self._runSolo(api)
        except Exception as e:
            api.PrintStatus("Weft Solo threads: %s" % e)

    def _runSolo(self, api):
        from . import core as _core

        stageId = api.stageIdentifier
        if not stageId or not os.path.isfile(stageId):
            api.PrintStatus(
                "Weft Solo threads: the open stage has no file on disk "
                "(anonymous root layer) -- pull needs a real --context file")
            return

        seedPaths = [str(p) for p in api.selectedPaths]
        if not seedPaths:
            api.PrintStatus("Weft Solo threads: select one or more prims first")
            return

        kinds = _core.edge_kinds(api.stage, seedPaths)
        follow = self._showFollowChecklist(api, kinds)
        if follow is None:
            return  # cancelled

        try:
            from weft import manifest as _manifest
            from weft import pull as _pull
        except ImportError:
            api.PrintStatus("Weft Solo threads: usd-core is required (pip install usd-core)")
            return

        try:
            seeds = ["path:%s" % p for p in seedPaths]
            p = _pull.pull(stageId, seeds, follow=follow)
        except ValueError as e:
            api.PrintStatus("Weft Solo threads: %s" % e)
            return
        _manifest.layer_hashes(p)
        self._lastPull = p

        memberPaths = [m.path for m in p.members]
        toDeactivate = _core.deactivation_set(api.stage, memberPaths)

        from pxr import Usd
        deactivated = set()
        with Usd.EditContext(api.stage, api.stage.GetSessionLayer()):
            for path in toDeactivate:
                prim = api.stage.GetPrimAtPath(path)
                if prim and prim.IsActive():
                    prim.SetActive(False)
                    prim.SetCustomDataByKey(_MARKER_KEY, True)
                    deactivated.add(path)
        self._deactivated[stageId] = deactivated

        self._showReceipt(api, p)
        api.UpdateGUI()
        api.PrintStatus(
            "Weft Solo threads (view solo -- deactivation, not a population mask): "
            "%d member%s, %d prim%s deactivated"
            % (len(p.members), "" if len(p.members) == 1 else "s",
               len(deactivated), "" if len(deactivated) == 1 else "s"))

    def _showFollowChecklist(self, api, kinds):
        """A small modal checklist of the kinds found on the selection's own
        outgoing edges, plus free text for anything else (spec section 7's
        follow language, e.g. `up:electrical:feeds*8`). Returns a list of
        follow-term strings, or None if the user cancelled."""
        dialog = QtWidgets.QDialog(api.qMainWindow)
        dialog.setWindowTitle("Weft: Solo threads -- follow")
        layout = QtWidgets.QVBoxLayout(dialog)

        layout.addWidget(QtWidgets.QLabel(
            "Kinds found on the selection's outgoing edges:"))
        checks = []
        if kinds:
            for kind in kinds:
                cb = QtWidgets.QCheckBox(kind)
                cb.setChecked(True)
                layout.addWidget(cb)
                checks.append((kind, cb))
        else:
            layout.addWidget(QtWidgets.QLabel("  (none found)"))

        layout.addWidget(QtWidgets.QLabel("Additional follow terms (comma-separated):"))
        extra = QtWidgets.QLineEdit()
        extra.setPlaceholderText("e.g. up:electrical:feeds*8")
        layout.addWidget(extra)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return None

        terms = [kind for kind, cb in checks if cb.isChecked()]
        extraText = extra.text().strip()
        if extraText:
            terms += [t.strip() for t in extraText.split(",") if t.strip()]
        return terms

    def _onRestore(self, api):
        try:
            self._runRestore(api)
        except Exception as e:
            api.PrintStatus("Weft Restore world: %s" % e)

    def _runRestore(self, api):
        from pxr import Usd

        stageId = api.stageIdentifier
        session = api.stage.GetSessionLayer()
        restored = set()

        with Usd.EditContext(api.stage, session):
            for path in self._deactivated.pop(stageId, set()):
                prim = api.stage.GetPrimAtPath(path)
                if prim:
                    prim.ClearActive()
                    prim.ClearCustomDataByKey(_MARKER_KEY)
                    restored.add(path)

            # Defensive sweep: reactivate any prim carrying our marker, even
            # one this container instance never tracked (a previous usdview
            # process, a stage reopened after a crash, ...).
            # Usd.PrimAllPrimsPredicate -- unlike the stage's default
            # traversal predicate -- includes inactive prims, so a prim we
            # (or an earlier run) deactivated is still found here.
            # GetCustomDataByKey composes correctly through the ":" in our
            # marker key (customData nests namespaced keys: "weft:solo" is
            # stored as {"weft": {"solo": True}}, not a flat "weft:solo"
            # entry) -- reading raw Sdf.PrimSpec.customData would have to
            # reimplement that nesting; the composed Usd.Prim API already
            # does it.
            for prim in api.stage.Traverse(Usd.PrimAllPrimsPredicate):
                if not prim.GetCustomDataByKey(_MARKER_KEY):
                    continue
                prim.ClearActive()
                prim.ClearCustomDataByKey(_MARKER_KEY)
                restored.add(prim.GetPath().pathString)

        api.UpdateGUI()
        api.PrintStatus("Weft Restore world: %d prim%s reactivated"
                         % (len(restored), "" if len(restored) == 1 else "s"))

    # -- Who depends on this? --------------------------------------------

    def _onWho(self, api):
        try:
            self._showWhoDialog(api)
        except Exception as e:
            api.PrintStatus("Weft Who depends on this?: %s" % e)

    def _showWhoDialog(self, api):
        stageId = api.stageIdentifier
        if not stageId or not os.path.isfile(stageId):
            api.PrintStatus(
                "Weft Who depends on this?: the open stage has no file on disk "
                "(anonymous root layer)")
            return
        seedPaths = [str(p) for p in api.selectedPaths]
        if not seedPaths:
            api.PrintStatus("Weft Who depends on this?: select one or more prims first")
            return

        dialog = QtWidgets.QDialog(api.qMainWindow)
        dialog.setWindowTitle("Weft: Who depends on this?")
        layout = QtWidgets.QVBoxLayout(dialog)

        depthRow = QtWidgets.QHBoxLayout()
        depthRow.addWidget(QtWidgets.QLabel("Depth:"))
        depthSpin = QtWidgets.QSpinBox()
        depthSpin.setRange(1, 4)
        depthSpin.setValue(1)
        depthRow.addWidget(depthSpin)
        depthRow.addStretch(1)
        layout.addLayout(depthRow)

        table = QtWidgets.QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["source", "kind", "member"])
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)

        def refresh():
            from . import core as _core
            try:
                rows = _core.who_rows(stageId, seedPaths, depthSpin.value())
            except ValueError as e:
                api.PrintStatus("Weft Who depends on this?: %s" % e)
                return
            table.setRowCount(0)
            for src, kind, member in rows:
                r = table.rowCount()
                table.insertRow(r)
                table.setItem(r, 0, QtWidgets.QTableWidgetItem(src))
                table.setItem(r, 1, QtWidgets.QTableWidgetItem(kind))
                table.setItem(r, 2, QtWidgets.QTableWidgetItem(member))
            api.PrintStatus("Weft Who depends on this?: %d incoming edge%s"
                             % (len(rows), "" if len(rows) == 1 else "s"))

        def onCellClicked(row, _col):
            item = table.item(row, 0)
            if not item:
                return
            prim = api.stage.GetPrimAtPath(item.text())
            api.ClearPrimSelection()
            if prim:
                api.AddPrimToSelection(prim)
            api.UpdateGUI()

        table.cellClicked.connect(onCellClicked)
        depthSpin.valueChanged.connect(lambda _v: refresh())

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.close)
        buttons.accepted.connect(dialog.close)
        layout.addWidget(buttons)

        try:
            refresh()
        except ImportError:
            api.PrintStatus("Weft Who depends on this?: usd-core is required (pip install usd-core)")
            return

        dialog.resize(680, 420)
        dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        dialog.destroyed.connect(lambda *_: self._openDialogs.remove(dialog)
                                  if dialog in self._openDialogs else None)
        self._openDialogs.append(dialog)
        dialog.show()

    # -- Receipt panel ----------------------------------------------------

    def _ensureReceiptDock(self, api):
        if self._receiptDock is not None:
            return self._receiptDock

        dock = QtWidgets.QDockWidget("Weft Receipt", api.qMainWindow)
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        text = QtWidgets.QPlainTextEdit()
        text.setReadOnly(True)
        text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        font = QtGui.QFont("Monospace")
        font.setStyleHint(QtGui.QFont.TypeWriter)
        text.setFont(font)
        layout.addWidget(text)

        buttonRow = QtWidgets.QHBoxLayout()
        copyBtn = QtWidgets.QPushButton("Copy mask")
        saveBtn = QtWidgets.QPushButton("Save manifest...")
        buttonRow.addWidget(copyBtn)
        buttonRow.addWidget(saveBtn)
        buttonRow.addStretch(1)
        layout.addLayout(buttonRow)

        dock.setWidget(widget)
        copyBtn.clicked.connect(lambda: self._copyMask(api))
        saveBtn.clicked.connect(lambda: self._saveManifest(api))

        api.qMainWindow.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self._receiptDock = dock
        self._receiptText = text
        return dock

    def _showReceipt(self, api, pullResult):
        from . import core as _core
        dock = self._ensureReceiptDock(api)
        self._receiptText.setPlainText(_core.receipt_text(pullResult))
        dock.show()
        dock.raise_()

    def _copyMask(self, api):
        try:
            if self._lastPull is None:
                api.PrintStatus("Weft: no receipt yet -- run Solo threads first")
                return
            paths = "\n".join(m.path for m in self._lastPull.members)
            QtWidgets.QApplication.clipboard().setText(paths)
            api.PrintStatus("Weft: copied %d member path%s to the clipboard"
                             % (len(self._lastPull.members),
                                "" if len(self._lastPull.members) == 1 else "s"))
        except Exception as e:
            api.PrintStatus("Weft: copy mask failed: %s" % e)

    def _saveManifest(self, api):
        try:
            if self._lastPull is None:
                api.PrintStatus("Weft: no receipt yet -- run Solo threads first")
                return
            from weft import manifest as _manifest
            path, _filter = QtWidgets.QFileDialog.getSaveFileName(
                api.qMainWindow, "Save manifest", "", "USD ASCII (*.usda)")
            if not path:
                return
            doc = _manifest.to_document(self._lastPull)
            with open(path, "w") as fh:
                fh.write(doc)
            api.PrintStatus("Weft: manifest saved to %s" % path)
        except Exception as e:
            api.PrintStatus("Weft: save manifest failed: %s" % e)


# We load the PluginContainer using libplug (see plugInfo.json), so it needs
# to be a defined Tf.Type -- see pxr.Usdviewq.plugin.PluginContainerTfType.
if Tf is not None:
    Tf.Type.Define(WeftViewerContainer)
