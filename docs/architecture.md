# Architecture

JMC Guitar Zoom is a PySide6 desktop application. The code is split in five packages under `jmc_guitar_zoom/`;
the dependencies point downwards (`ui` uses everything, `device` uses nothing else of the project).

```
ui  ->  library, effects, patches, device
library -> effects          effects -> device, patches          patches -> (upstream decoders only)
```

## Modules

| Package | Responsibility | Qt? |
|---|---|---|
| `device/` | `Transport` (the real `MidoTransport` and a `FakeTransport` for tests), `sysex.py` (pure functions that build requests and parse replies, 7-bit packing, CRC), `PedalClient` (request/reply matching, timeouts, typed errors, tuner events). | no |
| `patches/` | `Patch` / `EffectSlot` model, `zptc.py` (parse and build the 760-byte patch buffer), `edit.py` (replace, remove, move effects; wide-effect filler slots), `backup.py` (never-overwrite backups), `bank.py` (the app-side patch bank), `library.py` (backup folders). | no |
| `effects/` | `catalog.py` (reads `.zd2` effect files), `models.py` (Guitar Lab's `AllZDL7_2.lst`: which pedal runs which effect), `flst.py` (the install flag in `FLST_SEQ.ZT2`), `installer.py` (install, remove, repair), `i18n.py` and `descriptions_es.json` (Spanish texts). | no |
| `library/` | `updater.py`: checks Zoom's public Guitar Lab channel and downloads and verifies effects into the app's own library. | no |
| `ui/` | The main window and screens (editor, bank, effects manager, library updater), the chain and card widgets, the tuner, the theme (`design/`), `worker.py` (pedal I/O thread), `gc_guard.py`. | yes |

The container formats (`.zptc` patch, `.zd2` effect) are parsed with the `construct` definitions of the upstream
scripts at the repository root (`zoomzt2.py`, `decode_preset.py`), imported and never modified. Everything the
application does on top of them is in `jmc_guitar_zoom/`.

## Threading model

- **GUI thread.** Everything that touches a widget. Qt objects are never used from another thread.
- **Pedal worker.** `PedalWorker` (in `ui/worker.py`) owns the `PedalClient` and does all pedal I/O: connect, read
  and write patches, file operations, the tuner. It lives on its own `QThread`. The window calls it with queued
  signals or `PedalWorker.request`, and it answers with signals; every failure becomes an `error` signal. Only one
  request runs at a time (the client holds a lock), so a write can never interleave with a read.
- **Update worker.** The library updater (network and file work) runs on a second `QThread` and reports through
  signals. It never touches a widget; after a download the window reloads the catalog on the GUI thread.

### The GC guard

`ui/gc_guard.py` switches Python's automatic garbage collection off and runs `gc.collect()` from a `QTimer` that
lives on the GUI thread. The reason is a race inside Shiboken (PySide's binding layer): it releases the GIL while it
deletes the C++ side of a wrapper. If the GUI thread is half-way through destroying a widget tree and a worker
thread's allocations trigger a collection, the collector walks wrappers that are being destroyed and the process
crashes in `gc_collect_main -> visit_decref -> libshiboken6`. With collection only on the GUI thread, between
events, this cannot happen. Reference counting still frees everything that is not in a cycle at once. The test
suite installs the same guard for the whole session (`tests/ui/conftest.py`).

## Write-safety model

Writing to the pedal is the only irreversible thing the application does, so it is the most guarded:

1. **Model gate.** `MainWindow.write_block_reason()` returns why nothing may be written to the connected pedal. Only
   models in `effects.models.SUPPORTED_MODELS` (the A1 FOUR) are writable; for any other, or an unknown one, every
   write action (save, import, effects manager, bank) is disabled and says why.
2. **Backup first.** A patch write first reads the slot and stores its current content in the autosave folder
   (`patches/backup.py`; files are created exclusively, never overwritten). The effect list is backed up before it
   is changed.
3. **Write, then read back.** After writing, the data is read again and compared with what was sent; a difference
   is reported as an error, never ignored.
4. **Order that never leaves a dangling reference.** Installing an effect uploads the file before setting its flag
   in `FLST_SEQ.ZT2`; removing clears the flag before deleting the file. `FLST_SEQ.ZT2` is edited in place, one
   byte, never rebuilt.
5. **The bank never loses a patch.** Loading a patch into an occupied position moves the occupant to the bank
   first; the bank entry is removed only after the pedal's read-back matched. On any failure a duplicate stays in the
   bank. Deleting a bank entry moves it to a trash folder.
6. **Untrusted downloads.** The updater only talks to the Guitar Lab channel (https, fixed host, no redirects out of
   it, no `..`), limits sizes, reads a zip in memory, takes one `.ZD2`, parses it and requires the id the list
   announced and a version no older than the list's before publishing it atomically under a new name.

## Testing approach

- The suite is offscreen (`QT_QPA_PLATFORM=offscreen`) and needs no display, no MIDI port and no pedal. Tests never
  open a MIDI port and never write to a pedal: the pedal is a `FakeTransport` with scripted replies, and the
  pedal's file system is an in-memory store behind `PedalClient`'s file methods.
- Reply builders in `tests/device/device_replies.py` use upstream's own `pack()` and `binascii`, so the new
  protocol code is cross-checked against the upstream algorithm instead of against itself.
- The tests drive the UI through its public widgets (clicks, drops, key events) and assert every observable effect:
  the bytes sent, what was written, the files on disk, the messages.
- Fixtures are synthetic (`tests/support/`): effect files, the pedal's effect list, patches, artwork and the channel
  list are generated, so no Zoom-proprietary file is in the repository. Tests that compare against Zoom's real files
  carry the `zoom_files` marker, read the git-ignored `tests/.zoom-fixtures/` that
  `scripts/fetch_test_fixtures.py` fills, and are skipped without it.
- Real-hardware observations are kept as synthetic cases with a note saying what was observed (for example the
  single-byte install flag in `flst_factory.py`, the name padding in `patch_factory.py`).
