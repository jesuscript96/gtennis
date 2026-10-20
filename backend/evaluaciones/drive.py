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


def _sesion():
    if not configurado():
        raise DriveNoDisponible("Drive no está conectado.")
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    cred = service_account.Credentials.from_service_account_info(
        _credenciales(), scopes=["https://www.googleapis.com/auth/drive"])
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


def subir(ev):
    """Sube (o reescribe) el PDF del informe en la carpeta del jugador.
    Devuelve `(file_id, url)`."""
    try:
        s = _sesion()
        nombre, contenido = pdf.nombre(ev), pdf.generar(ev)
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
