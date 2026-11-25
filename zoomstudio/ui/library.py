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
from PySide6.QtWidgets import QFileDialog, QLabel, QProgressBar, QPushButton

from zoomstudio.patches import edit, library
from zoomstudio.patches.model import Patch
from zoomstudio.patches.zptc import build_zptc, parse_zptc

from . import strings as S
from .dialogs import ConfirmDialog
from .glass import GlassMenu
from .icons import icon


class LibraryMixin:
    """Mixed into ``MainWindow``; relies on its patch store, worker and signals."""

    def open_effects_screen(self) -> None:
        """The effects screen through the top-bar toggle, so every way in leaves the same state."""
        if self.effects_button.isEnabled():
            self.effects_button.setChecked(True)

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

        self.copy_action = action(S.COPY_PATCH, lambda: self._with_selected(self.copy_patch), "Ctrl+C")
        self.paste_action = action(S.PASTE_PATCH, lambda: self._with_selected(self.paste_patch), "Ctrl+V")
        self.clear_action = action(S.CLEAR_SLOT, lambda: self._with_selected(self.clear_slot), "Delete",
                                   S.CLEAR_SLOT_TIP)
        self.backup_action = action(S.BACKUP_ALL, lambda: self.backup_all(False))
        self.backup_files_action = action(S.BACKUP_FILES, lambda: self.backup_all(True))
        self.write_dirty_action = action(S.WRITE_DIRTY, self.write_all_dirty)
        self.export_selected_action = action(S.EXPORT_SELECTED, self._choose_export_selected)
        self.export_all_action = action(S.EXPORT_ALL, self._choose_export_all)
        self.import_file_action = action(S.IMPORT_FILE, self._choose_import_file)
        self.import_folder_action = action(S.IMPORT_FOLDER, self._choose_import_folder)

        for act in (self.copy_action, self.paste_action, self.clear_action):
            self.patch_list.addAction(act)  # shortcuts act only while the patch list has focus
        self.effects_action = action(S.LIBRARY_EFFECTS, self.open_effects_screen)
        self.effects_action.setIcon(icon("package"))
        menu = GlassMenu(self.library_button, self.backdrop_root)
        self.library_button.setMenu(menu)
        for act in (self.effects_action, None, self.backup_action, self.backup_files_action, None, self.copy_action, self.paste_action,
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
        self.task_bar.setTextVisible(False)  # the phase and count are a label: text over a 6 px bar cannot be read
        self.task_label = QLabel("")
        self.task_label.setProperty("role", "secondary")
        self.task_label.hide()
        self.task_cancel = QPushButton(S.CANCEL)
        self.task_cancel.clicked.connect(self._cancel_task)
        self.task_bar.hide()
        self.task_cancel.hide()
        self.statusBar().addPermanentWidget(self.task_label)
        self.statusBar().addPermanentWidget(self.task_bar)
        self.statusBar().addPermanentWidget(self.task_cancel)

    def _update_library_actions(self) -> None:
        idle = not self._saving
        connected = self._is_connected and self._worker is not None
        has_patch = self.current_patch is not None
        self.backup_action.setEnabled(connected and idle)
        self.backup_files_action.setEnabled(connected and idle)
        self.write_dirty_action.setEnabled(connected and idle and self.any_dirty())
        dirty = sum(1 for loc in self._stacks if self.is_dirty(loc))
        self.write_dirty_action.setText(S.write_dirty(dirty))
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
        menu = GlassMenu(self, self.backdrop_root)
        for act in (self.copy_action, self.paste_action, self.clear_action, None, self.export_selected_action,
                    self.import_file_action):
            if act is None:
                menu.addSeparator()
            else:
                menu.addAction(act)
        menu.exec(self.patch_list.viewport().mapToGlobal(pos))

    def _with_selected(self, operation) -> None:
        if self._location is None:
            self.statusBar().showMessage(S.SELECT_PATCH_FIRST)
            return
        operation(self._location)

    def _ask(self, title: str, text: str) -> bool:
        return ConfirmDialog.ask(self, title, text, S.CONFIRM)

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
        return "; ".join(S.blocker(self._display(loc), why[0]) for loc, why in sorted(blocked.items()))

    def _apply(self, changes: dict[int, Patch], text: str) -> None:
        """Connected: write through the safe queue. Offline (or blocked): stage as dirty edits."""
        if not self._can_write:
            self._stage(changes, text)
            return
        blocked = self._blockers(changes)
        if blocked:
            self._stage(changes, text)
            self._report_error(S.err_not_written_fix(self._describe_blockers(blocked)))
            return
        self._queue_write({loc: changes[loc] for loc in changes})

    def _queue_write(self, patches: dict[int, Patch]) -> bool:
        if self.backup_dir is None:
            self._report_error(S.ERR_NO_BACKUP_DIR)
            return False
        try:
            items = [(loc, build_zptc(edit.sent_form(patches[loc]))) for loc in sorted(patches)]
        except ValueError as exc:
            self._report_error(S.build_failed(exc))
            return False
        self._set_saving(True)
        self.statusBar().showMessage(S.writing_patches(len(items)))
        self._queue_requested.emit(items, self.backup_dir)
        return True

    # ------------------------------------------------------ patch operations

    def copy_patch(self, location: int) -> None:
        patch = self._patches.get(location)
        if patch is None:
            self._report_error(S.err_nothing_to_copy(self._display(location)))
            return
        self._clipboard = copy.deepcopy(patch)
        self.statusBar().showMessage(S.copied(self._display(location), patch.name))
        self._update_buttons()

    def paste_patch(self, location: int) -> None:
        if self._saving:
            return
        if self._clipboard is None:
            self._report_error(S.ERR_NOTHING_TO_PASTE)
            return
        if self._can_write and not self._ask(
                S.PASTE_TITLE, S.ask_paste(self._clipboard.name, self._display(location))):
            return
        self._apply({location: copy.deepcopy(self._clipboard)}, S.UNDO_PASTE)

    def swap_patches(self, a: int, b: int) -> None:
        if a == b or self._saving:
            return
        pa, pb = self._content(a), self._content(b)
        if not self._ask(S.SWAP_TITLE, S.ask_swap(self._display(a), pa.name, self._display(b), pb.name,
                                                  self._can_write)):
            return
        self._apply({a: pb, b: pa}, S.UNDO_SWAP)

    def clear_slot(self, location: int) -> None:
        if self._saving:
            return
        if self._can_write and not self._ask(
                S.CLEAR_TITLE, S.ask_clear(self._display(location))):
            return
        self._apply({location: library.empty_patch()}, S.UNDO_CLEAR)

    # ---------------------------------------------------------- export/import

    def _choose_export_selected(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, S.EXPORT_SELECTED_TITLE, str(Path.home()))
        if folder:
            self.export_selected(Path(folder))

    def _choose_export_all(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, S.EXPORT_ALL_TITLE, str(Path.home()))
        if folder:
            self.export_all(Path(folder))

    def _choose_import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, S.IMPORT_FILE_TITLE, str(Path.home()), S.PATCH_FILTER)
        if path:
            self.import_file(Path(path))

    def _choose_import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, S.IMPORT_FOLDER_TITLE, str(Path.home()))
        if folder:
            self.import_folder(Path(folder))

    def export_selected(self, folder: Path, location: int | None = None) -> Path | None:
        location = self._location if location is None else location
        patch = self._patches.get(location) if location is not None else None
        if patch is None:
            self._report_error(S.ERR_SELECT_TO_EXPORT)
            return None
        try:
            path = library.export_one(folder, location, patch)
        except FileExistsError as exc:
            self._report_error(S.err_not_exported_file(exc.filename))
            return None
        except (ValueError, OSError) as exc:
            self._report_error(S.err_cannot_export(exc))
            return None
        self.statusBar().showMessage(S.exported(path))
        return path

    def export_all(self, folder: Path) -> Path | None:
        if not self._patches:
            self._report_error(S.ERR_NO_PATCHES_TO_EXPORT)
            return None
        try:
            dest = library.export_patches(folder, self._patches)
        except FileExistsError as exc:
            self._report_error(S.err_not_exported_folder(exc.filename))
            return None
        except (ValueError, OSError) as exc:
            self._report_error(S.err_cannot_export(exc))
            return None
        self.statusBar().showMessage(S.exported_all(len(self._patches), dest))
        return dest

    def import_file(self, path: Path, location: int | None = None) -> None:
        location = self._location if location is None else location
        if location is None:
            self._report_error(S.ERR_SELECT_SLOT_TO_IMPORT)
            return
        try:
            loaded = parse_zptc(Path(path).read_bytes())
        except (ValueError, OSError) as exc:
            self._report_error(S.err_cannot_import(path, exc))
            return
        if not self._ask(S.IMPORT_TITLE, S.ask_import(self._display(location), loaded.name, Path(path).name,
                                                      self._can_write)):
            return
        self._apply({location: edit.with_fillers(loaded, self.catalog)}, S.UNDO_IMPORT_FILE)

    def import_folder(self, folder: Path) -> None:
        folder = Path(folder)
        if not folder.is_dir():
            self._report_error(S.not_a_folder(folder))
            return
        found, problems = library.read_folder(folder)
        usable = {loc: p for loc, p in found.items() if 1 <= loc <= self._patch_count}
        skipped = sorted(set(found) - set(usable))
        if skipped:
            problems.append(S.err_outside_slots(", ".join(str(n) for n in skipped)))
        if problems:
            self._report_error("; ".join(problems[:3]))
        if not usable:
            self._report_error(S.err_no_patches_in(folder))
            return
        first, last = min(usable), max(usable)
        if not self._ask(S.IMPORT_FOLDER_ASK_TITLE, S.ask_import_folder(
                len(usable), self._display(first), self._display(last), folder.name, self._can_write)):
            return
        self._apply({loc: edit.with_fillers(p, self.catalog) for loc, p in usable.items()}, S.UNDO_IMPORT_FOLDER)

    def write_all_dirty(self) -> None:
        if self._saving:
            return
        if not self._can_write:
            self._report_error(S.ERR_CONNECT_TO_WRITE)
            return
        dirty = {loc: copy.deepcopy(self._patches[loc]) for loc in sorted(self._stacks)
                 if self.is_dirty(loc) and loc in self._patches}
        if not dirty:
            self.statusBar().showMessage(S.NO_UNSAVED_PATCHES)
            return
        blocked = self._blockers(dirty)
        if blocked:
            self._report_error(S.err_nothing_written_fix(self._describe_blockers(blocked)))
            return
        if not self._ask(S.WRITE_TITLE, S.ask_write_dirty(len(dirty), ", ".join(str(self._display(n)) for n in dirty))):
            return
        self._queue_write(dirty)

    # ------------------------------------------------------------ backup all

    def backup_all(self, with_files: bool = False, stamp: str | None = None) -> None:
        if not self._can_write:
            self._report_error(S.ERR_CONNECT_TO_BACKUP)
            return
        if self._saving:
            return
        if self.library_dir is None:
            self._report_error(S.ERR_NO_LIBRARY_DIR)
            return
        self._set_saving(True)
        self.task_bar.setRange(0, 0)
        self.task_bar.show()
        self.task_cancel.show()
        self.statusBar().showMessage(S.BACKING_UP)
        self._backup_requested.emit(self.library_dir, with_files, stamp)

    def _cancel_task(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.statusBar().showMessage(S.CANCELLING)

    def _on_backup_progress(self, phase: str, done: int, total: int) -> None:
        self.task_bar.setRange(0, max(1, total))
        self.task_bar.setValue(done)
        self.task_bar.setFormat(f"{phase} %v/%m")
        self.task_label.setText(f"{phase} {done}/{total}")
        self.task_label.show()

    def _on_backup_done(self, folder: str, ok: bool) -> None:
        self.task_bar.hide()
        self.task_label.hide()
        self.task_cancel.hide()
        self._set_saving(False)
        self.statusBar().showMessage(S.backup_saved(folder) if ok else S.backup_incomplete(folder))
        self.backup_finished.emit(folder, ok)

    def _on_queue_done(self, written: object, failed: int) -> None:
        self._set_saving(False)
        done = ", ".join(str(self._display(n)) for n in written)
        if not failed:
            self.statusBar().showMessage(S.wrote_and_verified(done))
        self.queue_finished.emit(list(written), failed)
