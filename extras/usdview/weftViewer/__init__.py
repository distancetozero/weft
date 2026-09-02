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


def _guard(api, label, fn):
    """Wrap a Qt slot so ANY exception it raises -- not just the ValueError
    a malformed weft ask/follow term raises -- becomes a PrintStatus message
    instead of an uncaught exception inside Qt's event loop. Every nested
    function connected to a signal (not just the four top-level registered
    commands, which are already wrapped by their own `_onX` methods) is
    wired through this."""
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            api.PrintStatus("%s: %s" % (label, e))
    return wrapped


def _refuse(api, msg):
    """A REFUSAL the user must actually SEE, not just a line in the status
    bar: PrintStatus alone landed only there, which the owner reported
    missing twice ("nothing pops up") for the no-selection and
    anonymous-stage guards. PrintStatus stays too, for the log/scripted
    use. Reserved for refusals -- paths where the command does nothing at
    all; a success stays status-bar-only, same as before."""
    api.PrintStatus(msg)
    QtWidgets.QMessageBox.information(api.qMainWindow, "Weft", msg)


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

        # The classic Qt default-button trap: QDialogButtonBox makes its
        # Close button auto-default, so pressing Enter in `edit` activates
        # Close (-> dialog.close()) instead of -- or as well as --
        # `edit.returnPressed`. The dialog vanishes before `runAsk` below
        # produces anything a user can see. Strip both flags so Enter is
        # ONLY `edit.returnPressed`.
        closeBtn = buttons.button(QtWidgets.QDialogButtonBox.Close)
        closeBtn.setAutoDefault(False)
        closeBtn.setDefault(False)

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
            # Enter alone both resolves AND selects: selectAll() fires
            # itemSelectionChanged, which onSelectionChanged below turns
            # into a live viewport selection -- type, Enter, things light up.
            listWidget.selectAll()
            api.PrintStatus("Weft Ask: %s" % declaration)

        def onSelectionChanged():
            paths = [item.text() for item in listWidget.selectedItems()]
            api.ClearPrimSelection()
            for path in paths:
                prim = api.stage.GetPrimAtPath(path)
                if prim:
                    api.AddPrimToSelection(prim)
            api.UpdateGUI()

        edit.returnPressed.connect(_guard(api, "Weft Ask", runAsk))
        listWidget.itemSelectionChanged.connect(
            _guard(api, "Weft Ask", onSelectionChanged))

        dialog.resize(560, 420)
        dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        dialog.destroyed.connect(_guard(api, "Weft Ask", lambda *_: (
            self._openDialogs.remove(dialog) if dialog in self._openDialogs else None)))
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
            _refuse(api, "Weft Solo threads: the open stage has no file on disk "
                    "(anonymous root layer) -- pull needs a real --context file")
            return

        seedPaths = [str(p) for p in api.selectedPaths]
        if not seedPaths:
            _refuse(api, "Weft Solo threads: select one or more prims first")
            return

        kinds = _core.edge_kinds(api.stage, seedPaths)
        follow = self._showFollowChecklist(api, kinds)
        if follow is None:
            return  # cancelled, stage untouched

        try:
            from weft import manifest as _manifest
            from weft import pull as _pull
        except ImportError:
            api.PrintStatus("Weft Solo threads: usd-core is required (pip install usd-core)")
            return

        # FINDING 4: usdview's own GUI refresh walks the current prim AND
        # property focus (property focus rides prim focus) -- if that path
        # points into a region we are about to deactivate, usdview's OWN
        # _resetGUI -> _populatePropertyInspector -> getFocusProp crashes
        # with "RuntimeError: Accessed invalid null prim" once it's stale,
        # which happens on ANY stage edit usdview reacts to, not only our
        # own UpdateGUI() calls. Clear the selection before authoring ANY
        # deactivation -- both the restore-first reactivation just below
        # (whose own selection guard lives in `_runRestore`, reused here)
        # and the fresh deactivation further down. A prim GUARANTEED to
        # survive -- the first pull member -- is reselected once we know
        # what that is.
        api.ClearPrimSelection()
        api.UpdateGUI()

        # Restore-before-solo, so a second Solo threads call is always safe
        # without an intervening Restore world: deactivation_set's
        # GetChildren() walk uses the default (active-only) predicate, so it
        # cannot see -- and therefore cannot correctly route a spine
        # through -- prims a PREVIOUS solo already deactivated (it could
        # even silently drop a new member whose ancestor is still
        # deactivated). Reuse the exact restore code path Restore world
        # uses, so pull() and deactivation_set below always start from a
        # fully-active stage.
        priorRestored = self._runRestore(api)

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
                    prim.SetCustomDataByKey(_core.MARKER_KEY, True)
                    deactivated.add(path)
        # A full restore just ran above, so there is nothing stale left to
        # union with here -- this replaces an already-empty tracking entry.
        self._deactivated[stageId] = deactivated

        # Selection stayed cleared through both mutations above -- reselect
        # now that the frontier is settled, onto the first pull member
        # (members are exactly what stays active, by construction).
        if memberPaths:
            firstMember = api.stage.GetPrimAtPath(memberPaths[0])
            if firstMember:
                api.AddPrimToSelection(firstMember)

        self._showReceipt(api, p)
        api.UpdateGUI()
        priorNote = (" (%d prior deactivation%s cleared first)"
                     % (len(priorRestored), "" if len(priorRestored) == 1 else "s")
                     if priorRestored else "")
        api.PrintStatus(
            "Weft Solo threads (view solo -- deactivation, not a population mask): "
            "%d member%s, %d prim%s deactivated%s"
            % (len(p.members), "" if len(p.members) == 1 else "s",
               len(deactivated), "" if len(deactivated) == 1 else "s", priorNote))

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
            restored = self._runRestore(api)
            api.UpdateGUI()
            api.PrintStatus("Weft Restore world: %d prim%s reactivated"
                             % (len(restored), "" if len(restored) == 1 else "s"))
        except Exception as e:
            api.PrintStatus("Weft Restore world: %s" % e)

    def _runRestore(self, api):
        """Reactivate everything Solo threads deactivated on this stage:
        this container's own tracking, plus a defensive sweep (via
        `core.restore_set`) for any prim carrying our marker that this
        instance never tracked -- a previous usdview process, a stage
        reopened after a crash, .... Returns the set of paths reactivated.
        No PrintStatus/UpdateGUI here (beyond the selection guard below):
        this is also the exact code path Solo threads calls FIRST on every
        run (see `_runSolo`), and a mid-solo status message would be
        confusing noise.

        FINDING 4 selection guard, standalone Restore world AND the
        restore-first step inside `_runSolo` alike: clear the selection
        before reactivating anything -- usdview reacts to stage edits on
        its own, so a stale prim/property focus can crash usdview's OWN
        GUI refresh regardless of when we call UpdateGUI() ourselves -- then
        re-add whatever of the PRE-restore selection still resolves to a
        valid, active prim once the mutation is done. When called from
        `_runSolo`, the selection was typically already cleared by the
        caller a moment ago, so capturing it here just captures an empty
        list -- a harmless no-op, not a conflict."""
        from pxr import Usd
        from . import core as _core

        stageId = api.stageIdentifier
        session = api.stage.GetSessionLayer()

        priorSelected = [str(p) for p in api.selectedPaths]
        api.ClearPrimSelection()
        api.UpdateGUI()

        tracked = self._deactivated.pop(stageId, set())
        # core.restore_set reads the CURRENT marker set fresh off the live
        # stage -- it is not `tracked`'s complement, it can overlap it
        # entirely (the common case) or extend past it (the defensive case
        # above), so the two are unioned, not chained.
        toRestore = tracked | set(_core.restore_set(api.stage))

        restored = set()
        with Usd.EditContext(api.stage, session):
            for path in toRestore:
                prim = api.stage.GetPrimAtPath(path)
                if prim:
                    prim.ClearActive()
                    prim.ClearCustomDataByKey(_core.MARKER_KEY)
                    restored.add(path)

        for path in priorSelected:
            prim = api.stage.GetPrimAtPath(path)
            if prim and prim.IsActive():
                api.AddPrimToSelection(prim)

        return restored

    # -- Who depends on this? --------------------------------------------

    def _onWho(self, api):
        try:
            self._showWhoDialog(api)
        except Exception as e:
            api.PrintStatus("Weft Who depends on this?: %s" % e)

    def _showWhoDialog(self, api):
        stageId = api.stageIdentifier
        if not stageId or not os.path.isfile(stageId):
            _refuse(api, "Weft Who depends on this?: the open stage has no file "
                    "on disk (anonymous root layer)")
            return
        seedPaths = [str(p) for p in api.selectedPaths]
        if not seedPaths:
            _refuse(api, "Weft Who depends on this?: select one or more prims first")
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

        label = "Weft Who depends on this?"
        table.cellClicked.connect(_guard(api, label, onCellClicked))
        depthSpin.valueChanged.connect(_guard(api, label, lambda _v: refresh()))

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.close)
        buttons.accepted.connect(dialog.close)
        layout.addWidget(buttons)

        # Same default-button trap as the Ask dialog (see _showAskDialog):
        # strip auto-default/default from Close so Enter elsewhere in this
        # dialog (e.g. while the depth spinbox has focus) doesn't silently
        # close it.
        closeBtn = buttons.button(QtWidgets.QDialogButtonBox.Close)
        closeBtn.setAutoDefault(False)
        closeBtn.setDefault(False)

        # Not wrapped in _guard: this first call happens during dialog
        # construction, not from a live signal, and an ImportError here
        # means the dialog should never be shown at all. A third refusal
        # path with the same "nothing pops up" failure mode as the two
        # guards above (audited for finding 5), so it gets the same
        # treatment.
        try:
            refresh()
        except ImportError:
            _refuse(api, "%s: usd-core is required (pip install usd-core)" % label)
            return

        dialog.resize(680, 420)
        dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        dialog.destroyed.connect(_guard(api, label, lambda *_: (
            self._openDialogs.remove(dialog) if dialog in self._openDialogs else None)))
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
