"""Copia de cada informe en la carpeta del jugador, en la unidad compartida del club.

La app entra con una cuenta de servicio del Workspace del club que es «Gestor de
contenido» de la unidad `DRIVE_INFORMES_ID`. Dentro, una carpeta por jugador
(se crea la primera vez y se recuerda en `CarpetaJugador`) y en ella el PDF
de cada evaluación. Si el informe se vuelve a guardar, se reescribe el mismo
fichero en vez de duplicarlo.
"""
import base64
import json
import logging
import unicodedata
import uuid

from django.conf import settings

from . import pdf
from .models import CarpetaJugador

log = logging.getLogger(__name__)

API = "https://www.googleapis.com/drive/v3/files"
SUBIDA = "https://www.googleapis.com/upload/drive/v3/files"
CARPETA = "application/vnd.google-apps.folder"
COMUN = {"supportsAllDrives": "true"}


class DriveNoDisponible(Exception):
    pass


def configurado():
    return bool(settings.GOOGLE_SERVICE_ACCOUNT_JSON and settings.DRIVE_INFORMES_ID)


def _credenciales():
    bruto = settings.GOOGLE_SERVICE_ACCOUNT_JSON.strip()
    if not bruto.startswith("{"):
        bruto = base64.b64decode(bruto).decode()
    return json.loads(bruto)


def ct_configurado():
    """¿Van los informes de tardes a «Mi unidad» de la cuenta del club?"""
    return bool(settings.GOOGLE_SERVICE_ACCOUNT_JSON and settings.DRIVE_CT_USUARIO)


def _sesion(en_nombre_de=None):
    if not (configurado() or (en_nombre_de and ct_configurado())):
        raise DriveNoDisponible("Drive no está conectado.")
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    cred = service_account.Credentials.from_service_account_info(
        _credenciales(), scopes=["https://www.googleapis.com/auth/drive"])
    if en_nombre_de:
        cred = cred.with_subject(en_nombre_de)
    return AuthorizedSession(cred)


def _ok(r, que):
    if not r.ok:
        log.warning("Drive %s: %s %s", que, r.status_code, r.text[:300])
        raise DriveNoDisponible(f"Drive no ha dejado {que} ({r.status_code}).")
    return r.json()


def _sigue_ahi(s, file_id):
    r = s.get(f"{API}/{file_id}", params={**COMUN, "fields": "id,trashed"})
    return r.ok and not r.json().get("trashed")


def _carpeta_jugador(s, jugador):
    """ID de la carpeta del jugador: la recordada, una con su nombre que ya
    hubiera en la unidad o una nueva."""
    raiz = settings.DRIVE_INFORMES_ID
    guardada = CarpetaJugador.objects.filter(jugador=jugador).first()
    if guardada and _sigue_ahi(s, guardada.folder_id):
        return guardada.folder_id
    nombre = jugador.nombre.strip()
    escapado = nombre.replace("\\", "\\\\").replace("'", "\\'")
    r = s.get(API, params={
        **COMUN, "includeItemsFromAllDrives": "true", "corpora": "drive", "driveId": raiz,
        "q": f"name = '{escapado}' and mimeType = '{CARPETA}' and '{raiz}' in parents and trashed = false",
        "fields": "files(id)", "pageSize": 1,
    })
    encontradas = _ok(r, "buscar la carpeta del jugador").get("files", [])
    if encontradas:
        folder_id = encontradas[0]["id"]
    else:
        r = s.post(API, params={**COMUN, "fields": "id"},
                   json={"name": nombre, "mimeType": CARPETA, "parents": [raiz]})
        folder_id = _ok(r, "crear la carpeta del jugador")["id"]
    CarpetaJugador.objects.update_or_create(jugador=jugador, defaults={"folder_id": folder_id})
    return folder_id


def _multipart(metadatos, contenido, tipo="application/pdf"):
    frontera = uuid.uuid4().hex
    cuerpo = (
        f"--{frontera}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(metadatos)}\r\n"
        f"--{frontera}\r\nContent-Type: {tipo}\r\n\r\n"
    ).encode("utf-8") + contenido + f"\r\n--{frontera}--".encode("utf-8")
    return cuerpo, {"Content-Type": f"multipart/related; boundary={frontera}"}


def subir(ev, idioma=None):
    """Sube (o reescribe) el PDF del informe en la carpeta del jugador.
    Devuelve `(file_id, url)`."""
    try:
        s = _sesion()
        nombre, contenido = pdf.nombre(ev, idioma), pdf.generar(ev, idioma)
        params = {**COMUN, "uploadType": "multipart", "fields": "id,webViewLink"}
        if ev.drive_file_id and _sigue_ahi(s, ev.drive_file_id):
            cuerpo, cab = _multipart({"name": nombre}, contenido)
            datos = _ok(s.patch(f"{SUBIDA}/{ev.drive_file_id}", params=params, data=cuerpo, headers=cab),
                        "actualizar el informe")
        else:
            carpeta = _carpeta_jugador(s, ev.jugador)
            cuerpo, cab = _multipart({"name": nombre, "parents": [carpeta], "mimeType": "application/pdf"}, contenido)
            datos = _ok(s.post(SUBIDA, params=params, data=cuerpo, headers=cab), "guardar el informe")
        return datos["id"], datos.get("webViewLink", "")
    except DriveNoDisponible:
        raise
    except Exception as e:  # red, credenciales mal copiadas…: el informe no se pierde
        log.exception("Fallo al subir a Drive")
        raise DriveNoDisponible("No se ha podido guardar en Drive.") from e


def a_la_papelera(file_id):
    """Manda a la papelera de Drive el PDF de un informe que se ha borrado en la
    app. Si no se puede, se deja y se apunta en el log (no es grave)."""
    if not file_id or not (configurado() or ct_configurado()):
        return False
    try:
        s = _sesion(settings.DRIVE_CT_USUARIO if ct_configurado() else None)
        r = s.patch(f"{API}/{file_id}", params=COMUN, json={"trashed": True})
        if not r.ok:
            log.warning("Drive: no se ha podido mandar %s a la papelera (%s)", file_id, r.status_code)
        return r.ok
    except Exception:  # noqa: BLE001
        log.warning("Drive: fallo al mandar %s a la papelera", file_id, exc_info=True)
        return False


# --- Informes de Competición de tardes (27/10/2026) -------------------------
# Unidad › Escuela › Jugador › «Pendientes de validar» | «Validados y enviados».
SUBCARPETA = {"pendientes": "Pendientes de validar", "validados": "Validados y enviados"}


def _escapar(nombre):
    return nombre.replace("\\", "\\\\").replace("'", "\\'")


def _carpeta_ruta(s, partes):
    """ID de la carpeta `partes` (lista de nombres desde la raíz de la unidad);
    crea la que falte y recuerda cada tramo en `CarpetaDrive`."""
    from .models import CarpetaDrive

    raiz = settings.DRIVE_INFORMES_ID
    padre = raiz
    for i in range(len(partes)):
        ruta = "/".join(partes[: i + 1])
        nombre = partes[i].strip()
        guardada = CarpetaDrive.objects.filter(ruta=ruta).first()
        if guardada and _sigue_ahi(s, guardada.folder_id):
            padre = guardada.folder_id
            continue
        r = s.get(API, params={
            **COMUN, "includeItemsFromAllDrives": "true", "corpora": "drive", "driveId": raiz,
            "q": f"name = '{_escapar(nombre)}' and mimeType = '{CARPETA}' and '{padre}' in parents and trashed = false",
            "fields": "files(id)", "pageSize": 1,
        })
        encontradas = _ok(r, "buscar una carpeta").get("files", [])
        if encontradas:
            folder_id = encontradas[0]["id"]
        else:
            folder_id = _ok(s.post(API, params={**COMUN, "fields": "id"},
                                   json={"name": nombre, "mimeType": CARPETA, "parents": [padre]}),
                            "crear una carpeta")["id"]
        CarpetaDrive.objects.update_or_create(ruta=ruta, defaults={"folder_id": folder_id})
        padre = folder_id
    return padre


# --- Competición de tardes en «Mi unidad» del club (02/11/2026) --------------
# DRIVE_CT_RUTA › «Por validar» | «Validados», con los PDF de todos los jugadores
# juntos. La ruta ya existe en el Drive de DRIVE_CT_USUARIO; las dos carpetas se
# crean si faltan.
CARPETA_CT = {"pendientes": "Por validar", "validados": "Validados"}


def _normal(nombre):
    """Para comparar nombres de carpeta sin que importen tildes, mayúsculas ni espacios."""
    sin_tildes = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


def _hija(s, padre, nombre, crear=False):
    """ID de la carpeta `nombre` dentro de `padre` (comparando sin tildes ni mayúsculas)."""
    r = s.get(API, params={**COMUN, "includeItemsFromAllDrives": "true", "pageSize": 200, "fields": "files(id,name)",
                           "q": f"'{padre}' in parents and mimeType = '{CARPETA}' and trashed = false"})
    for f in _ok(r, "buscar una carpeta").get("files", []):
        if _normal(f["name"]) == _normal(nombre):
            return f["id"]
    if not crear:
        raise DriveNoDisponible(f"No encuentro la carpeta «{nombre}» en el Drive de {settings.DRIVE_CT_USUARIO}.")
    return _ok(s.post(API, params={**COMUN, "fields": "id"},
                      json={"name": nombre, "mimeType": CARPETA, "parents": [padre]}), "crear una carpeta")["id"]


def _tramos(texto):
    return [p.strip() for p in texto.split("›") if p.strip()]


def _carpeta_club(s, ruta, destino, prefijo, existen):
    """La carpeta «Por validar» o «Validados» dentro de `ruta` (en «Mi unidad»
    de DRIVE_CT_USUARIO). Los `existen` primeros tramos tienen que estar ya
    (si no, avisa en vez de inventarse la ruta); los siguientes se crean la
    primera vez. Recuerda cada tramo en `CarpetaDrive`."""
    from .models import CarpetaDrive

    partes = _tramos(ruta) + [CARPETA_CT[destino]]
    padre = "root"
    for i, nombre in enumerate(partes):
        clave = prefijo + " › ".join(partes[: i + 1])
        guardada = CarpetaDrive.objects.filter(ruta=clave).first()
        if guardada and _sigue_ahi(s, guardada.folder_id):
            padre = guardada.folder_id
            continue
        padre = _hija(s, padre, nombre, crear=i >= existen)
        CarpetaDrive.objects.update_or_create(ruta=clave, defaults={"folder_id": padre})
    return padre


def _carpeta_ct(s, destino):
    """Competición de tardes: la ruta entera ya existe; solo se crean «Por
    validar» y «Validados»."""
    return _carpeta_club(s, settings.DRIVE_CT_RUTA, destino, "ct:", len(_tramos(settings.DRIVE_CT_RUTA)))


# Alto rendimiento (12/11/2026): como tardes, dentro de su carpeta de «Gestion
# deportiva». Hasta «Alto rendimiento» ya existe en el Drive del club (junto a
# «Jugadores activos», «Metodologia»…); «26/27 › Seguimiento y evaluaciones» y
# las dos carpetas de dentro se crean con el primer informe.
AR_TRAMOS_QUE_EXISTEN = 3


def _carpeta_ar(s, destino):
    return _carpeta_club(s, settings.DRIVE_AR_RUTA, destino, "ar:",
                         min(AR_TRAMOS_QUE_EXISTEN, len(_tramos(settings.DRIVE_AR_RUTA))))


def subir_informe(inf, idioma="ES"):
    """Deja el PDF del informe en la carpeta que le toca por su estado y
    reescribe el mismo fichero: solo se guarda la última versión. Con
    DRIVE_CT_USUARIO, en «Por validar» o «Validados» de su Drive, dentro de
    la ruta de su circuito (tardes o Alto rendimiento); si no, en la unidad
    compartida, Escuela › Jugador › «Pendientes de validar» o «Validados y
    enviados»."""
    try:
        destino = "validados" if inf.estado == inf.Estado.VALIDADO else "pendientes"
        if ct_configurado():
            s = _sesion(settings.DRIVE_CT_USUARIO)
            carpeta = _carpeta_ar(s, destino) if inf.circuito == "alto_rendimiento" else _carpeta_ct(s, destino)
        else:
            s = _sesion()
            escuela = inf.jugador.escuela.nombre if inf.jugador.escuela_id else "Sin escuela"
            carpeta = _carpeta_ruta(s, [escuela, inf.jugador.nombre.strip(), SUBCARPETA[destino]])
        nombre, contenido = pdf.nombre_informe(inf, idioma), pdf.generar_informe(inf, idioma)
        params = {**COMUN, "uploadType": "multipart", "fields": "id,webViewLink,parents"}
        actual = None
        if inf.drive_file_id and _sigue_ahi(s, inf.drive_file_id):
            actual = _ok(s.get(f"{API}/{inf.drive_file_id}", params={**COMUN, "fields": "parents,driveId"}),
                         "leer el informe")
            # El de la unidad compartida de antes no se mueve a «Mi unidad»: se hace uno nuevo.
            if ct_configurado() and actual.get("driveId"):
                actual = None
        if actual is not None:
            cuerpo, cab = _multipart({"name": nombre}, contenido)
            mover = {}
            antiguos = [p for p in actual.get("parents", []) if p != carpeta]
            if antiguos or carpeta not in actual.get("parents", []):
                mover = {"addParents": carpeta, "removeParents": ",".join(antiguos)}
            datos = _ok(s.patch(f"{SUBIDA}/{inf.drive_file_id}", params={**params, **mover}, data=cuerpo, headers=cab),
                        "actualizar el informe")
        else:
            cuerpo, cab = _multipart({"name": nombre, "parents": [carpeta], "mimeType": "application/pdf"}, contenido)
            datos = _ok(s.post(SUBIDA, params=params, data=cuerpo, headers=cab), "guardar el informe")
        inf.drive_file_id, inf.drive_url, inf.drive_carpeta = datos["id"], datos.get("webViewLink", ""), destino
    except DriveNoDisponible:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("Fallo al subir el informe a Drive")
        raise DriveNoDisponible("No se ha podido guardar en Drive.") from e
