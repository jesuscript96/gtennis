from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse
from django.utils.http import content_disposition_header
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from academy.models import Jugador
from academy.permissions import evalua_fisico, evalua_tenis_solo_informes
from academy.scope import jugadores_visibles, puede_ver_jugador

from . import catalogo, drive, fichero, ia, pdf
from .models import Evaluacion, EvaluacionFisica
from .serializers import EvaluacionFisicaSerializer, EvaluacionSerializer


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

    def _jugadores(self):
        """A quién puede evaluar de tenis: los suyos de siempre y, si es de los
        entrenadores de Competición de tardes o de gestión deportiva, también
        los alumnos de las escuelas «solo informes» (que están inactivos)."""
        user = self.request.user
        filtro = Q(pk__in=jugadores_visibles(user).values("pk"))
        if evalua_tenis_solo_informes(user):
            filtro |= Q(pk__in=jugadores_evaluables_fisico().values("pk"))
        return Jugador.objects.filter(filtro)

    def get_queryset(self):
        user = self.request.user
        visibles = jugadores_visibles(user, base=Jugador.objects.all())
        filtro = Q(jugador__in=visibles)
        if evalua_tenis_solo_informes(user):
            filtro |= Q(jugador__escuela__solo_informes=True)
        qs = Evaluacion.objects.filter(filtro).select_related("jugador").distinct()
        p = self.request.query_params
        if p.get("jugador"):
            qs = qs.filter(jugador_id=p["jugador"])
        if p.get("estado"):
            qs = qs.filter(estado=p["estado"])
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        if not self._jugadores().filter(pk=serializer.validated_data["jugador"].pk).exists():
            raise PermissionDenied("Ese jugador no está entre los tuyos.")
        serializer.save(evaluador=user, nombre_evaluador=_nombre_evaluador(user))

    @action(detail=False)
    def jugadores(self, request):
        """Los jugadores que puede evaluar de tenis, con su escuela y la fecha
        de su última evaluación de tenis."""
        ultimas = dict(Evaluacion.objects.order_by("fecha").values_list("jugador_id", "fecha"))
        return Response([{
            "id": j.id, "nombre": j.nombre,
            "escuela": j.escuela.nombre if j.escuela_id else "",
            "solo_informes": bool(j.escuela_id and j.escuela.solo_informes),
            "ultima": str(ultimas[j.id]) if j.id in ultimas else None,
        } for j in self._jugadores().select_related("escuela").order_by("nombre")])

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


def jugadores_evaluables_fisico():
    """Los alumnos de las escuelas «solo informes» (hoy, Competición de tardes)."""
    from django.db.models import Q

    hoy = timezone.localdate()
    return (Jugador.objects.filter(escuela__solo_informes=True)
            .filter(Q(fecha_baja__isnull=True) | Q(fecha_baja__gte=hoy))
            .select_related("escuela").order_by("nombre"))


class EvaluacionFisicaViewSet(viewsets.ModelViewSet):
    """Parte física de los informes. Solo para el preparador físico y gestión
    deportiva (dirección y Dani Gimeno); ven todas, y cambia o borra cada una
    quien la hizo o gestión deportiva. Filtro: `?jugador=`."""

    serializer_class = EvaluacionFisicaSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not evalua_fisico(request.user):
            raise PermissionDenied("La parte física es del preparador físico y de gestión deportiva.")

    def get_queryset(self):
        qs = EvaluacionFisica.objects.select_related("jugador")
        if self.request.query_params.get("jugador"):
            qs = qs.filter(jugador_id=self.request.query_params["jugador"])
        return qs

    def perform_create(self, serializer):
        jugador = serializer.validated_data["jugador"]
        if not jugadores_evaluables_fisico().filter(pk=jugador.pk).exists():
            raise PermissionDenied("Ese jugador no está en Competición de tardes.")
        serializer.save(evaluador=self.request.user, nombre_evaluador=_nombre_evaluador(self.request.user))

    def _editable(self, ev):
        if not ev.puede_editar(self.request.user):
            raise PermissionDenied("Solo quien la hizo o gestión deportiva pueden cambiarla.")
        return ev

    def perform_update(self, serializer):
        self._editable(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._editable(instance).delete()

    @action(detail=False)
    def catalogo(self, request):
        return Response(catalogo.fisico_para_api())

    @action(detail=False)
    def jugadores(self, request):
        """Los jugadores a los que se les puede hacer la parte física, con la
        fecha de su última evaluación física."""
        ultimas = {}
        for ev in EvaluacionFisica.objects.order_by("fecha").values("jugador_id", "fecha", "estado"):
            ultimas[ev["jugador_id"]] = ev
        return Response([{
            "id": j.id, "nombre": j.nombre, "edad": j.edad, "foto": j.foto_url or "",
            "ultima": str(ultimas[j.id]["fecha"]) if j.id in ultimas else None,
        } for j in jugadores_evaluables_fisico()])

    @action(detail=True, methods=["post"])
    def terminar(self, request, pk=None):
        ev = self._editable(self.get_object())
        faltan = [b["titulo"] for b in catalogo.BLOQUES_FISICO
                  if any(k not in ev.puntuaciones for k, _, _ in b["criterios"])]
        if faltan:
            raise ValidationError({"puntuaciones": f"Faltan notas en: {', '.join(faltan)}."})
        ev.estado = EvaluacionFisica.Estado.TERMINADA
        ev.terminada_en = ev.terminada_en or timezone.now()
        ev.save(update_fields=["estado", "terminada_en", "actualizada"])
        return Response(self.get_serializer(ev).data)
