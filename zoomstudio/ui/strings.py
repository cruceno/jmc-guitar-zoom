"""Every text the user reads, in neutral Spanish (no voseo).

Not translated on purpose: effect and parameter names (they come from the pedal's catalog), the term
"patch" and patch names, "slot", "DSP", "A1 FOUR". Wording written by ui-developer for messages the
prototype does not show; review it here, in one place.
"""

from __future__ import annotations

from PySide6.QtCore import QLocale

_ES = QLocale(QLocale.Language.Spanish)

# ----------------------------------------------------------------- numbers and groups

GROUP_NAMES = {
    "DYNAMICS": "Dinámica", "FILTER": "Filtro", "DRIVE": "Saturación", "AMP": "Amplificador",
    "PREAMP": "Preamplificador", "BASS AMP": "Amplificador de bajo", "CABINET": "Gabinete",
    "AG MODEL": "Modelo AG", "MODULATION": "Modulación", "SFX": "SFX", "DELAY": "Delay",
    "REVERB": "Reverb", "PEDAL": "Pedal",
}
ALL_GROUPS = "Todos los grupos"


def group_label(group: str) -> str:
    """Group name as shown; the internal catalog key never changes."""
    return GROUP_NAMES.get(group.upper(), group.title())


def number(value: float, decimals: int = 1) -> str:
    return _ES.toString(float(value), "f", decimals)


def percent(value: float, decimals: int = 1) -> str:
    return f"{number(value, decimals)} %"


def slots_label(count: int) -> str:
    return "1 slot" if count == 1 else f"{count} slots"


# ----------------------------------------------------------------- window

NOT_CONNECTED = "Sin conexión"
READY = "Listo"
MEMORY_NA = "Memoria: n/d"
DSP_NA = "DSP: n/d"
MEMORY_LABEL = "Memoria"
DSP_LABEL = "DSP"
NOT_AVAILABLE = "n/d"
CHAIN_TITLE = "Cadena"
PATCH_EMPTY_NAME = "Patch vacío"
EDIT_MENU = "&Editar"
LIBRARY_MENU = "&Biblioteca"
UNDO = "Deshacer"
REDO = "Rehacer"
CONNECT = "Conectar"
DISCONNECT = "Desconectar"
OPEN_FOLDER = "Abrir carpeta…"
RELOAD = "Recargar"
OPEN_FILE = "Abrir archivo…"
SAVE_FILE = "Guardar como archivo…"
SAVE_TO_PEDAL = "Guardar en la pedalera"
TUNER = "Afinador"
SWITCH_ON = "SÍ"
SWITCH_OFF = "NO"
LIVE = "En vivo"
CANCEL = "Cancelar"
CONFIRM = "Confirmar"
TUNER_TIP = "Enciende o apaga el afinador de la pedalera (T). La pedalera queda muda mientras está encendido"
LIVE_TIP = "Envía también a la pedalera los cambios de parámetros y de encendido mientras se edita"
PATCHES = "Patches"
NO_PATCH_SELECTED = "Ningún patch seleccionado"
NAME = "Nombre"
VOLUME = "Volumen"
VOLUME_TIP = "Volumen del patch"
UNNAMED = "(sin nombre)"
UNSAVED_CHANGES = "Cambios sin guardar"
EDITED = "Editado"
EMPTY = "Vacío"


def offline(folder: str) -> str:
    return f"{NOT_CONNECTED} · carpeta {folder}"


def connected(model: str) -> str:
    return f"Conectado · {model}"


def firmware_tip(firmware: str) -> str:
    return f"Firmware {firmware}"


def memory_text(used_kb: float, max_kb: float, pct: float) -> str:
    return f"Memoria: {used_kb:.0f} / {max_kb:.0f} KB ({pct:.0f} %)"


def name_tip(limit: int) -> str:
    return f"Nombre del patch: hasta {limit} caracteres ASCII imprimibles"


def dsp_value(dsp: float) -> str:
    """The value written beside the DSP bar («69 %»; over 100 % it says why the bar is red)."""
    return f"{dsp:.0f} %" + (" · sobre el límite" if dsp > 100 else "")


def patches_caption(in_use: int, first: int = 10, last: int = 59) -> str:
    return f"{first}–{last} · {in_use} en uso"


def chain_caption(effects: int, slots: int) -> str:
    noun = "efecto" if effects == 1 else "efectos"
    return f"{effects} {noun} · {slots} slots · ←/→ elegir · Ctrl+←/→ o arrastrar para reordenar"


def dsp_text(dsp: float) -> str:
    return f"DSP: {dsp:.0f} %" + ("  (sobre el límite)" if dsp > 100 else "")


def patch_title(display: int, name: str, volume: int) -> str:
    return f"{display}  {name}  (volumen {volume})"


def empty_patch_title(display: int) -> str:
    return f"{display}  -  vacío"


def unknown_model(code: int) -> str:
    return f"modelo 0x{code:02X}"


# ----------------------------------------------------------------- save to pedal

SAVE_NEEDS_CONNECTION = "Conecte la pedalera para guardar"
SAVE_NO_EDITS = "No hay cambios sin guardar en este patch"
SAVE_TIP = "Hace backup del slot, escribe este patch y lo vuelve a leer para verificarlo"
ERR_NO_BACKUP_DIR = "No hay carpeta de copias de seguridad configurada: no se escribe en la pedalera"
ERR_NOT_CONNECTED = "No hay conexión con la pedalera"
SELECT_PATCH_TO_EDIT = "Seleccione un patch para editar"
SELECT_PATCH_FIRST = "Seleccione un patch primero"
SELECT_PEDAL_TO_REPLACE = "Seleccione primero el pedal que se reemplaza"
EMPTY_SLOT_HINT = "Slot vacío: elija un efecto del catálogo (botón, Enter o doble clic) o suéltelo aquí"
CONNECTING = "Conectando…"
DISCONNECTED = "Desconectado"
READING_PATCHES = "Leyendo patches…"
CANCELLING = "Cancelando…"


def cannot_save(reasons: list[str]) -> str:
    return "No se puede guardar: " + "; ".join(reasons)


def saving(display: int) -> str:
    return f"Guardando el patch {display}…"


def saved(display: int, backup: str) -> str:
    return f"Patch {display} guardado (contenido anterior: {backup})"


def build_failed(exc: object) -> str:
    return f"No se pudo armar el patch: {exc}"


def error(message: str) -> str:
    return f"Error: {message}"


def reading_progress(done: int, total: int) -> str:
    return f"Leyendo patches {done}/{total}"


def loaded_from_pedal(count: int) -> str:
    return f"Se cargaron {count} patches desde la pedalera"


def loaded_from_folder(count: int, folder: object) -> str:
    return f"Se cargaron {count} patches desde {folder}"


def not_a_folder(folder: object) -> str:
    return f"No es una carpeta: {folder}"


# ----------------------------------------------------------------- undo texts

UNDO_RENAME = "Renombrar patch"
UNDO_VOLUME = "Cambiar volumen"
UNDO_PARAM = "Cambiar parámetro"
UNDO_REPLACE = "Reemplazar efecto"
UNDO_REMOVE = "Quitar efecto"
UNDO_MOVE = "Mover efecto"
UNDO_OPEN_FILE = "Abrir archivo"
UNDO_PASTE = "Pegar patch"
UNDO_SWAP = "Intercambiar patches"
UNDO_CLEAR = "Vaciar slot"
UNDO_IMPORT_FILE = "Importar archivo"
UNDO_IMPORT_FOLDER = "Importar carpeta"


def undo_power(on: bool) -> str:
    return "Encender efecto" if on else "Apagar efecto"


def not_runnable(name: str) -> str:
    return f"{name} no funciona en la A1 FOUR"


# ----------------------------------------------------------------- files and dialogs

SAVE_PATCH_FILE = "Guardar patch como archivo"
OPEN_PATCH_FILE = "Abrir archivo de patch"
PATCH_FILTER = "Patch de Zoom (*.zptc)"
OPEN_BACKUP_FOLDER = "Abrir carpeta de copia de seguridad"
SELECT_PATCH_TO_SAVE = "Seleccione un patch para guardar"
SELECT_LOCATION_FOR_FILE = "Seleccione una ubicación donde abrir el archivo"
NOTHING_TO_RELOAD = "No hay nada que recargar: conecte la pedalera o abra una carpeta"
DISCARD_TITLE = "¿Descartar los cambios sin guardar?"
DISCARD_ACCEPT = "Descartar cambios"
DISCARD_OPEN_FOLDER = "Abrir otra carpeta"
DISCARD_RELOAD = "Recargar"
DISCARD_CONNECT = "Conectar (se vuelven a leer todos los patches de la pedalera)"
DISCARD_CLOSE = "Cerrar"


def discard_text(count: int, action: str) -> str:
    return f"{count} patches tienen cambios sin guardar.\n{action} descartará esos cambios."


def saved_file(path: object) -> str:
    return f"Se guardó {path}"


def cannot_save_file(path: object, exc: object) -> str:
    return f"No se pudo guardar {path}: {exc}"


def cannot_open_file(path: object, exc: object) -> str:
    return f"No se pudo abrir {path}: {exc}"


def patch_not_writable(reasons: list[str]) -> str:
    return "Este patch no se puede escribir en la pedalera tal como está: " + "; ".join(reasons)


def opened_into(name: str, display: int) -> str:
    return f"Se abrió {name} en {display}"


# ----------------------------------------------------------------- library

COPY_PATCH = "Copiar patch"
PASTE_PATCH = "Pegar patch"
CLEAR_SLOT = "Vaciar slot"
CLEAR_SLOT_TIP = "Escribe el patch Empty de fábrica en el slot"
BACKUP_ALL = "Copia de seguridad de todos los patches"
BACKUP_FILES = "Copia de seguridad de patches y archivos de la pedalera"
WRITE_DIRTY = "Escribir en la pedalera todo lo editado"
EDIT_MENU_NOTE = "Cada patch guarda su propio historial."


def write_dirty(count: int) -> str:
    """Menu text of the write-everything action, with how many patches it would write."""
    return f"{WRITE_DIRTY} ({count})" if count else WRITE_DIRTY
EXPORT_SELECTED = "Exportar patch seleccionado…"
EXPORT_ALL = "Exportar todos los patches…"
IMPORT_FILE = "Importar archivo de patch en el slot seleccionado…"
IMPORT_FOLDER = "Importar carpeta de copia de seguridad…"
EXPORT_SELECTED_TITLE = "Exportar patch a una carpeta"
EXPORT_ALL_TITLE = "Exportar todos los patches a una carpeta"
IMPORT_FILE_TITLE = "Importar archivo de patch"
IMPORT_FOLDER_TITLE = "Importar carpeta de copia de seguridad"
ERR_NOTHING_TO_PASTE = "No hay nada que pegar: copie un patch primero"
ERR_SELECT_TO_EXPORT = "Seleccione un patch para exportar"
ERR_NO_PATCHES_TO_EXPORT = "No hay patches para exportar"
ERR_SELECT_SLOT_TO_IMPORT = "Seleccione un slot donde importar el archivo"
ERR_CONNECT_TO_WRITE = "Conecte la pedalera para escribir"
ERR_CONNECT_TO_BACKUP = "Conecte la pedalera para hacer la copia de seguridad"
ERR_NO_LIBRARY_DIR = "No hay carpeta de patches configurada para las copias de seguridad"
NO_UNSAVED_PATCHES = "No hay patches sin guardar"
BACKING_UP = "Haciendo la copia de seguridad de la pedalera…"
PASTE_TITLE = "Pegar patch"
SWAP_TITLE = "Intercambiar patches"
CLEAR_TITLE = "Vaciar slot"
IMPORT_TITLE = "Importar patch"
IMPORT_FOLDER_ASK_TITLE = "Importar carpeta"
WRITE_TITLE = "Escribir en la pedalera"


def err_nothing_to_copy(display: int) -> str:
    return f"El patch {display} está vacío: no hay nada que copiar"


def copied(display: int, name: str) -> str:
    return f"Se copió el patch {display} ({name})"


def ask_paste(name: str, display: int) -> str:
    return f"¿Escribir '{name}' en el patch {display}?\nEl contenido anterior del slot se respalda antes."


def ask_swap(a: int, name_a: str, b: int, name_b: str, can_write: bool) -> str:
    tail = ("\nAmbos slots se escriben en la pedalera, cada uno con su copia de seguridad previa." if can_write
            else "\nEl cambio queda en memoria hasta que se escriba en la pedalera.")
    return f"¿Intercambiar el patch {a} ({name_a or 'vacío'}) con el patch {b} ({name_b or 'vacío'})?" + tail


def ask_clear(display: int) -> str:
    return f"¿Escribir el patch Empty de fábrica en el patch {display}?\nEl contenido anterior del slot se respalda antes."


def ask_import(display: int, name: str, filename: str, can_write: bool) -> str:
    tail = ("\nSe escribe en la pedalera, con copia de seguridad previa del slot." if can_write
            else "\nEl cambio queda en memoria hasta que se escriba en la pedalera.")
    return f"¿Reemplazar el patch {display} por '{name}' del archivo {filename}?" + tail


def ask_import_folder(count: int, first: int, last: int, folder: str, can_write: bool) -> str:
    tail = ("\nSe escriben en la pedalera de a uno, cada slot con su copia de seguridad previa." if can_write
            else "\nLos cambios quedan en memoria hasta que se escriban.")
    return f"¿Importar {count} patches en los slots {first}-{last} desde {folder}?" + tail


def ask_write_dirty(count: int, displays: str) -> str:
    return (f"¿Escribir en la pedalera {count} patches modificados ({displays})?\n"
            "Cada slot se respalda antes; la cola se detiene en el primer fallo.")


def err_not_written_fix(described: str) -> str:
    return "No se escribió en la pedalera, corrija esto primero: " + described


def err_nothing_written_fix(described: str) -> str:
    return "No se escribió nada, corrija esto primero: " + described


def blocker(display: int, why: str) -> str:
    return f"patch {display}: {why}"


def writing_patches(count: int) -> str:
    return f"Escribiendo {count} patches en la pedalera…"


def err_not_exported_file(name: object) -> str:
    return f"No se exportó, el archivo ya existe: {name}"


def err_not_exported_folder(name: object) -> str:
    return f"No se exportó, la carpeta ya existe: {name}"


def err_cannot_export(exc: object) -> str:
    return f"No se pudo exportar: {exc}"


def exported(path: object) -> str:
    return f"Se exportó {path}"


def exported_all(count: int, dest: object) -> str:
    return f"Se exportaron {count} patches a {dest}"


def err_cannot_import(path: object, exc: object) -> str:
    return f"No se pudo importar {path}: {exc}"


def err_outside_slots(slots: str) -> str:
    return "fuera de los slots de la pedalera: " + slots


def err_no_patches_in(folder: object) -> str:
    return f"No hay patches para importar en {folder}"


def backup_saved(folder: str) -> str:
    return f"Copia de seguridad guardada en {folder}"


def backup_incomplete(folder: str) -> str:
    return "Copia de seguridad incompleta o cancelada" + (f": {folder}" if folder else "")


def wrote_and_verified(done: str) -> str:
    return f"Se escribieron y verificaron los patches: {done or 'ninguno'}"


# ----------------------------------------------------------------- worker

ERR_BACKUP_ABORTED = "Copia de seguridad abortada tras 3 fallos de lectura seguidos"
ERR_NO_REPLY = "La pedalera no respondió a tiempo"
ERR_BAD_REPLY = "La pedalera envió una respuesta inválida"
ERR_READBACK_DIFFERS = "difiere de lo enviado"
CANCELLED = "cancelado"
NONE_WRITTEN = "ninguno"


def err_patch(display: int, exc: object) -> str:
    return f"Patch {display}: {exc}"


def err_pc_mode_off(exc: object) -> str:
    return f"No se pudo salir limpiamente del modo PC: {exc}"


def err_pc_mode_switch(exc: object) -> str:
    return f"No se pudo cambiar limpiamente el modo PC: {exc}"


def err_readback_invalid(display: int, exc: object) -> str:
    return f"La lectura de verificación del patch {display} no es válida: {exc}"


def err_readback_differs(display: int, diffs: list[str]) -> str:
    return f"La lectura de verificación del patch {display} {ERR_READBACK_DIFFERS}: " + "; ".join(diffs[:4])


def err_queue_stopped(display: int, why: str, done: str) -> str:
    return f"Patch {display}: {why}. Cola detenida; slots escritos: {done}"


def err_backup_folder_exists(stamp: str) -> str:
    return f"La carpeta backup-{stamp} ya existe: no se escribió nada"


def err_files_folder_exists(stamp: str) -> str:
    return f"La carpeta pedal-files-{stamp} ya existe: no se guardaron los archivos de la pedalera"


def err_file(name: str, exc: object) -> str:
    return f"Archivo {name}: {exc}"


def with_detail(message: str, exc: object) -> str:
    """A Spanish sentence followed by the (English, technical) detail of a low-level error."""
    return f"{message} ({exc})"


# ----------------------------------------------------------------- chain, parameters, catalog

PEDAL_EMPTY = "Vacío"
PEDAL_EMPTY_TARGET = "Destino del catálogo"
PEDAL_EMPTY_ADD = "Agregar desde el catálogo"
TILE_PROBLEM = "No funciona en la A1 FOUR"
REMOVE_EFFECT = "Quitar este efecto"
SLOT_EMPTY_TIP = "Slot vacío"
POWER_ON = "Encendido"
POWER_OFF = "Apagado"
SELECT_EFFECT = "Seleccione un efecto de la cadena"
CATALOG_TITLE = "Catálogo de efectos"
SEARCH_EFFECTS = "Buscar efectos…"
SEARCH_EFFECTS_TIP = "Buscar efectos por nombre o grupo"
CLEAR_SEARCH = "Borrar la búsqueda"
DSP_AFTER = "DSP después"
ONLY_A1 = "Solo A1 FOUR"
BADGE_ON_PEDAL = "En la pedalera"
BADGE_IN_CHAIN = "En la cadena"
BADGE_NOT_A1 = "No A1"
NOT_IN_PEDAL_SOURCES = "-"


def tile_tip(name: str, group: str, dsp: float, wide: bool) -> str:
    return f"{name} ({group}) - {percent(dsp)} de DSP" + (" - ocupa dos slots" if wide else "")


def tile_problem_tip(problem: str) -> str:
    return f"No se puede escribir en la pedalera: {problem}\n"


def unknown_effect_title(effect_id: int) -> str:
    return f"El efecto 0x{effect_id:08X} no está en el catálogo (sin rangos de parámetros)"


def catalog_row(name: str, group: str, dsp: float, on_pedal: bool) -> str:
    return f"{name}   {group_label(group)}   {percent(dsp)}" + (f"   {BADGE_ON_PEDAL}" if on_pedal else "")


def visible_count(n: int) -> str:
    return "1 visible" if n == 1 else f"{n} visibles"


def no_effect_matches(query: str, group: str, only_a1: bool) -> str:
    text = f"Ningún efecto coincide con «{query}»" if query else "Ningún efecto coincide con los filtros"
    if group:
        text += f" en {group}"
    if only_a1:
        text += " entre los compatibles con la A1 FOUR"
    return text + "."


def catalog_destination(selected_index: int | None, is_empty: bool, wide: bool, name: str) -> str:
    """Sentence of the destination card: where the selected effect goes and what it replaces."""
    if selected_index is None:
        return NO_TARGET
    n = selected_index + 1
    where = f"Va a los slots {n}–{n + 1}" if wide else f"Va al slot {n}"
    return f"{where} · slot vacío" if is_empty else f"{where} · reemplaza {name}"


def catalog_detail(description: str, dsp: float, wide: bool, sources: str) -> str:
    return f"{description}\n{percent(dsp)} de DSP, {slots_label(2 if wide else 1)}. En: {sources}"


# ----------------------------------------------------------------- tuner

TUNER_TITLE = "Afinador · lectura de la pedalera"
TUNER_EXIT = "Salir del afinador"
TUNER_KEY = "T"
TUNER_SCALE_ZERO = "0"
TUNER_HINT = ("Desvío en pasos de la pedalera (0 = afinado). La pedalera queda muda mientras el afinador "
              "está encendido; pulsar T o «Salir del afinador» para volver al editor.")

ERR_SAVE_FAILED = "No se pudo guardar el patch"

BADGE_TWO_SLOTS = "2 slots"
JACK_IN = "Entrada"
JACK_OUT = "Salida"
TURN_ON = "Encender"
TURN_OFF = "Apagar"
REMOVE = "Quitar"


def slot_label(index: int, wide: bool) -> str:
    return f"Slots {index + 1}–{index + 2}" if wide else f"Slot {index + 1}"


def footswitch_name(is_on: bool, effect: str) -> str:
    """Accessible name: the action the footswitch performs when pressed."""
    return f"{TURN_OFF if is_on else TURN_ON} {effect}"

RESET = "Restablecer"
PARAM_HINT = "Arrastre una perilla · doble clic para restablecer"
NO_PARAM_HELP = "Sin descripción para este parámetro"


def empty_slot_title(n: int) -> str:
    return f"El slot {n} está vacío"


def empty_slot_instructions(n: int) -> str:
    return (f"Elegir un efecto en el catálogo y pulsar «Agregar al slot {n}», Enter o doble clic. "
            "También se puede arrastrar hasta el slot.")


def param_facts(value: int, maximum: int, default: int) -> str:
    return f"Valor {value} · rango 0–{maximum} · predeterminado {default}"


def effect_facts(dsp: float, wide: bool, installed: bool) -> str:
    where = "instalado en la pedalera" if installed else "no instalado en la pedalera"
    return f"{percent(dsp)} de DSP · {slots_label(2 if wide else 1)} · {where}"


def param_range(maximum: int, default: int) -> str:
    return f"0–{maximum} · pred. {default}"

ADD_TO_SLOT = "Agregar al slot {n}"
REPLACE_SLOT = "Reemplazar slot {n}"
REPLACE_SLOTS = "Reemplazar slots {n}–{m}"
NO_TARGET = "Seleccione un patch"
ENTER_HINT = "o Enter · doble clic"


def catalog_target(selected_index: int | None, is_empty: bool, wide: bool) -> str:
    """Label of the catalog button: what pressing it does to the selected pedal."""
    if selected_index is None:
        return NO_TARGET
    n = selected_index + 1
    if is_empty:
        return ADD_TO_SLOT.format(n=n)
    return REPLACE_SLOTS.format(n=n, m=n + 1) if wide else REPLACE_SLOT.format(n=n)

TUNER_NO_NOTE = "Sin nota · tocar una cuerda"
TUNER_IN_TUNE = "AFINADO"


def tuner_status(note: str | None, offset: int) -> str:
    """Pill text of the tuner. Negative offset = flat note (tune up), positive = sharp (tune down), as the
    user confirmed (readme.md: degree 1 = flat, 8 = perfect, 15 = sharp; the value is CC 99 minus 8)."""
    if note is None:
        return TUNER_NO_NOTE
    if offset == 0:
        return TUNER_IN_TUNE
    if offset < 0:
        return f"BAJO −{-offset} · subir afinación"
    return f"ALTO +{offset} · bajar afinación"
