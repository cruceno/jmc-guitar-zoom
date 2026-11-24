"""Librarian actions of the main window: backup all, copy/paste/swap/clear, export/import.

Every pedal write goes through ``PedalWorker.write_patches`` (backup of the slot, sent form,
read-back compare, stop at the first failure). Without a pedal the same operations act on the
in-memory set as undoable edits and leave the slots dirty; "Write all dirty to pedal" sends them
later. A patch that may not be written (A1/A2/A3 blockers) is staged, never sent.
"""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QProgressBar, QPushButton

from zoomstudio.patches import edit, library
from zoomstudio.patches.model import Patch
from zoomstudio.patches.zptc import build_zptc, parse_zptc


class LibraryMixin:
    """Mixed into ``MainWindow``; relies on its patch store, worker and signals."""

    def _init_library(self) -> None:
        self._clipboard: Patch | None = None

    # ------------------------------------------------------------------ UI

    def _build_library_ui(self) -> None:
        def action(text, slot, shortcut=None, tip=""):
            act = QAction(text, self)
            act.triggered.connect(lambda _checked=False: slot())
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
                act.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            act.setToolTip(tip or text)
            return act

        self.copy_action = action("Copy patch", lambda: self._with_selected(self.copy_patch), "Ctrl+C")
        self.paste_action = action("Paste patch", lambda: self._with_selected(self.paste_patch), "Ctrl+V")
        self.clear_action = action("Clear slot", lambda: self._with_selected(self.clear_slot), "Delete",
                                   "Write the factory Empty patch to the slot")
        self.backup_action = action("Back up all patches", lambda: self.backup_all(False))
        self.backup_files_action = action("Back up patches and pedal files", lambda: self.backup_all(True))
        self.write_dirty_action = action("Write all dirty to pedal", self.write_all_dirty)
        self.export_selected_action = action("Export selected patch...", self._choose_export_selected)
        self.export_all_action = action("Export all patches...", self._choose_export_all)
        self.import_file_action = action("Import patch file into selected slot...", self._choose_import_file)
        self.import_folder_action = action("Import backup folder...", self._choose_import_folder)

        for act in (self.copy_action, self.paste_action, self.clear_action):
            self.patch_list.addAction(act)  # shortcuts act only while the patch list has focus
        menu = self.menuBar().addMenu("&Library")
        for act in (self.backup_action, self.backup_files_action, None, self.copy_action, self.paste_action,
                    self.clear_action, None, self.export_selected_action, self.export_all_action,
                    self.import_file_action, self.import_folder_action, None, self.write_dirty_action):
            if act is None:
                menu.addSeparator()
            else:
                menu.addAction(act)

        self.patch_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.patch_list.customContextMenuRequested.connect(self._show_patch_menu)
        self.patch_list.patch_dropped.connect(self.swap_patches)

        self.task_bar = QProgressBar()
        self.task_bar.setMaximumWidth(260)
        self.task_cancel = QPushButton("Cancel")
        self.task_cancel.clicked.connect(self._cancel_task)
        self.task_bar.hide()
        self.task_cancel.hide()
        self.statusBar().addPermanentWidget(self.task_bar)
        self.statusBar().addPermanentWidget(self.task_cancel)

    def _update_library_actions(self) -> None:
        idle = not self._saving
        connected = self._is_connected and self._worker is not None
        has_patch = self.current_patch is not None
        self.backup_action.setEnabled(connected and idle)
        self.backup_files_action.setEnabled(connected and idle)
        self.write_dirty_action.setEnabled(connected and idle and self.any_dirty())
        self.copy_action.setEnabled(has_patch)
        self.paste_action.setEnabled(self._location is not None and self._clipboard is not None and idle)
        self.clear_action.setEnabled(self._location is not None and idle)
        self.export_selected_action.setEnabled(has_patch)
        self.export_all_action.setEnabled(bool(self._patches))
        self.import_file_action.setEnabled(self._location is not None and idle)
        self.import_folder_action.setEnabled(idle)

    def _show_patch_menu(self, pos) -> None:
        item = self.patch_list.itemAt(pos)
        if item is None:
            return
        self.patch_list.setCurrentItem(item)
        menu = QMenu(self)
        for act in (self.copy_action, self.paste_action, self.clear_action, None, self.export_selected_action,
                    self.import_file_action):
            if act is None:
                menu.addSeparator()
            else:
                menu.addAction(act)
        menu.exec(self.patch_list.viewport().mapToGlobal(pos))

    def _with_selected(self, operation) -> None:
        if self._location is None:
            self.statusBar().showMessage("Select a patch first")
            return
        operation(self._location)

    def _ask(self, title: str, text: str) -> bool:
        reply = QMessageBox.question(self, title, text,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        return reply == QMessageBox.StandardButton.Yes

    @property
    def _can_write(self) -> bool:
        return self._is_connected and self._worker is not None

    # ------------------------------------------------------- applying changes

    def _content(self, location: int) -> Patch:
        patch = self._patches.get(location)
        return copy.deepcopy(patch) if patch is not None else library.empty_patch()

    def _stage(self, changes: dict[int, Patch], text: str) -> None:
        """Put ``changes`` into the in-memory set as undoable edits (the slots become dirty)."""
        from .main_window import PatchEdit  # late import: main_window imports this module

        for location in sorted(changes):
            self._stack(location).push(PatchEdit(self, location, self._patches.get(location),
                                                 changes[location], text, None, None, None))

    def _blockers(self, changes: dict[int, Patch]) -> dict[int, list[str]]:
        found = {loc: edit.save_blockers(p, self.catalog, self.allowed_ids) for loc, p in changes.items()}
        return {loc: why for loc, why in found.items() if why}

    def _describe_blockers(self, blocked: dict[int, list[str]]) -> str:
        return "; ".join(f"patch {self._display(loc)}: {why[0]}" for loc, why in sorted(blocked.items()))

    def _apply(self, changes: dict[int, Patch], text: str) -> None:
        """Connected: write through the safe queue. Offline (or blocked): stage as dirty edits."""
        if not self._can_write:
            self._stage(changes, text)
            return
        blocked = self._blockers(changes)
        if blocked:
            self._stage(changes, text)
            self._report_error("Not written to the pedal, fix these first: " + self._describe_blockers(blocked))
            return
        self._queue_write({loc: changes[loc] for loc in changes})

    def _queue_write(self, patches: dict[int, Patch]) -> bool:
        if self.backup_dir is None:
            self._report_error("No backup folder configured: refusing to write to the pedal")
            return False
        try:
            items = [(loc, build_zptc(edit.sent_form(patches[loc]))) for loc in sorted(patches)]
        except ValueError as exc:
            self._report_error(f"Cannot build the patch: {exc}")
            return False
        self._set_saving(True)
        self.statusBar().showMessage(f"Writing {len(items)} patch(es) to the pedal...")
        self._queue_requested.emit(items, self.backup_dir)
        return True

    # ------------------------------------------------------ patch operations

    def copy_patch(self, location: int) -> None:
        patch = self._patches.get(location)
        if patch is None:
            self._report_error(f"Patch {self._display(location)} is empty: nothing to copy")
            return
        self._clipboard = copy.deepcopy(patch)
        self.statusBar().showMessage(f"Copied patch {self._display(location)} ({patch.name})")
        self._update_buttons()

    def paste_patch(self, location: int) -> None:
        if self._saving:
            return
        if self._clipboard is None:
            self._report_error("Nothing to paste: copy a patch first")
            return
        if self._can_write and not self._ask(
                "Paste patch", f"Write '{self._clipboard.name}' to patch {self._display(location)}?\n"
                               "The slot's previous content is backed up first."):
            return
        self._apply({location: copy.deepcopy(self._clipboard)}, "Paste patch")

    def swap_patches(self, a: int, b: int) -> None:
        if a == b or self._saving:
            return
        pa, pb = self._content(a), self._content(b)
        if not self._ask("Swap patches",
                         f"Swap patch {self._display(a)} ({pa.name or 'empty'}) with patch "
                         f"{self._display(b)} ({pb.name or 'empty'})?"
                         + ("\nBoth slots are written to the pedal, each backed up first." if self._can_write
                            else "\nThe change stays in memory until you write it to the pedal.")):
            return
        self._apply({a: pb, b: pa}, "Swap patches")

    def clear_slot(self, location: int) -> None:
        if self._saving:
            return
        if self._can_write and not self._ask(
                "Clear slot", f"Write the factory Empty patch to patch {self._display(location)}?\n"
                              "The slot's previous content is backed up first."):
            return
        self._apply({location: library.empty_patch()}, "Clear slot")

    # ---------------------------------------------------------- export/import

    def _choose_export_selected(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export patch to folder", str(Path.home()))
        if folder:
            self.export_selected(Path(folder))

    def _choose_export_all(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export all patches to folder", str(Path.home()))
        if folder:
            self.export_all(Path(folder))

    def _choose_import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import patch file", str(Path.home()), "Zoom patch (*.zptc)")
        if path:
            self.import_file(Path(path))

    def _choose_import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Import backup folder", str(Path.home()))
        if folder:
            self.import_folder(Path(folder))

    def export_selected(self, folder: Path, location: int | None = None) -> Path | None:
        location = self._location if location is None else location
        patch = self._patches.get(location) if location is not None else None
        if patch is None:
            self._report_error("Select a patch to export")
            return None
        try:
            path = library.export_one(folder, location, patch)
        except FileExistsError as exc:
            self._report_error(f"Not exported, the file already exists: {exc.filename}")
            return None
        except (ValueError, OSError) as exc:
            self._report_error(f"Cannot export: {exc}")
            return None
        self.statusBar().showMessage(f"Exported {path}")
        return path

    def export_all(self, folder: Path) -> Path | None:
        if not self._patches:
            self._report_error("No patches to export")
            return None
        try:
            dest = library.export_patches(folder, self._patches)
        except FileExistsError as exc:
            self._report_error(f"Not exported, the folder already exists: {exc.filename}")
            return None
        except (ValueError, OSError) as exc:
            self._report_error(f"Cannot export: {exc}")
            return None
        self.statusBar().showMessage(f"Exported {len(self._patches)} patches to {dest}")
        return dest

    def import_file(self, path: Path, location: int | None = None) -> None:
        location = self._location if location is None else location
        if location is None:
            self._report_error("Select a slot to import the file into")
            return
        try:
            loaded = parse_zptc(Path(path).read_bytes())
        except (ValueError, OSError) as exc:
            self._report_error(f"Cannot import {path}: {exc}")
            return
        if not self._ask("Import patch",
                         f"Replace patch {self._display(location)} with '{loaded.name}' from {Path(path).name}?"
                         + ("\nIt is written to the pedal, the slot backed up first." if self._can_write
                            else "\nThe change stays in memory until you write it to the pedal.")):
            return
        self._apply({location: edit.with_fillers(loaded, self.catalog)}, "Import file")

    def import_folder(self, folder: Path) -> None:
        folder = Path(folder)
        if not folder.is_dir():
            self._report_error(f"Not a folder: {folder}")
            return
        found, problems = library.read_folder(folder)
        usable = {loc: p for loc, p in found.items() if 1 <= loc <= self._patch_count}
        skipped = sorted(set(found) - set(usable))
        if skipped:
            problems.append("outside the pedal's slots: " + ", ".join(str(n) for n in skipped))
        if problems:
            self._report_error("; ".join(problems[:3]))
        if not usable:
            self._report_error(f"No patches to import in {folder}")
            return
        first, last = min(usable), max(usable)
        if not self._ask("Import folder",
                         f"Import {len(usable)} patch(es) into slots {self._display(first)}-{self._display(last)}"
                         f" from {folder.name}?"
                         + ("\nThey are written to the pedal one by one, each slot backed up first."
                            if self._can_write else "\nThe changes stay in memory until you write them.")):
            return
        self._apply({loc: edit.with_fillers(p, self.catalog) for loc, p in usable.items()}, "Import folder")

    def write_all_dirty(self) -> None:
        if self._saving:
            return
        if not self._can_write:
            self._report_error("Connect to the pedal to write")
            return
        dirty = {loc: copy.deepcopy(self._patches[loc]) for loc in sorted(self._stacks)
                 if self.is_dirty(loc) and loc in self._patches}
        if not dirty:
            self.statusBar().showMessage("No unsaved patches")
            return
        blocked = self._blockers(dirty)
        if blocked:
            self._report_error("Nothing written, fix these first: " + self._describe_blockers(blocked))
            return
        if not self._ask("Write to pedal",
                         f"Write {len(dirty)} changed patch(es) "
                         f"({', '.join(str(self._display(n)) for n in dirty)}) to the pedal?\n"
                         "Each slot is backed up first; the queue stops at the first failure."):
            return
        self._queue_write(dirty)

    # ------------------------------------------------------------ backup all

    def backup_all(self, with_files: bool = False, stamp: str | None = None) -> None:
        if not self._can_write:
            self._report_error("Connect to the pedal to back it up")
            return
        if self._saving:
            return
        if self.library_dir is None:
            self._report_error("No patches folder configured for backups")
            return
        self._set_saving(True)
        self.task_bar.setRange(0, 0)
        self.task_bar.show()
        self.task_cancel.show()
        self.statusBar().showMessage("Backing up the pedal...")
        self._backup_requested.emit(self.library_dir, with_files, stamp)

    def _cancel_task(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.statusBar().showMessage("Cancelling...")

    def _on_backup_progress(self, phase: str, done: int, total: int) -> None:
        self.task_bar.setRange(0, max(1, total))
        self.task_bar.setValue(done)
        self.task_bar.setFormat(f"{phase} %v/%m")

    def _on_backup_done(self, folder: str, ok: bool) -> None:
        self.task_bar.hide()
        self.task_cancel.hide()
        self._set_saving(False)
        self.statusBar().showMessage(f"Backup saved to {folder}" if ok else
                                     f"Backup incomplete or cancelled{': ' + folder if folder else ''}")
        self.backup_finished.emit(folder, ok)

    def _on_queue_done(self, written: object, failed: int) -> None:
        self._set_saving(False)
        done = ", ".join(str(self._display(n)) for n in written)
        if not failed:
            self.statusBar().showMessage(f"Wrote and verified patch(es): {done or 'none'}")
        self.queue_finished.emit(list(written), failed)
