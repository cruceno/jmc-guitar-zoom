# Zoom A1 FOUR: protocol notes

What this application knows about talking to the pedal, verified on a real A1 FOUR (firmware 1.01) over USB MIDI.
The base of all of it is the reverse engineering done by the **[zoom-zt2](https://github.com/mungewell/zoom-zt2)**
project (SysEx framing, the 7-bit packing, the CRC, the file commands, the `.zptc`, `.zd2` and `FLST_SEQ.ZT2`
formats); this document records what was confirmed or added for the A1 FOUR. Code: `jmc_guitar_zoom/device/sysex.py`
(pure message builders and parsers) and `device/client.py`.

All SysEx payloads below are shown without the `F0`/`F7` framing and with every byte at most `0x7F`.

## Addressing and identity

- Header of every message: `52 00 6E` (manufacturer `52` = Zoom, device `00`, model `6E`).
- Identity: request `7E 7F 06 01` (Universal Identity Request); the reply is `7E dev 06 02 52 <family> <member>
  <version>`. The model byte is `6E`; the **member** byte is what tells the pedals apart: A1 FOUR = `0x11` (Guitar
  Lab calls the model `0x6E001100`), G5n = `0x00`, G1 FOUR = `0x0C`.
- Patch info request `44` -> reply `43`: number of patches, patch buffer size (760 bytes) and patches per bank.
  A location is 1-based; `bank, slot = divmod(location - 1, patches_per_bank)`.

## Modes

| Request | Meaning | Reply |
|---|---|---|
| `50` / `51` | editor mode on / off | `52 00 6E 00 00` |
| `52` / `53` | PC mode on / off | `52 00 6E 00 00` |

PC mode is needed for reading and writing patches and files; editor mode is needed for live edit and the tuner.
Leaving a mode is acknowledged the same way. Both acknowledgements are exactly `00 00` (any other reply is not an
acknowledgement).

## Reply map

Replies do **not** echo the request command:

| Request | Reply header |
|---|---|
| `50`, `51`, `52`, `53`, patch write `45` | `00 00` |
| patch info `44` | `43` |
| read patch `46` | `45` |
| read current patch `64 13` | `64 12` |
| file commands `60 xx` | `60 04 <xx>` for data replies, `60 03 00` for status replies |

Every `60` command is answered by exactly one `60` reply.

## Patches

- Read: `46 00 00 <bank lo hi> <slot lo hi>` (14-bit values split in two 7-bit bytes).
- Write: `45 00 00 <bank> <slot> <length 14 bit> <7-bit packed data> <CRC>`. The acknowledgement carries no
  verification of the content, so the application always reads the slot back and compares.
- Read the current (edit buffer) patch: `64 13` -> `64 12 ... <length> <packed data> <CRC>`.
- Data blocks are 7-bit packed: for each group of up to 7 data bytes, one byte with their high bits, then the 7 low
  halves. The CRC trailer is `crc32(data) XOR 0xFFFFFFFF` as five 7-bit bytes, little endian.
- Select a patch: Control Change 0 (bank high), Control Change 32 (bank low), then a Program Change.
- A patch is a 760-byte `.zptc` buffer. Two-slot ("wide") effects are followed by a filler slot (id `1`) in the
  stored chain; the editor works on the chain without them and puts them back when saving.

## Live edit (editor mode)

`64 03 00 <slot> <param> <value>` sets one parameter of the current patch; `value` is five 7-bit bytes, little
endian. The pedal does **not** acknowledge it.

Verified on a real A1 FOUR (firmware 1.01): `slot` is the index into the chain **with** the wide-effect filler
slots, exactly as the `.zptc` stores it, and `param` is `0` for the effect's on/off and the dial's index plus 2 for a
dial. Checked with a wide amp's Bass dial (slot 1, param 3), a reverb's first dial after two wide effects (slot 6,
param 2) and an equaliser's volume (slot 4, param 9): each changed exactly that value on the pedal.

Two special slots address the patch itself:

| Slot | Param | Meaning |
|---|---|---|
| `0x09` | 0..9 | character `n` of the patch name (ASCII) |
| `0x0A` | `0x00` | patch volume |

Both verified on a real A1 FOUR (firmware 1.01, 2026-11-25): the current-patch read (`64 13`) returned the new volume
and the new first character, and sending the old values back restored the patch byte for byte.

A parameter message cannot swap the effect in a slot, so swapping an effect is only possible by writing the patch.

## Tuner

In editor mode `64 0B` starts and `64 0C` stops the tuner; the pedal is muted while it is on. Readings are not
SysEx: they arrive as Control Changes.

- **CC 98**: the note, an index into `A, A#, B, C, C#, D, D#, E, F, F#, G, G#`; a value past the end means no note.
- **CC 99**: the deviation in cents, with an offset: `cents = value - 8`.

## Files

The pedal has a small file system (effects `NAME.ZD2`, `FLST_SEQ.ZT2`, rhythm samples, ...). File names are 8.3 ASCII,
at most 12 characters, no directories.

| Command | Meaning |
|---|---|
| `60 25 00 00 *\0` / `60 26 ...` | list: first, then next; a reply with `payload[4] != 4` ends the list; the name is a fixed 12-byte field at offsets 14-25, zero-padded (a 12-character name has no zero; byte 26 is not part of it) |
| `60 25 00 00 <name>\0` + `60 05 00` | does the file exist (status of 5 zero bytes = yes) |
| `60 20 02 <9 zeros> <name>\0` | open for reading; `60 22 ...` reads a block; data replies are `60 04 <xx>` |
| `60 24 <name>\0` | delete |
| `60 20 01 <9 zeros> <name>\0` | open for writing |
| `60 23 40 00 00 00 00 <len 14 bit> 00 00 00 <packed block> <CRC>` | one upload block (up to 512 bytes) |
| `60 21 40 00 00 00 00` then `60 09` | close (each gets one reply) |
| `60 29 00 00 00 00 00` | disk usage: maximum and available bytes, five 7-bit bytes each at offsets 10 and 15 |

**Upload sequence** (as zoom-zt2 does it): delete the old file, open for writing, a status request (`60 05 00`), then
each 512-byte block followed by a status request, then close. The status replies carry no success code, so an
upload is verified by reading the file back. **Delete** is the delete command followed by close.

**Memory.** Uploading 27,864 bytes used 28,630 bytes of the pedal's memory, so the application keeps a margin of one
block (4,096 bytes) on top of the file size before it allows an install.

## `FLST_SEQ.ZT2` and the install flag

The pedal's effect list. On the A1 FOUR (firmware 1.01) it is 14,784 bytes: two sections (two copies of the list),
each a run of groups framed by `>>>` / `<<<` records, and each starting with a `BYPASS.ZD2` record. A record is 26
bytes: the file name NUL-padded to 12, `00`, a 4-byte version, `00`, the **installed flag** (0 or 1), the effect id
(4 bytes, little endian; the top byte is the group) and `00 00 00`.

Installing an effect with Guitar Lab uploads the effect's `.ZD2` unchanged and changes **exactly one byte** of this
file: the flag of that effect's record in the **first** section (the second section already has it set). zoom-zt2's
rebuild of the file uses a fixed size and truncates the A1 FOUR's longer list, so this application only ever flips
that one byte in place, keeping the length, after backing the list up. A flag set without the file on the pedal
means the effect is "missing its file" (the manager can repair it by uploading the file again).

## `.ZD2` effect files

A `.ZD2` starts with `ZDLF`, a length and a checksum, then fixed header fields (version as ASCII like `1.40`, the
group, the effect id, the effect name and group name, 11 bytes each), then tagged chunks: `ICON`, `TXJ1`/`TXE1`
(Japanese and English description), `INFO` (the DSP load as a float; the editor shows it divided by 2.5, because
100 % of the chip is 250), `DATA` (the DSP image), and `PRME` (JSON with the parameters' names and explanations).
Parameter ranges and defaults are not in the container: they are a table of 56-byte records inside `DATA`
(`name(12) | max u32 | default u32 | padding`), `OnOff` first, then the effect's own name, then one record per
parameter; trailing `Dummy` records mean a wide (two-slot) effect. The pedal stores the file as `NAME.ZD2`; Guitar
Lab caches it as `NAME_VVV.zd2`. Zoom's channel serves each effect as `<NAME>.zip` containing the `.ZD2`, in
`archive/GUITAR_LAB/ZDLF7_2/` for the `AllZDL7_2.lst` list: Guitar Lab 7.3's cache matches those files byte for
byte. The list's own `zdl_url` field still names `ZDLF3/`, whose files date from 2019 and are older than the list
(Comp 1.30 against 1.40). A few files are newer than the list says (Gt GEQ 7: list 1.10, file 1.20), and Guitar Lab
caches them under the list's version.

## What does not work

- **Rhythm machine and looper.** Probed on hardware without success. In editor mode the pedal echoes tempo changes
  as `64 03 00 0A 02 <lo> <hi> 00 00 00`, and a patch change as CC 0, CC 32 and a Program Change, but starting or
  stopping the rhythm, changing patterns and every looper action were not echoed. Reading "screens" with
  `64 02 00 <n> 00` answers for n = 0..5 but only shows the patch slots. The zoom-zt2 messages for other models
  (`64 03 00 0A 01 <window>` to select a window, `0A 03 01` and `0A 04 01` for footswitches 1 and 2) are
  acknowledged by the A1 FOUR but had no visible effect: the rhythm did not start. The application therefore has no
  rhythm or looper control.
- **Settings** (system tempo, patch volume, autosave, ...). Documented by zoom-zt2 as system-setting messages for
  other models; reading and changing them on the A1 FOUR is deferred, not implemented.
- **Firmware** is neither downloaded nor written. The updater only compares the version the channel publishes with
  the one the pedal reports.
