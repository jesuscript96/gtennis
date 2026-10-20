from django.conf import settings
from django.http import HttpResponse
from django.utils.http import content_disposition_header
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from academy.models import Jugador
from academy.scope import jugadores_visibles, puede_ver_jugador

from . import catalogo, drive, fichero, ia, pdf
from .models import Evaluacion
from .serializers import EvaluacionSerializer


def _nombre_evaluador(user):
    ent = getattr(user, "entrenador", None)
    if ent is not None:
        return ent.nombre
    return user.get_full_name() or user.username


class EvaluacionViewSet(viewsets.ModelViewSet):
    """Informes de rendimiento.

    Las ve quien ve al jugador (también las de alumnos ya dados de baja, para no
    perder el historial); evalúa cualquiera que tenga al jugador en su alcance y
    la cambia o borra quien la hizo o dirección. Filtros: `?jugador=`, `?estado=`.
    """

    serializer_class = EvaluacionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        visibles = jugadores_visibles(self.request.user, base=Jugador.objects.all())
        qs = Evaluacion.objects.filter(jugador__in=visibles).select_related("jugador")
        p = self.request.query_params
        if p.get("jugador"):
            qs = qs.filter(jugador_id=p["jugador"])
        if p.get("estado"):
            qs = qs.filter(estado=p["estado"])
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        if not puede_ver_jugador(user, serializer.validated_data["jugador"]):
            raise PermissionDenied("Ese jugador no está entre los tuyos.")
        serializer.save(evaluador=user, nombre_evaluador=_nombre_evaluador(user))

    def _editable(self, ev):
        if not ev.puede_editar(self.request.user):
            raise PermissionDenied("Solo quien hizo la evaluación o dirección pueden cambiarla.")
        return ev

    def perform_update(self, serializer):
        self._editable(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._editable(instance).delete()

    @action(detail=False)
    def catalogo(self, request):
        return Response({"bloques": catalogo.para_api(), "ia": bool(settings.ANTHROPIC_API_KEY),
                         "drive": drive.configurado()})

    def _pulir(self, ev, bloque, texto):
        """Guarda el comentario de `bloque` pulido por Claude. Devuelve el aviso si
        no se pudo pulir (entonces se queda el texto del entrenador tal cual)."""
        if catalogo.es_nada(texto):
            ev.comentarios[bloque] = {"original": texto.strip(), "pulido": "", "idioma": ev.idioma}
            return None
        habilidad = catalogo.POR_CLAVE[bloque]["habilidad"] if bloque in catalogo.POR_CLAVE \
            else "los resultados recientes en torneos"
        aviso = None
        try:
            pulido = ia.pulir(texto, ev.idioma, habilidad)
        except ia.IANoDisponible as e:
            pulido, aviso = fichero.limpiar(texto), str(e)
        ev.comentarios[bloque] = {"original": texto.strip(), "pulido": pulido,
                                  "idioma": ev.idioma if aviso is None else ""}
        return aviso

    @action(detail=True, methods=["post"])
    def pulir(self, request, pk=None):
        """`{bloque, texto}` → guarda el comentario del bloque ya redactado."""
        ev = self._editable(self.get_object())
        bloque = request.data.get("bloque")
        if bloque not in catalogo.POR_CLAVE and bloque != catalogo.COMPETICION:
            raise ValidationError({"bloque": "Bloque desconocido."})
        aviso = self._pulir(ev, bloque, str(request.data.get("texto") or ""))
        ev.save(update_fields=["comentarios", "actualizada"])
        return Response({"comentario": ev.comentarios[bloque], "aviso": aviso})

    @action(detail=True, methods=["post"])
    def terminar(self, request, pk=None):
        """Comprueba que estén las 34 notas, pasa los comentarios al idioma del
        informe si hace falta y propone fortalezas y mejoras (si aún no hay o se
        pide `rehacer_resumen`)."""
        ev = self._editable(self.get_object())
        faltan = [b["titulo"] for b in catalogo.BLOQUES
                  if any(k not in ev.puntuaciones for k, _, _ in b["criterios"])]
        if faltan:
            raise ValidationError({"puntuaciones": f"Faltan notas en: {', '.join(faltan)}."})
        avisos = []
        # Un comentario pulido en otro idioma (se cambió el idioma después) se vuelve a pasar.
        for bloque, com in list(ev.comentarios.items()):
            if com.get("pulido") and com.get("idioma") and com["idioma"] != ev.idioma:
                aviso = self._pulir(ev, bloque, com.get("original") or com["pulido"])
                if aviso:
                    avisos.append(aviso)
        if request.data.get("rehacer_resumen") or not (ev.fortalezas or ev.mejoras):
            try:
                ev.fortalezas, ev.mejoras = ia.resumir(ev)
            except ia.IANoDisponible as e:
                avisos.append(f"{e} Escribe tú las fortalezas y mejoras.")
        ev.estado = Evaluacion.Estado.TERMINADA
        ev.terminada_en = ev.terminada_en or timezone.now()
        ev.save()
        datos = self.get_serializer(ev).data
        return Response({**datos, "avisos": list(dict.fromkeys(avisos))})

    @action(detail=True, methods=["post"])
    def drive(self, request, pk=None):
        """Guarda (o reescribe) el informe terminado en la carpeta del jugador en Drive."""
        ev = self._editable(self.get_object())
        if ev.estado != Evaluacion.Estado.TERMINADA:
            raise ValidationError({"estado": "Solo se guardan en Drive los informes terminados."})
        aviso = None
        try:
            ev.drive_file_id, ev.drive_url = drive.subir(ev)
            ev.save(update_fields=["drive_file_id", "drive_url", "actualizada"])
        except drive.DriveNoDisponible as e:
            aviso = f"{e} El informe está guardado en la app; puedes reintentarlo desde su ficha."
        return Response({**self.get_serializer(ev).data, "aviso": aviso})

    @action(detail=True, url_path="pdf")
    def informe_pdf(self, request, pk=None):
        """El informe maquetado, para descargarlo."""
        ev = self.get_object()
        respuesta = HttpResponse(pdf.generar(ev), content_type="application/pdf")
        respuesta["Content-Disposition"] = content_disposition_header(True, pdf.nombre(ev))
        return respuesta

    @action(detail=True)
    def fichero(self, request, pk=None):
        """El `.txt` `clave=valor` del informe, para descargarlo."""
        ev = self.get_object()
        return Response({"nombre": fichero.nombre(ev), "contenido": fichero.contenido(ev)})
