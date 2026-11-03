from collections import defaultdict
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response

from academy.models import Aviso, Coach, Entrenador, Jugador, VacacionesEntrenador
from academy.permissions import es_coach, es_direccion

from . import historial
from .models import CambioTorneo, Participante, Torneo
from .serializers import ParticipanteSerializer, TorneoListaSerializer, TorneoSerializer, entrenador_de


class SoloDireccionOCoach(BasePermission):
    """El calendario de torneos lo ve cualquiera con sesión, pero solo lo
    cambian los head coaches y dirección (16/10/2026; del 13/10 al 16/10 los
    entrenadores ni lo veían)."""

    message = "Solo los head coaches y dirección pueden cambiar el calendario de torneos."

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return manda(u)


def manda(user):
    """Head coach o dirección: crean y editan torneos, y apuntan, confirman,
    mueven y quitan jugadores."""
    return es_direccion(user) or es_coach(user)


def es_entrenador(user):
    return getattr(user, "entrenador", None) is not None


class ApuntanTambienEntrenadores(SoloDireccionOCoach):
    """Quién va a cada torneo: además de head coaches y dirección, los
    entrenadores apuntan a sus jugadores (03/11/2026). Qué puede tocar cada
    uno lo decide el viewset."""

    message = "Solo los entrenadores, los head coaches y dirección apuntan jugadores a los torneos."

    def has_permission(self, request, view):
        return super().has_permission(request, view) or bool(
            request.user and request.user.is_authenticated and es_entrenador(request.user))


def _q_de_mi_grupo(user):
    """Los jugadores que alguien lleva en los torneos, según Grupos: el
    entrenador, los de su columna (es su responsable o comparte la gestión);
    el head coach, los de las columnas de sus entrenadores y las altas que aún
    no tienen entrenador. None = todos (dirección).

    03/11/2026: antes valía lo que cada uno ve en Mis jugadores, y ahí entran
    los porcentajes (con quién entrena), el resto de su color y los invitados:
    a Álvaro le salían 24 jugadores para apuntar y en Grupos tiene 6."""
    if user.is_superadmin:
        return None
    coach = getattr(user, "coach", None)
    if coach is not None and coach.activo:
        ents = coach.entrenadores.all()
        return (Q(entrenador_responsable__isnull=True) | Q(entrenador_responsable__in=ents)
                | Q(cogestores__in=ents))
    ent = getattr(user, "entrenador", None)
    if ent is None:
        return Q(pk__in=[])
    return Q(entrenador_responsable=ent) | Q(cogestores=ent)


def jugadores_apuntables(user):
    """A quién ofrece el desplegable de apuntar: los de su grupo que siguen
    entrenando, sin invitados."""
    qs = (Jugador.objects.filter(activo=True, invitaciones__isnull=True)
          .filter(Q(fecha_baja__isnull=True) | Q(fecha_baja__gte=date.today())))
    q = _q_de_mi_grupo(user)
    return (qs if q is None else qs.filter(q)).distinct().order_by("nombre")


def es_de_mi_grupo(user, jugador):
    q = _q_de_mi_grupo(user)
    return q is None or Jugador.objects.filter(q, pk=jugador.pk).exists()


def avisar_head_coach(participante, usuario):
    """Un entrenador ha apuntado a un jugador: lo sabe el head coach del grupo
    del jugador (el color de quien lo gestiona) para confirmarlo, moverlo o
    quitarlo. Si el jugador no tiene grupo, el del entrenador; si tampoco,
    dirección."""
    t, j = participante.torneo, participante.jugador
    quien = getattr(usuario, "entrenador", None)
    con_color = Coach.objects.filter(activo=True, user__isnull=False).exclude(color="")
    gestores = [e for e in [j.entrenador_responsable, *j.cogestores.all()] if e is not None]
    coaches = list(con_color.filter(entrenadores__in=gestores).distinct()) if gestores else []
    if not coaches and quien is not None:
        coaches = list(con_color.filter(entrenadores=quien).distinct())
    fechas = f"{t.fecha_inicio:%d/%m}" + (f" al {t.fecha_fin:%d/%m}" if t.fecha_fin != t.fecha_inicio else "")
    titulo = f"{quien.nombre if quien else usuario.username} apunta a {j.nombre} a «{t.nombre}»"[:160]
    mensaje = (f"Torneo del {fechas}. Queda pendiente de confirmar: en Torneos, «Por confirmar», "
               f"lo confirmas, lo mueves a otro torneo o lo quitas.")
    destinos = [c.user for c in coaches if c.user_id != usuario.id]
    if not destinos:
        Aviso.objects.create(para_direccion=True, tipo=Aviso.Tipo.GENERAL, titulo=titulo, mensaje=mensaje)
    for u in destinos:
        Aviso.objects.create(usuario=u, tipo=Aviso.Tipo.GENERAL, titulo=titulo, mensaje=mensaje)


class TorneoViewSet(viewsets.ModelViewSet):
    """Calendario de torneos.

    Lo ve cualquiera con sesión; lo cambian head coaches y dirección. Filtros: `?desde=&hasta=` (solapamiento),
    `?q=` (nombre, lugar, circuito, jugador), `?circuito=`, `?jugador=<id>`,
    `?entrenador=<id>` (acompaña), `?con_jugadores=1`.
    """

    permission_classes = [SoloDireccionOCoach]
    pagination_class = None

    def get_serializer_class(self):
        return TorneoListaSerializer if self.action == "list" else TorneoSerializer

    def get_queryset(self):
        qs = (Torneo.objects
              .prefetch_related("participantes__apuntado_por__entrenador", "acompanantes",
                                "participantes__jugador__entrenador_responsable",
                                "participantes__jugador__cogestores")
              .annotate(_n_jug=Count("participantes", distinct=True)))
        p = self.request.query_params
        if p.get("desde"):
            qs = qs.filter(fecha_fin__gte=p["desde"])
        if p.get("hasta"):
            # La previa también cuenta: un torneo cuya previa cae en el tramo sale.
            qs = qs.filter(Q(fecha_inicio__lte=p["hasta"]) | Q(qualy_inicio__lte=p["hasta"]))
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
            "en_curso": base.filter(Q(fecha_inicio__lte=hoy) | Q(qualy_inicio__lte=hoy), fecha_fin__gte=hoy).count(),
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
            if otro.qualy_inicio and (not t.qualy_inicio or otro.qualy_inicio < t.qualy_inicio):
                t.qualy_inicio = otro.qualy_inicio
            t.qualy_fin = t.qualy_fin or otro.qualy_fin
            t.solo_fines_semana = t.solo_fines_semana or otro.solo_fines_semana
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
    jugadores de su grupo; a los nombres sin ficha los toca cualquiera.

    Desde el 03/11/2026 los entrenadores apuntan a sus jugadores (los de su
    columna en Grupos) a torneos que ya existen. Lo suyo entra como
    pendiente y avisa al head coach; solo pueden quitar lo que apuntaron ellos
    mientras siga pendiente. Mover y confirmar, head coaches y dirección."""

    serializer_class = ParticipanteSerializer
    permission_classes = [ApuntanTambienEntrenadores]
    pagination_class = None

    def get_queryset(self):
        qs = (Participante.objects
              .select_related("jugador__entrenador_responsable", "torneo", "apuntado_por__entrenador")
              .prefetch_related("jugador__cogestores"))
        if self.request.query_params.get("torneo"):
            qs = qs.filter(torneo_id=self.request.query_params["torneo"])
        return qs

    def _de_mi_grupo(self, jugador):
        user = self.request.user
        if jugador is None or es_de_mi_grupo(user, jugador):
            return
        raise PermissionDenied(f"{jugador.nombre} no es de tu grupo: lo gestiona otro head coach.")

    def _puede_apuntar_entrenador(self, d):
        user = self.request.user
        jugador, t = d.get("jugador"), d["torneo"]
        if jugador is None:
            raise ValidationError({"jugador": "Elige a uno de tus jugadores."})
        if not jugadores_apuntables(user).filter(pk=jugador.pk).exists():
            raise PermissionDenied(f"{jugador.nombre} no está en tu columna de Grupos.")
        if t.fecha_fin < date.today():
            raise ValidationError({"torneo": "Ese torneo ya ha terminado."})
        if t.estado == Torneo.Estado.CANCELADO:
            raise ValidationError({"torneo": "Ese torneo está cancelado."})

    def perform_create(self, serializer):
        d = serializer.validated_data
        user = self.request.user
        extra = {"apuntado_por": user}
        if manda(user):
            self._de_mi_grupo(d.get("jugador"))
        else:
            self._puede_apuntar_entrenador(d)
            extra["certeza"] = Participante.Certeza.PENDIENTE
        t = d["torneo"]
        nombre = d.get("nombre") or (d["jugador"].nombre if d.get("jugador") else "")
        historial.registrar(user, f"Apuntar a {nombre} en «{t.nombre}»", t.id)
        p = serializer.save(**extra)
        if not manda(user):
            avisar_head_coach(p, user)

    def perform_update(self, serializer):
        p = serializer.instance
        if not manda(self.request.user):
            raise PermissionDenied("Mover o confirmar jugadores lo hacen los head coaches y dirección.")
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
        user = self.request.user
        if manda(user):
            self._de_mi_grupo(instance.jugador)
        elif not (instance.apuntado_por_id == user.id
                  and instance.certeza == Participante.Certeza.PENDIENTE):
            raise PermissionDenied("Solo puedes quitar a quien apuntaste tú mientras siga pendiente; "
                                   "lo demás lo cambian los head coaches y dirección.")
        historial.registrar(user, f"Quitar a {instance.nombre} de «{instance.torneo.nombre}»",
                            instance.torneo_id)
        instance.delete()

    @action(detail=False, methods=["get"])
    def por_confirmar(self, request):
        """Lo que han apuntado los entrenadores y falta confirmar, en torneos
        que no han acabado. Dirección lo ve todo; un head coach, lo de su
        grupo; un entrenador, lo que apuntó él."""
        user = request.user
        qs = (self.get_queryset()
              .filter(certeza=Participante.Certeza.PENDIENTE, apuntado_por__isnull=False,
                      torneo__fecha_fin__gte=date.today())
              .order_by("torneo__fecha_inicio", "torneo__nombre", "nombre"))
        if not user.is_superadmin:
            if es_coach(user):
                qs = qs.filter(jugador__in=Jugador.objects.filter(_q_de_mi_grupo(user)))
            else:
                qs = qs.filter(apuntado_por=user)
        filas = list(qs)
        datos = ParticipanteSerializer(filas, many=True, context=self.get_serializer_context()).data
        for fila, p in zip(datos, filas):
            fila["torneo_detalle"] = {
                "id": p.torneo_id, "nombre": p.torneo.nombre, "fecha_inicio": p.torneo.fecha_inicio,
                "fecha_fin": p.torneo.fecha_fin, "qualy_inicio": p.torneo.qualy_inicio,
                "cierre_inscripcion": p.torneo.cierre_inscripcion,
            }
        return Response(datos)

    @action(detail=False, methods=["get"])
    def jugadores(self, request):
        """El desplegable de apuntar: los jugadores de su grupo, con su
        entrenador según Grupos."""
        qs = jugadores_apuntables(request.user).select_related(
            "entrenador_responsable").prefetch_related("cogestores")
        return Response([{"id": j.id, "nombre": j.nombre, "entrenador": entrenador_de(j)} for j in qs])


class CambioTorneoViewSet(viewsets.ViewSet):
    """Deshacer: cada uno, lo suyo, del último cambio hacia atrás (también
    el entrenador, que solo apunta y quita lo que apuntó)."""

    permission_classes = [ApuntanTambienEntrenadores]

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
