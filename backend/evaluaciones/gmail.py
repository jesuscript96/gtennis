"""Envío de correo por Gmail con la cuenta de servicio del club (19/11/2026).

La misma cuenta de servicio que guarda los informes en Drive escribe en
nombre de `CORREO_GMAIL` (gestion@gtennis.com) gracias a la delegación en
todo el dominio: en la consola de administración de Google, a su ID de
cliente se le añade el permiso `https://www.googleapis.com/auth/gmail.send`
junto al de Drive. Así no hay que guardar ninguna contraseña.

Es un backend de correo de Django: con `CORREO_GMAIL` puesto, todo
`EmailMessage` sale por aquí (adjuntos, «responder a»…).
"""
import base64
import logging

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

log = logging.getLogger(__name__)

ALCANCE = "https://www.googleapis.com/auth/gmail.send"
ENVIAR = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class GmailNoDisponible(Exception):
    pass


def configurado():
    return bool(getattr(settings, "CORREO_GMAIL", "") and settings.GOOGLE_SERVICE_ACCOUNT_JSON)


def _credenciales():
    from google.oauth2 import service_account

    from .drive import _credenciales as datos

    return service_account.Credentials.from_service_account_info(
        datos(), scopes=[ALCANCE]).with_subject(settings.CORREO_GMAIL)


# Un mensaje sin destinatario: Gmail lo rechaza siempre (400) sin enviar nada,
# pero solo después de comprobar que la API está activada y el permiso vale.
PRUEBA = base64.urlsafe_b64encode(b"Subject: comprobacion G Tenis\r\n\r\nNo se envia.").decode()


def comprobar():
    """¿Deja Google enviar en nombre de la cuenta del club? Pide el permiso de
    acceso y prueba la API con un mensaje sin destinatario, que Gmail rechaza
    sin enviar nada. Devuelve (ok, detalle)."""
    if not configurado():
        return False, "Falta CORREO_GMAIL o la cuenta de servicio."
    from google.auth.transport.requests import AuthorizedSession, Request

    try:
        cred = _credenciales()
        cred.refresh(Request())
    except Exception as e:  # noqa: BLE001 — se enseña el motivo tal cual
        texto = str(e)
        if "unauthorized_client" in texto:
            texto = ("Google no deja enviar todavía: falta autorizar el permiso gmail.send para la "
                     "cuenta de servicio en la consola de administración (delegación en todo el dominio).")
        return False, texto[:300]
    try:
        r = AuthorizedSession(cred).post(ENVIAR, json={"raw": PRUEBA}, timeout=30)
    except Exception as e:  # noqa: BLE001
        return False, f"No se ha podido llegar a Gmail: {e}"[:300]
    if r.status_code == 400:
        return True, f"Envía como {settings.CORREO_GMAIL}."
    if r.ok:  # no debería: un mensaje sin destinatario no sale
        return True, f"Envía como {settings.CORREO_GMAIL}."
    texto = r.text
    if "SERVICE_DISABLED" in texto or "accessNotConfigured" in texto or "has not been used" in texto:
        return False, "La API de Gmail no está activada en el proyecto de Google Cloud (InformesJugadores)."
    return False, f"Gmail responde {r.status_code}: {texto[:250]}"


class GmailBackend(BaseEmailBackend):
    """Manda cada mensaje con la API de Gmail en nombre de `CORREO_GMAIL`."""

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        from google.auth.transport.requests import AuthorizedSession

        enviados = 0
        try:
            sesion = AuthorizedSession(_credenciales())
        except Exception:
            if not self.fail_silently:
                raise
            return 0
        for m in email_messages:
            crudo = base64.urlsafe_b64encode(m.message().as_bytes()).decode()
            try:
                r = sesion.post(ENVIAR, json={"raw": crudo}, timeout=60)
                if not r.ok:
                    log.warning("Gmail: %s %s", r.status_code, r.text[:300])
                    raise GmailNoDisponible(f"Gmail no ha dejado enviar ({r.status_code}): {r.text[:200]}")
                enviados += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return enviados
