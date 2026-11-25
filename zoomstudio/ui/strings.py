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


def save_button_name(display: int | None) -> str:
    """Accessible name of the icon-only save button."""
    return SAVE_TO_PEDAL if display is None else f"{SAVE_TO_PEDAL} (escribe el patch en la posición {display})"


def save_tooltip(display: int | None, reason: str) -> str:
    return f"{save_button_name(display)}\n{reason}"

TUNER = "Afinador"
SWITCH_ON = "SÍ"
SWITCH_OFF = "NO"
LIVE = "En vivo"
CANCEL = "Cancelar"
CONFIRM = "Confirmar"
TUNER_TIP = "Enciende o apaga el afinador de la pedalera (T). La pedalera queda muda mientras está encendido"
LIVE_TIP = "Envía también a la pedalera los cambios de parámetros y de encendido mientras se edita"
PATCHES = "Patches"
NO_PATCH_SELECTED = "Ningún patch"  # shown at 40 px in the title: the longer sentence did not fit the column
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


DSP_OVER_LIMIT = "sobre el límite"


def dsp_value(dsp: float) -> str:
    """The value written beside the DSP bar («69 %»)."""
    return f"{dsp:.0f} %"


def patches_caption(in_use: int, first: int = 10, last: int = 59) -> str:
    return f"{first}–{last} · {in_use} en uso"


def patch_missing_tip(names: list[str]) -> str:
    """Tooltip and spoken name of the warning on a patch that uses effects the pedal does not have."""
    return f"Usa efectos que no están en la pedalera: {', '.join(names)}"


def patches_missing_tip(count: int) -> str:
    return (f"{count} patches usan" if count != 1 else "1 patch usa") + " efectos que no están en la pedalera"


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
ON_PEDAL_NAME = "Instalado en la pedalera"  # the pedal icon of a catalog card
IN_CHAIN_NAME = "En la cadena del patch"  # the chain-link icon of a catalog card
NOT_INSTALLED_TIP = "Este efecto no está instalado en la pedalera"  # the warning icon (tile and card)
NOT_INSTALLED_TITLE = "Efecto no instalado"
INSTALL_ON_PEDAL = "Instalar en la pedalera"
INSTALL_NEEDS_PEDAL = "Conecte la pedalera para instalar efectos"
NOT_IN_PEDAL_SOURCES = "-"


def tile_tip(name: str, group: str, dsp: float, wide: bool) -> str:
    return f"{name} ({group}) - {percent(dsp)} de DSP" + (" - ocupa dos slots" if wide else "")


def tile_problem_tip(problem: str) -> str:
    return f"No se puede escribir en la pedalera: {problem}\n"


def unknown_effect_title(effect_id: int) -> str:
    return f"El efecto 0x{effect_id:08X} no está en el catálogo (sin rangos de parámetros)"


def catalog_row(name: str, group: str, dsp: float, badges: list[str]) -> str:
    """The text a card says for itself (it is painted, so this is what a screen reader and a search read)."""
    return f"{name}   {group_label(group)}   {percent(dsp)}" + "".join(f"   {b}" for b in badges)


def live_blocks_uninstalled(name: str) -> str:
    return f"En vivo no se puede usar {name}: no está instalado en la pedalera."


def install_offer(reason: str) -> str:
    return f"{reason}\n\n¿Desea instalarlo ahora, sin salir del editor?"


def cannot_quick_install(name: str) -> str:
    return f"{name} no se puede instalar desde el editor: falta su archivo o la pedalera no lo admite."


def visible_count(n: int) -> str:
    return "1 visible" if n == 1 else f"{n} visibles"


def compatible_count(n: int, pedal: str) -> str:
    """Header count of the editor catalog: what is shown is what the target pedal can run."""
    return f"{n} compatibles con {pedal}" if n != 1 else f"1 compatible con {pedal}"


def no_effect_matches(query: str, group: str, pedal: str = "") -> str:
    text = f"Ningún efecto coincide con «{query}»" if query else "Ningún efecto coincide con los filtros"
    if group:
        text += f" en {group}"
    if pedal:
        text += f" entre los compatibles con {pedal}"
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


# ----------------------------------------------------------------- effects manager

EFFECTS_BUTTON = "Efectos"
EFFECTS_TIP = "Instala o quita efectos de la pedalera. La edición de patches queda bloqueada mientras está abierta"
CATALOG_MANAGE = "Administrar"
LIBRARY_EFFECTS = "Instalar o quitar efectos…"
EFFECTS_TITLE = "Efectos de la pedalera"
EFFECTS_CLOSE = "Cerrar"
EFFECTS_INSTALLED = "Instalados"
EFFECTS_AVAILABLE = "Disponibles para instalar"
EFFECTS_SEARCH_TIP = "Buscar efectos por nombre o grupo"
EFFECTS_OFFLINE = ("Conecte la pedalera para administrar sus efectos: sin conexión no se puede ver qué hay "
                   "instalado ni instalar o quitar efectos.")
EFFECTS_LOADING = "Leyendo la lista de efectos de la pedalera…"
EFFECTS_NONE_INSTALLED = "No hay efectos instalados que coincidan."
EFFECTS_NONE_AVAILABLE = "No hay efectos disponibles para instalar que coincidan."
EFFECTS_SELECT_HINT = "Seleccione un efecto para ver su explicación y las acciones disponibles."
EFFECTS_NO_DESCRIPTION = "Este efecto no figura en el catálogo local: no hay explicación disponible."
EFFECTS_INSTALL = "Instalar"
EFFECTS_REMOVE = "Quitar"
EFFECTS_BUSY_INSTALL = "Instalando el efecto en la pedalera…"
EFFECTS_BUSY_REMOVE = "Quitando el efecto de la pedalera…"
EFFECTS_NOT_IN_CATALOG = "No figura en el catálogo local: no se puede comprobar si algún patch lo usa."
EFFECTS_PATCHES_INCOMPLETE = "Aún no se leyeron todos los patches: no se puede comprobar si alguno usa este efecto."
EFFECTS_UNSAVED_PATCHES = "Hay patches con cambios sin guardar: guárdelos o descártelos antes de quitar un efecto."
EFFECTS_INSTALL_OK = "Se puede instalar."
EFFECTS_REMOVE_OK = "Se puede quitar: ningún patch lo usa."
EFFECTS_SIZE_NA = "tamaño n/d"
EFFECTS_DSP_NA = "n/d"
EFFECTS_BACKUP_NOTE = ("Antes de escribir se hace una copia de seguridad de la lista de efectos "
                       "(FLST_SEQ.ZT2) en la carpeta de copias.")


def effects_size(size: int | None) -> str:
    return EFFECTS_SIZE_NA if size is None else f"{number(size / 1024)} KB"


def effects_memory(used: int, total: int, free: int) -> str:
    return f"{_ES.toString(used)} de {_ES.toString(total)} bytes usados · {_ES.toString(free)} bytes libres"


def effects_count(shown: int, total: int) -> str:
    return str(total) if shown == total else f"{shown} de {total}"


def effects_facts(group: str, dsp: str, size: str) -> str:
    return f"{group} · DSP {dsp} · {size}"


def effects_install_blocked(need: int, size: int, margin: int, free: int) -> str:
    return (f"No hay memoria suficiente: hacen falta {_ES.toString(need)} bytes ({_ES.toString(size)} del efecto "
            f"más {_ES.toString(margin)} de margen) y quedan {_ES.toString(free)}.")


EFFECTS_IN_USE_SHORT = "En uso: no se puede quitar"
EFFECTS_USAGE_PENDING_SHORT = "Uso sin confirmar: no se puede quitar todavía"
EFFECTS_USAGE_PENDING_TITLE = "Uso sin confirmar"
EFFECTS_USAGE_NONE = "Ningún patch usa este efecto"
EFFECTS_USAGE_NONE_NOTE = "Se puede quitar sin afectar a ningún patch."


def effects_usage_title(count: int) -> str:
    return f"Usado en {count} patch" + ("" if count == 1 else "es")


def effects_usage_card_name(display: int, name: str) -> str:
    return f"Patch {display}, {name or 'sin nombre'}. Pulse Intro para abrirlo en el editor"


def effects_confirm_install_title(name: str) -> str:
    return f"Instalar {name}"


def effects_confirm_install(name: str, file: str, size: int, free: int) -> str:
    return (f"Se escribirá {file} ({effects_size(size)}) en la pedalera y se marcará {name} como instalado. "
            f"Memoria libre: {_ES.toString(free)} bytes. {EFFECTS_BACKUP_NOTE}")


def effects_confirm_remove_title(name: str) -> str:
    return f"Quitar {name}"


def effects_confirm_remove(name: str, file: str) -> str:
    return (f"Se desmarcará {name} en la lista de efectos y se borrará {file} de la pedalera. "
            f"Ningún patch lo usa. {EFFECTS_BACKUP_NOTE}")


def effects_installed_ok(name: str) -> str:
    return f"{name} instalado en la pedalera"


def effects_repaired_ok(name: str) -> str:
    return f"{name} reparado: se subió el archivo que faltaba"


def effects_removed_ok(name: str) -> str:
    return f"{name} quitado de la pedalera"


def err_effect_change(name: str, installing: bool, exc: object) -> str:
    return with_detail(f"No se pudo {'instalar' if installing else 'quitar'} {name}", exc)


def err_effect_repair(name: str, exc: object) -> str:
    return with_detail(f"No se pudo reparar {name}", exc)
EFFECTS_RETRY = "Reintentar"
EFFECTS_LOAD_FAILED = "No se pudo leer la lista de efectos de la pedalera. El motivo figura en el mensaje de error."


# ---- effects manager: groups
EFFECTS_GROUP_TIP = "Mostrar solo los efectos de un grupo"
EFFECTS_SECTION_TIP = "Clic para plegar o desplegar el grupo"


def effects_section_name(label: str, count: int, expanded: bool) -> str:
    noun = "efecto" if count == 1 else "efectos"
    return f"Grupo {label}, {count} {noun}, {'desplegado' if expanded else 'plegado'}"

# ---- favourites
FAVORITE_ADD = "Marcar como favorito"
FAVORITE_REMOVE = "Quitar de favoritos"
FAVORITES = "Favoritos"


# ---- effects manager: repair an effect whose file is missing
EFFECTS_MISSING = "Falta el archivo"
EFFECTS_MISSING_TIP = "Falta el archivo: la lista de la pedalera marca este efecto como instalado, pero el archivo no está en ella"
EFFECTS_REPAIR = "Reparar"
EFFECTS_NO_LOCAL_COPY = "No hay una copia local de este efecto"
EFFECTS_REPAIR_OK = "Se puede reparar: se subirá solo el archivo que falta."
EFFECTS_BUSY_REPAIR = "Reparando el efecto en la pedalera…"


def effects_confirm_repair_title(name: str) -> str:
    return f"¿Reparar {name}?"


def effects_confirm_repair(name: str, file: str, size: int, free: int) -> str:
    return (f"La lista de la pedalera marca {name} como instalado, pero falta su archivo {file}. "
            f"Solo se sube el archivo ({effects_size(size)}); no se modifica la lista de efectos. "
            f"Antes de escribir se guarda una copia de seguridad de la lista (FLST_SEQ.ZT2).")
EFFECTS_USAGE_LIST = "Patches que usan el efecto"


# ---- patch bank
BANK_BUTTON = "Banco"
BANK_TIP = "Banco de patches: guarda patches fuera de la pedalera y los vuelve a cargar en la posición que quiera"
LIBRARY_BANK = "Banco de patches…"
MOVE_TO_BANK = "Mover al banco (liberar posición)"
BANK_TITLE = "Banco de patches"
BANK_CLOSE = "Cerrar"
BANK_POSITIONS = "En la pedalera"
BANK_ENTRIES = "En el banco"
BANK_SEARCH = "Buscar en el banco"
BANK_SEARCH_TIP = "Buscar patches del banco por nombre, posición de origen o fecha"
BANK_POSITIONS_LIST = "Posiciones de la pedalera"
BANK_ENTRIES_LIST = "Patches del banco"
BANK_LOAD = "Cargar en la posición…"
BANK_LOAD_TIP = "Carga el patch del banco en la posición que elija; si está ocupada, su patch pasa al banco"
BANK_STASH = "Guardar en el banco y liberar"
BANK_STASH_TIP = "Guarda el patch de la posición en el banco y deja la posición vacía"
BANK_EMPTY = "El banco está vacío. Arrastre un patch de la pedalera hasta aquí, o use «Guardar en el banco y liberar»."
BANK_NO_MATCH = "Ningún patch del banco coincide con la búsqueda."
BANK_OFFLINE_NOTE = "Conecte la pedalera para mover patches entre ella y el banco."
BANK_BUSY_NOTE = "Escribiendo en la pedalera…"
BANK_HINT = "Elija una posición y un patch del banco, o arrastre uno sobre el otro."
BANK_DROP_HERE = "Suelte aquí para guardar en el banco"
BANK_ORIGIN_UNKNOWN = "Origen desconocido"
BANK_DAMAGED = "Archivo dañado"
BANK_CHOOSE_TITLE = "Cargar en la posición"
BANK_CHOOSE_LABEL = "Posición de la pedalera:"
CONFIRM_BANK_STASH = "Guardar y liberar"
CONFIRM_BANK_LOAD = "Cargar"
BANK_STASH_TITLE = "Guardar en el banco y liberar"
BANK_LOAD_TITLE = "Cargar desde el banco"

ERR_BANK_NOTHING_TO_KEEP = "La posición ya está vacía: no hay nada que guardar en el banco"
ERR_BANK_OFFLINE = "Conecte la pedalera para mover patches entre ella y el banco"
ERR_BANK_LOADING = "Espere a que terminen de leerse los patches de la pedalera antes de usar el banco"
ERR_BANK_KEPT_BOTH = "No se pudo escribir en la pedalera: el banco conserva ambos patches"
ERR_BANK_KEPT_ONE = "No se pudo escribir en la pedalera: el banco conserva el patch"
ERR_BANK_NOT_FREED = "No se pudo vaciar la posición: el patch sigue en la pedalera y también quedó guardado en el banco"


def err_bank_unsaved(display: int) -> str:
    return f"El patch {display} tiene cambios sin guardar: guárdelos o descártelos antes de usar el banco"


def err_bank_store(why: object) -> str:
    return f"No se pudo guardar en el banco, no se escribió nada en la pedalera: {why}"


def err_bank_unknown(why: object) -> str:
    return f"No se pudo leer el patch del banco, no se escribió nada en la pedalera: {why}"


def err_bank_not_removed(name: str, why: object) -> str:
    return f"«{name}» ya está en la pedalera, pero no se pudo quitar del banco: {why}"


def _bank_name(name: str) -> str:
    return f"«{name or UNNAMED}»"


def bank_stash_text(display: int, name: str) -> str:
    return (f"El patch {display} ({_bank_name(name)}) pasa al banco y la posición {display} queda vacía "
            f"(se escribe el patch Empty de fábrica).")


def bank_load_text(display: int, name: str, occupant: str | None) -> str:
    if occupant is None:
        return (f"{_bank_name(name)} sale del banco y se escribe en la posición {display}, que está vacía.")
    return (f"{_bank_name(name)} sale del banco y se escribe en la posición {display}; "
            f"el patch {display} ({_bank_name(occupant)}) pasa al banco.")


def ask_bank_stash(display: int, name: str) -> str:
    return (bank_stash_text(display, name) + "\nPrimero se guarda en el banco y se comprueba el archivo; "
            "después se escribe en la pedalera con su copia de seguridad previa y lectura de verificación.")


def ask_bank_load(display: int, name: str, occupant: str | None) -> str:
    keep = ("\nEl patch actual se guarda primero en el banco y se comprueba el archivo. " if occupant is not None else "\n")
    return (bank_load_text(display, name, occupant) + keep +
            "El patch del banco se quita solo cuando la lectura de verificación de la pedalera coincide; "
            "si la escritura falla, el banco conserva todo.")


def bank_preview(position: tuple[int, str | None] | None, entry: str | None, dirty: bool = False) -> str:
    """One line about what the next action would do; ``position`` = (display, name or None when free)."""
    if position is None and entry is None:
        return BANK_HINT
    parts = []
    if position is not None:
        display, name = position
        parts.append(f"Posición {display}: {_bank_name(name)}" if name else f"Posición {display}: vacía")
    if entry is not None:
        parts.append(f"Banco: {_bank_name(entry)}")
    head = " · ".join(parts)
    if position is not None and entry is not None:
        display, name = position
        action = bank_load_text(display, entry, name)
    elif position is not None:
        display, name = position
        action = bank_stash_text(display, name) if name else "La posición ya está vacía."
    else:
        action = "Elija la posición donde cargarlo."
    return f"{head}\n{action}" + ("\nTiene cambios sin guardar: guárdelos antes." if dirty else "")


def bank_stashed(display: int, name: str) -> str:
    return f"{_bank_name(name)} está en el banco y la posición {display} quedó libre"


def bank_loaded(display: int, name: str, occupant: str | None) -> str:
    extra = f"; {_bank_name(occupant)} pasó al banco" if occupant is not None else ""
    return f"{_bank_name(name)} está en la posición {display}{extra}"


def bank_origin(origin: int | None) -> str:
    return f"Posición {origin}" if origin else BANK_ORIGIN_UNKNOWN


def bank_date(stamp: str) -> str:
    """``20261125-101500`` -> ``25/11/2026 10:15``."""
    try:
        return f"{stamp[6:8]}/{stamp[4:6]}/{stamp[0:4]} {stamp[9:11]}:{stamp[11:13]}"
    except IndexError:
        return stamp


def bank_count(count: int) -> str:
    return "1 patch" if count == 1 else f"{count} patches"


def bank_card_name(name: str, origin: int | None, stamp: str) -> str:
    return f"{_bank_name(name)}, {bank_origin(origin)}, {bank_date(stamp)}"


# ---- patch bank: rename and delete entries
BANK_RENAME = "Renombrar…"
BANK_RENAME_TIP = "Cambia el nombre del patch del banco (F2); el patch conserva el nuevo nombre al cargarlo en la pedalera"
BANK_DELETE = "Eliminar"
BANK_DELETE_TIP = "Mueve el patch a la papelera del banco (Supr); se puede recuperar desde esa carpeta"
BANK_RENAME_TITLE = "Renombrar patch del banco"
BANK_RENAME_LABEL = "Nombre nuevo:"
BANK_RENAME_OK = "Renombrar"
BANK_DELETE_TITLE = "Eliminar del banco"
CONFIRM_BANK_DELETE = "Mover a la papelera"
ERR_BANK_BUSY = "Hay una operación del banco en curso: espere a que termine"


def bank_name_hint(limit: int) -> str:
    return f"Hasta {limit} caracteres ASCII imprimibles"


def ask_bank_delete(name: str, trash: object) -> str:
    return (f"{_bank_name(name)} sale del banco y se mueve a la carpeta de la papelera:\n{trash}\n"
            "No se borra: se puede recuperar copiando el archivo desde esa carpeta. No se toca la pedalera.")


def bank_renamed(old: str, new: str) -> str:
    return f"{_bank_name(old)} ahora se llama {_bank_name(new)}; el archivo anterior quedó en la papelera del banco"


def bank_deleted(name: str, path: object) -> str:
    return f"{_bank_name(name)} está en la papelera del banco: {path}"


def err_bank_rename(why: object) -> str:
    return f"No se pudo renombrar el patch del banco: {why}"


def err_bank_delete(why: object) -> str:
    return f"No se pudo eliminar el patch del banco: {why}"


# ---- discard the changes of a patch
DISCARD_CHANGES_TIP = "Descartar cambios y volver a la última versión guardada"
DISCARD_NOTHING = "No hay cambios sin guardar en este patch"


def discard_tooltip(shortcut: str, reason: str = "") -> str:
    base = f"{DISCARD_CHANGES_TIP} ({shortcut})"
    return f"{base}\n{reason}" if reason else base


def discard_patch_title(display: int, name: str) -> str:
    return f"¿Descartar los cambios del patch {display}" + (f" «{name}»?" if name else "?")


def discard_patch_text(display: int, name: str) -> str:
    label = f"{display} «{name}»" if name else str(display)
    return (f"Se descartan los cambios sin guardar del patch {label}: vuelve a su última versión guardada. "
            "Puede recuperarlos con Deshacer.")

# ---- pedal target
CATALOG_PEDAL_TIP = "Pedal para el que se muestran los efectos compatibles"


# ---- effects screen: pedal filter (names always come from the detected model, never written here)
EFFECTS_ALL_PEDALS = "Todos los pedales"
EFFECTS_PEDAL_TIP = "Pedal cuyos efectos se muestran"
EFFECTS_THIS_PEDAL = "este pedal"
EFFECTS_NOT_INSTALLABLE = "No compatible con este pedal"
EFFECTS_NOT_IN_PEDAL_LIST = "La lista de la pedalera no incluye este efecto: no se puede instalar"


def pedal_connected_label(name: str) -> str:
    return f"{name} (conectada)"


def not_compatible_with(name: str) -> str:
    return f"No compatible con {name}"


def effects_not_compatible_reason(name: str) -> str:
    return f"Este efecto no es compatible con {name}: no se puede instalar"


# ---- pedals the app cannot edit yet
def pedal_readonly_banner(name: str) -> str:
    return f"{name} detectada: la edición todavía no está verificada en este modelo; solo lectura"


def pedal_readonly_reason(name: str) -> str:
    return f"{name}: edición no verificada en este modelo, solo lectura"


def pedal_unknown_banner(model_id: int) -> str:
    return f"Pedal no reconocido (modelo 0x{model_id:08X}): solo lectura"


def pedal_unknown_reason() -> str:
    return "Pedal no reconocido: solo lectura"


# ---- effect library updates (Zoom's Guitar Lab channel)
LIBRARY_UPDATE = "Actualizar biblioteca de efectos…"
UPDATE_BUTTON = "Actualizar biblioteca…"
UPDATE_BUTTON_TIP = "Busca efectos nuevos o actualizados en el canal público de Zoom y los descarga a la biblioteca de la aplicación"
UPDATE_TITLE = "Biblioteca de efectos"
UPDATE_CLOSE = "Cerrar"
UPDATE_ALL_MODELS = "Todos los modelos"
UPDATE_ALL_MODELS_TIP = "Incluye los efectos de todos los modelos de pedalera que Zoom publica, no solo los del modelo elegido"
UPDATE_CHECK = "Buscar de nuevo"
UPDATE_CHECK_TIP = "Vuelve a consultar el canal de Zoom"
UPDATE_NEW_TITLE = "Nuevos"
UPDATE_UPDATED_TITLE = "Actualizados"
UPDATE_NEW_LIST = "Efectos nuevos"
UPDATE_UPDATED_LIST = "Efectos con una versión más reciente"
UPDATE_CHECKING = "Consultando el canal de Zoom…"
UPDATE_UP_TO_DATE = "La biblioteca de efectos está al día."
UPDATE_NO_NEW = "No hay efectos nuevos."
UPDATE_NO_UPDATED = "No hay efectos con una versión más reciente."
UPDATE_ERROR_OFFLINE = ("No se pudo consultar el canal de Zoom. Compruebe la conexión a internet y vuelva a "
                        "intentarlo; la biblioteca actual no se ha tocado.")
UPDATE_DOWNLOAD = "Descargar"
UPDATE_DOWNLOAD_TIP = "Descarga los efectos de las listas y los guarda en la biblioteca de la aplicación"
UPDATE_CANCEL = "Cancelar"
UPDATE_CANCEL_TIP = "Detiene la descarga después del efecto en curso; lo ya descargado se conserva"
UPDATE_NOTICE_VIEW = "Ver"
UPDATE_NOTICE_VIEW_TIP = "Abre la biblioteca de efectos para ver y descargar las novedades"
UPDATE_NOTICE_DISMISS = "Descartar el aviso"
UPDATE_SIZE_UNKNOWN = "Tamaño sin determinar"
UPDATE_PROGRESS_LIST = "Progreso de la descarga"
UPDATE_NEW_LIST_NAME = "Efectos nuevos disponibles"
UPDATE_UPDATED_LIST_NAME = "Efectos con actualización disponible"
UPDATE_SUMMARY_FAILED_LIST = "Efectos que no se pudieron descargar"

UPDATE_REASONS = {
    "bad_name": "el nombre del archivo no es válido",
    "bad_version": "la versión indicada no es válida",
    "network": "falló la descarga",
    "too_large": "el archivo es más grande de lo permitido",
    "bad_zip": "el archivo comprimido está dañado",
    "no_zd2": "el archivo comprimido no contiene el efecto",
    "many_zd2": "el archivo comprimido contiene más de un efecto",
    "oversized": "el efecto pesa más de lo permitido",
    "bad_zd2": "el archivo no es un efecto válido",
    "id_mismatch": "el efecto descargado no es el que anuncia la lista",
    "version_mismatch": "la versión descargada no es la que anuncia la lista",
    "exists": "ya existe un archivo con ese nombre en la biblioteca",
    "write_failed": "no se pudo escribir en la carpeta de la biblioteca",
}


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


def update_scope(pedal: str, all_models: bool) -> str:
    return "Efectos de todos los modelos" if all_models or not pedal else f"Efectos para {pedal}"


def update_count(count: int) -> str:
    return _plural(count, "1 efecto", f"{count} efectos")


def update_notice(count: int, pedal: str) -> str:
    noun = _plural(count, "un efecto nuevo o actualizado", f"{count} efectos nuevos o actualizados")
    return f"Hay {noun} para {pedal}" if pedal else f"Hay {noun}"


def firmware_notice(remote: str, pedal: str, current: str | None) -> str:
    own = f" (la pedalera tiene {current})" if current else ""
    return (f"Zoom publica firmware {remote} para {pedal}{own}. "
            "La actualización se hace con Guitar Lab o con el actualizador de Zoom en Windows o macOS.")


def update_card_version(version: str, local: str | None) -> str:
    return f"Versión {version}" if local is None else f"Versión {local} → {version}"


def update_card_line(group: str, version: str, local: str | None, size: int | None) -> str:
    parts = [group_label(group)] if group else []
    parts.append(update_card_version(version, local))
    if size is not None:
        parts.append(f"{number(size / 1024)} KB")
    return " · ".join(parts)


def update_progress(done: int, total: int, name: str) -> str:
    return f"Descargando {done + 1} de {total}: {name}"


def update_summary(ok: int, failed: int, cancelled: bool) -> str:
    parts = []
    if ok:
        parts.append(_plural(ok, "Se descargó 1 efecto", f"Se descargaron {ok} efectos"))
    if failed:
        parts.append(_plural(failed, "1 efecto no se pudo descargar", f"{failed} efectos no se pudieron descargar"))
    if not parts:
        parts.append("No se descargó ningún efecto")
    text = "; ".join(parts) + "."
    return text + (" La descarga se canceló." if cancelled else "")


def update_failure(name: str, reason: str) -> str:
    return f"{name}: {UPDATE_REASONS.get(reason, 'error desconocido')}"


def update_more_failures(count: int) -> str:
    return f"y {_plural(count, '1 más', f'{count} más')}"


def update_reloaded(ok: int) -> str:
    return _plural(ok, "Biblioteca actualizada: 1 efecto nuevo ya está en el catálogo",
                   f"Biblioteca actualizada: {ok} efectos ya están en el catálogo")


def update_library_folder(path: object) -> str:
    return f"Se guardan en {path}"
