from collections import defaultdict
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from academy.models import Entrenador, VacacionesEntrenador
from academy.permissions import es_coach, es_direccion
from academy.scope import puede_ver_jugador

from . import historial
from .models import CambioTorneo, Participante, Torneo
from .serializers import ParticipanteSerializer, TorneoListaSerializer, TorneoSerializer


class SoloDireccionOCoach(BasePermission):
    """El calendario de torneos lo llevan los head coaches y dirección: los
    entrenadores no lo ven (decisión de Sergio, 13/10/2026)."""

    message = "El calendario de torneos es de los head coaches y de dirección."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (es_direccion(u) or es_coach(u)))


class TorneoViewSet(viewsets.ModelViewSet):
    """Calendario de torneos.

    Solo head coaches y dirección. Filtros: `?desde=&hasta=` (solapamiento),
    `?q=` (nombre, lugar, circuito, jugador), `?circuito=`, `?jugador=<id>`,
    `?entrenador=<id>` (acompaña), `?con_jugadores=1`.
    """

    permission_classes = [SoloDireccionOCoach]
    pagination_class = None

    def get_serializer_class(self):
        return TorneoListaSerializer if self.action == "list" else TorneoSerializer

    def get_queryset(self):
        qs = (Torneo.objects
              .prefetch_related("participantes", "acompanantes")
              .annotate(_n_jug=Count("participantes", distinct=True)))
        p = self.request.query_params
        if p.get("desde"):
            qs = qs.filter(fecha_fin__gte=p["desde"])
        if p.get("hasta"):
            qs = qs.filter(fecha_inicio__lte=p["hasta"])
        if p.get("circuito"):
            qs = qs.filter(circuito=p["circuito"])
        if p.get("jugador"):
            qs = qs.filter(participantes__jugador_id=p["jugador"])
        if p.get("entrenador"):
            qs = qs.filter(acompanantes__id=p["entrenador"])
        if p.get("con_jugadores"):
            qs = qs.filter(_n_jug__gt=0)
        if p.get("q"):
            q = p["q"].strip()
            qs = qs.filter(
                Q(nombre__icontains=q) | Q(lugar__icontains=q) | Q(circuito__icontains=q)
                | Q(alias__icontains=q) | Q(participantes__nombre__icontains=q)
                | Q(acompanantes__nombre__icontains=q)
            )
        return qs.distinct().order_by("fecha_inicio", "nombre")

    def perform_create(self, serializer):
        t = serializer.save(creado_por=self.request.user, fuente="Dado de alta en la app")
        historial.registrar(self.request.user, f"Alta de «{t.nombre}»", foto_previa={str(t.id): None})

    def perform_update(self, serializer):
        t = serializer.instance
        claves = set(self.request.data.keys())
        que = "Acompañante de" if claves == {"acompanantes"} else "Cambios en"
        historial.registrar(self.request.user, f"{que} «{t.nombre}»", t.id)
        serializer.save()

    def perform_destroy(self, instance):
        historial.registrar(self.request.user, f"Borrar «{instance.nombre}»", instance.id)
        instance.delete()

    @action(detail=False, methods=["get"])
    def resumen(self, request):
        """Cifras para la cabecera: cuántos torneos, cuántos con jugadores,
        próximos cierres de inscripción y lista de circuitos."""
        hoy = date.today()
        base = Torneo.objects.all()
        proximos_cierres = (
            base.filter(cierre_inscripcion__gte=hoy, cierre_inscripcion__lte=hoy + timedelta(days=21))
            .annotate(n=Count("participantes")).order_by("cierre_inscripcion")[:8]
        )
        return Response({
            "total": base.count(),
            "con_jugadores": base.annotate(n=Count("participantes")).filter(n__gt=0).count(),
            "en_curso": base.filter(fecha_inicio__lte=hoy, fecha_fin__gte=hoy).count(),
            "proximos_cierres": [
                {"id": t.id, "nombre": t.nombre, "cierre_inscripcion": t.cierre_inscripcion,
                 "fecha_inicio": t.fecha_inicio, "n_jugadores": t.n}
                for t in proximos_cierres
            ],
            "circuitos": [{"nombre": c, "n": n} for c, n in
                          base.exclude(circuito="").values_list("circuito").annotate(n=Count("id"))
                          .order_by("-n", "circuito")],
        })

    @action(detail=False, methods=["get"])
    def entrenadores(self, request):
        """Entrenadores activos con sus vacaciones en el tramo pedido, para
        que el desplegable de «acompaña» ofrezca solo a los que no están de
        vacaciones esa semana. Las franjas sueltas (M1, T2…) no cuentan: una
        tarde libre no impide viajar."""
        p = request.query_params
        vac = VacacionesEntrenador.objects.filter(
            ambito__in=[VacacionesEntrenador.Ambito.DIA, VacacionesEntrenador.Ambito.MANANA,
                        VacacionesEntrenador.Ambito.TARDE])
        if p.get("desde"):
            vac = vac.filter(fecha_fin__gte=p["desde"])
        if p.get("hasta"):
            vac = vac.filter(fecha_inicio__lte=p["hasta"])
        por = defaultdict(list)
        for v in vac:
            por[v.entrenador_id].append({
                "fecha_inicio": v.fecha_inicio, "fecha_fin": v.fecha_fin,
                "ambito": v.ambito, "motivo": v.motivo})
        return Response([
            {"id": e.id, "nombre": e.nombre, "vacaciones": por.get(e.id, [])}
            for e in Entrenador.objects.filter(activo=True).order_by("nombre")
        ])

    @action(detail=True, methods=["post"])
    def fusionar(self, request, pk=None):
        """Dos filas que son el mismo torneo: `con` se vuelca en este y se
        borra. Los jugadores pasan aquí (sin repetir), los acompañantes se
        suman, el nombre del otro queda como alias y el tramo de fechas cubre
        los dos."""
        t = self.get_object()
        otro = get_object_or_404(Torneo, pk=request.data.get("con"))
        if otro.pk == t.pk:
            raise ValidationError({"con": "Elige otro torneo."})
        with transaction.atomic():
            historial.registrar(request.user, f"Fusionar «{otro.nombre}» en «{t.nombre}»", t.id, otro.id)
            nombres = set(t.participantes.values_list("nombre", flat=True))
            for p in otro.participantes.all():
                if p.nombre in nombres:
                    p.delete()
                else:
                    p.torneo = t
                    p.save(update_fields=["torneo"])
            t.acompanantes.add(*otro.acompanantes.all())
            alias = [x for x in (t.alias + " | " + otro.nombre + " | " + otro.alias).split(" | ") if x.strip()]
            t.alias = " | ".join(dict.fromkeys(alias))[:300]
            t.fuente = ", ".join(x for x in (t.fuente, otro.fuente) if x)[:300]
            if otro.notas and otro.notas not in t.notas:
                t.notas = f"{t.notas}\n{otro.notas}".strip()
            if otro.acompanante_nota and otro.acompanante_nota not in t.acompanante_nota:
                t.acompanante_nota = ", ".join(x for x in (t.acompanante_nota, otro.acompanante_nota) if x)[:120]
            t.cierre_inscripcion = t.cierre_inscripcion or otro.cierre_inscripcion
            t.lugar = t.lugar or otro.lugar
            t.nivel = t.nivel or otro.nivel
            t.circuito = t.circuito or otro.circuito
            t.fecha_inicio = min(t.fecha_inicio, otro.fecha_inicio)
            t.fecha_fin = max(t.fecha_fin, otro.fecha_fin)
            t.save()
            otro.delete()
        t = self.get_queryset().get(pk=t.pk)
        return Response(TorneoSerializer(t, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["get"])
    def por_jugador(self, request):
        """Una fila por jugador con sus torneos ordenados por fecha."""
        por = {}
        qs = Participante.objects.select_related("torneo", "jugador").order_by("torneo__fecha_inicio")
        for p in qs:
            clave = p.jugador_id or f"n:{p.nombre}"
            d = por.setdefault(clave, {
                "jugador": p.jugador_id, "nombre": p.jugador.nombre if p.jugador else p.nombre,
                "en_academia": p.jugador is not None, "torneos": [],
            })
            d["torneos"].append({
                "id": p.torneo_id, "nombre": p.torneo.nombre, "circuito": p.torneo.circuito,
                "fecha_inicio": p.torneo.fecha_inicio, "fecha_fin": p.torneo.fecha_fin,
                "cierre_inscripcion": p.torneo.cierre_inscripcion, "certeza": p.certeza,
            })
        filas = sorted(por.values(), key=lambda d: (-len(d["torneos"]), d["nombre"]))
        return Response(filas)


class ParticipanteViewSet(viewsets.ModelViewSet):
    """Quién va a cada torneo. Un head coach solo apunta, mueve o quita a
    jugadores de su grupo; a los nombres sin ficha los toca cualquiera."""

    serializer_class = ParticipanteSerializer
    permission_classes = [SoloDireccionOCoach]
    pagination_class = None

    def get_queryset(self):
        qs = Participante.objects.select_related("jugador", "torneo")
        if self.request.query_params.get("torneo"):
            qs = qs.filter(torneo_id=self.request.query_params["torneo"])
        return qs

    def _de_mi_grupo(self, jugador):
        user = self.request.user
        if jugador is None or user.is_superadmin or puede_ver_jugador(user, jugador):
            return
        raise PermissionDenied(f"{jugador.nombre} no es de tu grupo: lo gestiona otro head coach.")

    def perform_create(self, serializer):
        d = serializer.validated_data
        self._de_mi_grupo(d.get("jugador"))
        t = d["torneo"]
        nombre = d.get("nombre") or (d["jugador"].nombre if d.get("jugador") else "")
        historial.registrar(self.request.user, f"Apuntar a {nombre} en «{t.nombre}»", t.id)
        serializer.save()

    def perform_update(self, serializer):
        p = serializer.instance
        self._de_mi_grupo(p.jugador)
        destino = serializer.validated_data.get("torneo")
        if destino is not None and destino.pk != p.torneo_id:
            historial.registrar(self.request.user,
                                f"Mover a {p.nombre} de «{p.torneo.nombre}» a «{destino.nombre}»",
                                p.torneo_id, destino.pk)
        else:
            que = "Confirmar a" if serializer.validated_data.get("certeza") == "CONFIRMADO" else "Cambios en"
            historial.registrar(self.request.user, f"{que} {p.nombre} en «{p.torneo.nombre}»", p.torneo_id)
        serializer.save()

    def perform_destroy(self, instance):
        self._de_mi_grupo(instance.jugador)
        historial.registrar(self.request.user, f"Quitar a {instance.nombre} de «{instance.torneo.nombre}»",
                            instance.torneo_id)
        instance.delete()


class CambioTorneoViewSet(viewsets.ViewSet):
    """Deshacer: cada uno, lo suyo, del último cambio hacia atrás."""

    permission_classes = [SoloDireccionOCoach]

    def list(self, request):
        cambios = CambioTorneo.objects.filter(creado_por=request.user)[:10]
        return Response([
            {"id": c.id, "descripcion": c.descripcion, "creado_at": c.creado_at,
             "torneos": [int(i) for i in c.foto]}
            for c in cambios
        ])

    @action(detail=False, methods=["post"])
    def deshacer(self, request):
        cambio = historial.ultimo(request.user)
        if cambio is None:
            return Response({"detail": "No tienes cambios que deshacer."}, status=404)
        otro = historial.bloqueo(cambio)
        if otro is not None:
            quien = otro.creado_por.get_full_name() or otro.creado_por.username if otro.creado_por else "otra persona"
            return Response({"detail": (
                f"No se puede deshacer «{cambio.descripcion}»: después, {quien} hizo "
                f"«{otro.descripcion}» en el mismo torneo. Corrígelo a mano o habla con {quien}.")},
                status=409)
        torneos = [int(i) for i in cambio.foto]
        descripcion = historial.deshacer(cambio)
        siguiente = historial.ultimo(request.user)
        return Response({
            "deshecho": descripcion, "torneos": torneos,
            "existen": list(Torneo.objects.filter(pk__in=torneos).values_list("id", flat=True)),
            "siguiente": siguiente.descripcion if siguiente else None,
        })
