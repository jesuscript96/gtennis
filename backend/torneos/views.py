from collections import defaultdict
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.utils.http import content_disposition_header
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response

from academy.models import Aviso, Coach, Entrenador, Jugador, VacacionesEntrenador
from academy.permissions import es_coordinador_tardes, es_direccion, lleva_torneos

from . import categorias as cats
from . import circuito, historial, mensual, pdf, por_jugador
from .models import CambioTorneo, CorreoTorneos, NormasTorneos, Participante, Torneo
from .serializers import (
    ParticipanteSerializer, TorneoListaSerializer, TorneoSerializer, de_baja, entrenador_de, nombre_de,
)


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
    """Head coach, quien coordina Competición de tardes (25/11/2026) o
    dirección: crean y editan torneos, y apuntan, validan, mueven y quitan a
    los jugadores de su grupo."""
    return lleva_torneos(user)


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


# Head coaches que en torneos llevan a toda la academia y no solo a su grupo:
# apuntan, mueven, confirman y quitan a cualquiera (10/11/2026, Pablo). Los de
# Competición de tardes no: esos solo existen para los informes.
TORNEOS_TODA_LA_ACADEMIA = {"pablo.gil"}


TARDES = Q(escuela__solo_informes=True)


def _q_de_mi_grupo(user):
    """Los jugadores que alguien lleva en los torneos, según Grupos: el
    entrenador, los de su columna (es su responsable o comparte la gestión);
    el head coach, los de las columnas de sus entrenadores y las altas que aún
    no tienen entrenador (si está en TORNEOS_TODA_LA_ACADEMIA, todos). None =
    todos (dirección).

    Los de Competición de tardes (escuela «solo informes») los lleva quien
    coordina tardes (25/11/2026, Alberto Sanz); a los head coaches no les
    entran, aunque no tengan entrenador.

    03/11/2026: antes valía lo que cada uno ve en Mis jugadores, y ahí entran
    los porcentajes (con quién entrena), el resto de su color y los invitados:
    a Álvaro le salían 24 jugadores para apuntar y en Grupos tiene 6."""
    if user.is_superadmin:
        return None
    q = Q(pk__in=[])
    coach = getattr(user, "coach", None)
    ent = getattr(user, "entrenador", None)
    if coach is not None and coach.activo:
        if user.username in TORNEOS_TODA_LA_ACADEMIA:
            q = ~TARDES
        else:
            ents = coach.entrenadores.all()
            q = ((Q(entrenador_responsable__isnull=True) & ~TARDES) | Q(entrenador_responsable__in=ents)
                 | Q(cogestores__in=ents))
    elif ent is not None:
        q = Q(entrenador_responsable=ent) | Q(cogestores=ent)
    if es_coordinador_tardes(user):
        q |= TARDES
    return q


def inicio_de(torneo):
    """Primer día que ocupa el torneo: la previa, si la tiene."""
    return min(d for d in (torneo.qualy_inicio, torneo.fecha_inicio) if d)


def jugadores_apuntables(user, torneo=None):
    """A quién ofrece el desplegable de apuntar: los de su grupo que siguen
    entrenando, sin invitados. Con `torneo`, tampoco los que se dan de baja
    antes de que empiece (10/11/2026)."""
    dia = max(date.today(), inicio_de(torneo)) if torneo is not None else date.today()
    # Los de Competición de tardes tienen la ficha inactiva (no van al
    # cuadrante) pero sí juegan torneos: para ellos solo cuenta la fecha de baja.
    qs = (Jugador.objects.filter(Q(activo=True) | TARDES, invitaciones__isnull=True)
          .filter(Q(fecha_baja__isnull=True) | Q(fecha_baja__gte=dia)))
    q = _q_de_mi_grupo(user)
    return (qs if q is None else qs.filter(q)).distinct().order_by("nombre")


def es_de_mi_grupo(user, jugador):
    q = _q_de_mi_grupo(user)
    return q is None or Jugador.objects.filter(q, pk=jugador.pk).exists()


def avisar_direccion(participantes, usuario):
    """Un head coach ha validado inscripciones: a dirección le queda darles el
    visto bueno final (25/11/2026). Un aviso por cada vez que valida, no uno
    por jugador."""
    if not participantes or not circuito.hace_de_head_coach(usuario):
        return
    quien = nombre_de(usuario)
    n = len(participantes)
    lista = ", ".join(f"{p.nombre} ({p.torneo.nombre})" for p in participantes[:6])
    if n > 6:
        lista += f" y {n - 6} más"
    titulo = (f"{quien} valida a {participantes[0].nombre} en «{participantes[0].torneo.nombre}»" if n == 1
              else f"{quien} valida {n} inscripciones a torneos")
    Aviso.objects.create(
        para_direccion=True, tipo=Aviso.Tipo.GENERAL, titulo=titulo[:160],
        mensaje=f"{lista}. Te falta el visto bueno final: en Torneos, «Por validar».")


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
    `?q=` (nombre, lugar, circuito, jugador), `?circuito=` (se puede repetir:
    varios circuitos a la vez, 26/11/2026), `?jugador=<id>`,
    `?entrenador=<id>` (acompaña), `?con_jugadores=1`.
    """

    permission_classes = [SoloDireccionOCoach]
    pagination_class = None

    def get_serializer_class(self):
        return TorneoListaSerializer if self.action == "list" else TorneoSerializer

    def get_queryset(self):
        qs = (Torneo.objects
              .prefetch_related("participantes__apuntado_por__entrenador", "acompanantes",
                                "participantes__validado_coach_por__entrenador",
                                "participantes__confirmado_por__entrenador",
                                "participantes__jugador__entrenador_responsable",
                                "participantes__jugador__cogestores",
                                "participantes__jugador__categoria_torneos",
                                "participantes__jugador__escuela")
              .annotate(_n_jug=Count("participantes", distinct=True)))
        p = self.request.query_params
        if p.get("desde"):
            qs = qs.filter(fecha_fin__gte=p["desde"])
        if p.get("hasta"):
            # La previa también cuenta: un torneo cuya previa cae en el tramo sale.
            qs = qs.filter(Q(fecha_inicio__lte=p["hasta"]) | Q(qualy_inicio__lte=p["hasta"]))
        circuitos = [c for c in p.getlist("circuito") if c]
        if circuitos:
            qs = qs.filter(circuito__in=circuitos)
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

    def _assert_sin_ajenos(self, torneo):
        """Un torneo con jugadores de otro grupo solo lo borra (o lo funde)
        dirección (10/11/2026): si no, un head coach se lleva por delante a
        jugadores que no puede tocar."""
        user = self.request.user
        if es_direccion(user):
            return
        ajenos = [p.nombre for p in torneo.participantes.select_related("jugador")
                  if p.jugador is not None and not es_de_mi_grupo(user, p.jugador)]
        if ajenos:
            raise PermissionDenied(
                f"Este torneo tiene jugadores de otro grupo ({', '.join(ajenos[:3])}"
                f"{'…' if len(ajenos) > 3 else ''}): solo dirección lo borra.")

    def perform_destroy(self, instance):
        self._assert_sin_ajenos(instance)
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
                 "fecha_borrado": t.fecha_borrado, "fecha_inicio": t.fecha_inicio, "n_jugadores": t.n}
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
        tarde libre no impide viajar.

        Tampoco cuenta la ausencia con motivo «Torneo» (10/11/2026): es la que
        se le pone en el cuadrante justo porque acompaña, y le escondía del
        desplegable del torneo al que va."""
        p = request.query_params
        # Unas horas sueltas («hasta las 10:00») tampoco impiden viajar.
        vac = VacacionesEntrenador.objects.filter(
            ambito__in=[VacacionesEntrenador.Ambito.DIA, VacacionesEntrenador.Ambito.MANANA,
                        VacacionesEntrenador.Ambito.TARDE],
            hora_desde__isnull=True, hora_hasta__isnull=True).exclude(motivo__icontains="torneo")
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
        self._assert_sin_ajenos(otro)
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
            t.categorias = cats.ordenar(t.categorias + otro.categorias)
            alias = [x for x in (t.alias + " | " + otro.nombre + " | " + otro.alias).split(" | ") if x.strip()]
            t.alias = " | ".join(dict.fromkeys(alias))[:300]
            t.fuente = ", ".join(x for x in (t.fuente, otro.fuente) if x)[:300]
            if otro.notas and otro.notas not in t.notas:
                t.notas = f"{t.notas}\n{otro.notas}".strip()
            if otro.acompanante_nota and otro.acompanante_nota not in t.acompanante_nota:
                t.acompanante_nota = ", ".join(x for x in (t.acompanante_nota, otro.acompanante_nota) if x)[:120]
            t.cierre_inscripcion = t.cierre_inscripcion or otro.cierre_inscripcion
            t.fecha_borrado = t.fecha_borrado or otro.fecha_borrado
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

    @action(detail=False, methods=["get"], url_path=r"jugador/(?P<jugador_id>\d+)")
    def de_jugador(self, request, jugador_id=None):
        """La página de un jugador (25/11/2026): los torneos que tiene por
        delante, confirmados y por confirmar, y cuántos ha jugado ya."""
        j = get_object_or_404(Jugador, pk=jugador_id)
        desde = parse_date(request.query_params.get("desde") or "") or date.today()
        filas = por_jugador.torneos_de(j, desde=desde, con_cancelados=True)
        return Response({
            "jugador": por_jugador.ficha(j), "desde": desde, "torneos": filas,
            "resumen": por_jugador.resumen([f for f in filas if not f["cancelado"]]),
            "jugados": Participante.objects.filter(jugador=j, torneo__fecha_fin__lt=desde)
            .exclude(torneo__estado=Torneo.Estado.CANCELADO).count(),
        })

    @action(detail=False, methods=["get"], url_path=r"jugador/(?P<jugador_id>\d+)/pdf")
    def pdf_jugador(self, request, jugador_id=None):
        """Lo mismo en un PDF para dárselo a la familia (sin las notas internas
        ni los torneos cancelados). `?idioma=EN` lo saca en inglés."""
        j = get_object_or_404(Jugador, pk=jugador_id)
        desde = parse_date(request.query_params.get("desde") or "") or date.today()
        idioma = "EN" if request.query_params.get("idioma") == "EN" else "ES"
        contenido = pdf.generar(por_jugador.ficha(j), por_jugador.torneos_de(j, desde=desde),
                                idioma=idioma, foto=pdf.foto_de(j))
        respuesta = HttpResponse(contenido, content_type="application/pdf")
        respuesta["Content-Disposition"] = content_disposition_header(True, pdf.nombre_fichero(j.nombre))
        return respuesta

    @action(detail=False, methods=["get"])
    def por_jugador(self, request):
        """Una fila por jugador con sus torneos ordenados por fecha. Los
        dados de baja van marcados (`de_baja`): la pantalla los esconde si no
        se piden (10/11/2026)."""
        por = {}
        qs = Participante.objects.select_related("torneo", "jugador__escuela").order_by("torneo__fecha_inicio")
        for p in qs:
            clave = p.jugador_id or f"n:{p.nombre}"
            d = por.setdefault(clave, {
                "jugador": p.jugador_id, "nombre": p.jugador.nombre if p.jugador else p.nombre,
                "en_academia": p.jugador is not None, "de_baja": de_baja(p.jugador), "torneos": [],
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
    jugadores de su grupo (Pablo, a toda la academia: TORNEOS_TODA_LA_ACADEMIA);
    a los nombres sin ficha los toca cualquiera.

    Desde el 03/11/2026 los entrenadores apuntan a sus jugadores (los de su
    columna en Grupos) a torneos que ya existen. Lo suyo entra como
    pendiente y avisa al head coach; solo pueden quitar lo que apuntaron ellos
    mientras siga pendiente. Mover y confirmar, head coaches y dirección."""

    serializer_class = ParticipanteSerializer
    permission_classes = [ApuntanTambienEntrenadores]
    pagination_class = None

    def get_queryset(self):
        qs = (Participante.objects
              .select_related("jugador__entrenador_responsable", "jugador__categoria_torneos", "torneo",
                              "jugador__escuela",
                              "apuntado_por__entrenador", "validado_coach_por__entrenador",
                              "confirmado_por__entrenador")
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
        self._no_de_baja(jugador, t)
        if not jugadores_apuntables(user).filter(pk=jugador.pk).exists():
            raise PermissionDenied(f"{jugador.nombre} no está en tu columna de Grupos.")
        if t.fecha_fin < date.today():
            raise ValidationError({"torneo": "Ese torneo ya ha terminado."})
        if t.estado == Torneo.Estado.CANCELADO:
            raise ValidationError({"torneo": "Ese torneo está cancelado."})

    def _no_de_baja(self, jugador, torneo):
        """Para todos: no se apunta a quien ya no entrena cuando empieza el
        torneo (10/11/2026)."""
        if jugador is not None and de_baja(jugador, inicio_de(torneo)):
            cuando = f" desde el {jugador.fecha_baja:%d/%m/%Y}" if jugador.fecha_baja else ""
            raise ValidationError({"detail": f"{jugador.nombre} está dado de baja{cuando}."})

    def _de_su_categoria(self, jugador, torneo):
        """Para todos, también dirección: solo los de la categoría del torneo
        o una más pequeña (03/11/2026)."""
        if jugador is not None and not cats.puede_jugar(jugador, torneo):
            # En «detail», que es lo que enseña la pantalla tal cual.
            raise ValidationError({"detail": cats.motivo(jugador, torneo)})

    def perform_create(self, serializer):
        d = serializer.validated_data
        user = self.request.user
        extra = {"apuntado_por": user}
        if manda(user):
            self._de_mi_grupo(d.get("jugador"))
            self._no_de_baja(d.get("jugador"), d["torneo"])
        else:
            self._puede_apuntar_entrenador(d)
            extra["certeza"] = Participante.Certeza.PENDIENTE
        self._de_su_categoria(d.get("jugador"), d["torneo"])
        t = d["torneo"]
        nombre = d.get("nombre") or (d["jugador"].nombre if d.get("jugador") else "")
        historial.registrar(user, f"Apuntar a {nombre} en «{t.nombre}»", t.id)
        p = serializer.save(**extra)
        if manda(user):
            # Lo que apunta un head coach ya lleva su visto bueno y espera a
            # dirección; lo de dirección queda confirmado (25/11/2026).
            p.save(update_fields=circuito.marcar(p, user))
        else:
            avisar_head_coach(p, user)

    def perform_update(self, serializer):
        p = serializer.instance
        if not manda(self.request.user):
            raise PermissionDenied("Mover o confirmar jugadores lo hacen los head coaches y dirección.")
        self._de_mi_grupo(p.jugador)
        user = self.request.user
        destino = serializer.validated_data.get("torneo")
        # La certeza no se escribe tal cual: pedir «CONFIRMADO» o
        # «VALIDADO_COACH» es validar, y cada uno llega hasta su altura.
        pide = serializer.validated_data.pop("certeza", None)
        if destino is not None and destino.pk != p.torneo_id:
            self._de_su_categoria(p.jugador, destino)
            historial.registrar(user, f"Mover a {p.nombre} de «{p.torneo.nombre}» a «{destino.nombre}»",
                                p.torneo_id, destino.pk)
            p = serializer.save()
            # Reasignado: queda a la altura de quien lo mueve (el head coach lo
            # deja para dirección; dirección, confirmado).
            p.save(update_fields=circuito.marcar(p, user))
            return
        if pide in (Participante.Certeza.CONFIRMADO, Participante.Certeza.VALIDADO_COACH):
            if not circuito.puede_subir(p, user):
                raise ValidationError({"detail": f"{p.nombre} ya tiene tu visto bueno en «{p.torneo.nombre}»."})
            historial.registrar(user, f"Validar a {p.nombre} en «{p.torneo.nombre}»", p.torneo_id)
            p = serializer.save()
            p.save(update_fields=circuito.marcar(p, user))
            avisar_direccion([p], user)
            return
        if pide is not None:
            raise ValidationError({"detail": "Para quitar un visto bueno, mueve al jugador o quítalo del torneo."})
        historial.registrar(user, f"Cambios en {p.nombre} en «{p.torneo.nombre}»", p.torneo_id)
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
        """Lo que falta por validar en torneos que no han acabado (25/11/2026):
        lo pendiente del head coach (apuntado por un entrenador o deducido del
        Excel) y lo que el head coach ya validó y espera a dirección. Dirección
        lo ve todo; un head coach, lo de su grupo; un entrenador, lo que apuntó
        él. Cada fila dice a quién espera y si quien pregunta puede validarla."""
        user = request.user
        C = Participante.Certeza
        qs = (self.get_queryset()
              .filter(certeza__in=[C.PENDIENTE, C.DEDUCIDO, C.VALIDADO_COACH],
                      torneo__fecha_fin__gte=date.today())
              .exclude(torneo__estado=Torneo.Estado.CANCELADO)
              .order_by("torneo__fecha_inicio", "torneo__nombre", "nombre"))
        if not user.is_superadmin:
            if circuito.hace_de_head_coach(user):
                q = _q_de_mi_grupo(user)
                qs = qs.filter(jugador__in=Jugador.objects.filter(q) if q is not None else Jugador.objects.all())
            else:
                qs = qs.filter(apuntado_por=user)
        filas = list(qs)
        datos = ParticipanteSerializer(filas, many=True, context=self.get_serializer_context()).data
        for fila, p in zip(datos, filas):
            fila["espera"] = circuito.espera_a(p.certeza)
            fila["puede_validar"] = manda(user) and circuito.puede_subir(p, user)
            fila["validado_coach_por_nombre"] = nombre_de(p.validado_coach_por)
            fila["torneo_detalle"] = {
                "id": p.torneo_id, "nombre": p.torneo.nombre, "fecha_inicio": p.torneo.fecha_inicio,
                "fecha_fin": p.torneo.fecha_fin, "qualy_inicio": p.torneo.qualy_inicio,
                "cierre_inscripcion": p.torneo.cierre_inscripcion,
            }
        return Response(datos)

    @action(detail=False, methods=["post"])
    def validar(self, request):
        """Dar el visto bueno a varios a la vez (`ids`). El head coach los deja
        validados para dirección; dirección, confirmados. Se salta, diciendo
        por qué, lo que no es de su grupo o ya tiene su visto bueno."""
        user = request.user
        if not manda(user):
            raise PermissionDenied("Validan los head coaches y dirección.")
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            raise ValidationError({"ids": "Indica a quién validar."})
        ps = list(self.get_queryset().filter(pk__in=ids).order_by("torneo__fecha_inicio", "nombre"))
        validos, saltados = [], []
        for p in ps:
            if p.jugador is not None and not es_de_mi_grupo(user, p.jugador):
                saltados.append(f"{p.nombre}: no es de tu grupo")
            elif not circuito.puede_subir(p, user):
                saltados.append(f"{p.nombre}: ya tiene tu visto bueno")
            else:
                validos.append(p)
        if validos:
            que = (f"Validar a {validos[0].nombre} en «{validos[0].torneo.nombre}»" if len(validos) == 1
                   else f"Validar {len(validos)} inscripciones a torneos")
            with transaction.atomic():
                historial.registrar(user, que, *[p.torneo_id for p in validos])
                for p in validos:
                    p.save(update_fields=circuito.marcar(p, user))
            avisar_direccion(validos, user)
        return Response({"validados": len(validos), "saltados": saltados})

    @action(detail=False, methods=["get"])
    def jugadores(self, request):
        """El desplegable de apuntar: los jugadores de su grupo, con su
        entrenador según Grupos. Con `?torneo=`, solo los que entran por
        categoría, con la suya ese año (None si no consta su nacimiento)."""
        t = None
        if request.query_params.get("torneo"):
            t = get_object_or_404(Torneo, pk=request.query_params["torneo"])
        qs = jugadores_apuntables(request.user, t).select_related(
            "entrenador_responsable", "categoria_torneos").prefetch_related("cogestores")
        filas = []
        for j in qs:
            if t is not None and not cats.puede_jugar(j, t):
                continue
            cat = cats.categoria_de(j, t.fecha_inicio.year if t else date.today().year)
            filas.append({"id": j.id, "nombre": j.nombre, "entrenador": entrenador_de(j),
                          "categoria": cats.NOMBRE[cat] if cat else None})
        return Response(filas)


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


class SoloHeadCoachesYDireccion(BasePermission):
    message = "Los correos a las familias los validan los head coaches y dirección."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and manda(request.user))


def _mes(valor):
    """«2026-12» o «2026-12-01» → 1 de diciembre de 2026; si no, el mes actual."""
    d = parse_date(f"{valor}-01" if valor and len(valor) == 7 else (valor or ""))
    return (d or date.today()).replace(day=1)


class CorreoTorneosViewSet(viewsets.ViewSet):
    """Los correos del día 1 a las familias (25/11/2026). Dirección ve y valida
    todos; cada head coach, los de su grupo. Validado = sale en el minuto
    siguiente (lo manda el programador)."""

    permission_classes = [SoloHeadCoachesYDireccion]

    def _correo(self, pk):
        c = mensual.visibles(self.request.user).filter(pk=pk).first()
        if c is None:
            raise PermissionDenied("Ese correo no es de tu grupo.")
        return c

    def _fila(self, c):
        r = mensual.resumen_de(c)
        pendiente = c.estado == CorreoTorneos.Estado.PENDIENTE
        return {
            "id": c.id, "jugador": c.jugador_id, "nombre": c.jugador.nombre,
            "entrenador": entrenador_de(c.jugador), "mes": c.mes,
            "estado": c.estado, "estado_display": c.get_estado_display(),
            "idioma": mensual.idioma_de(c.jugador) if pendiente else c.idioma,
            "destinatarios": mensual.destinatarios_de(c.jugador) if pendiente else c.destinatarios,
            "n_torneos": r["total"], "por_confirmar": r["por_confirmar"],
            "inscripciones_abiertas": r["inscripciones_abiertas"], "proximo_cierre": r["proximo_cierre"],
            "validado_por_nombre": nombre_de(c.validado_por), "validado_en": c.validado_en,
            "enviado_en": c.enviado_en, "envio_error": c.envio_error,
            "puede_validar": mensual.puede_validar(self.request.user, c),
        }

    def _responder(self, fn, *args):
        try:
            return fn(*args)
        except mensual.CorreoError as e:
            raise ValidationError({"detail": str(e)})

    def list(self, request):
        from evaluaciones.informes import correo_configurado

        mes = _mes(request.query_params.get("mes"))
        qs = (mensual.visibles(request.user).filter(mes=mes)
              .select_related("jugador__entrenador_responsable", "validado_por__entrenador")
              .prefetch_related("jugador__cogestores").order_by("jugador__nombre"))
        normas = NormasTorneos.actuales()
        return Response({
            "mes": mes, "correo_activo": correo_configurado(),
            "hay_normas": bool(normas.texto.strip()), "puede_generar": es_direccion(request.user),
            "filas": [self._fila(c) for c in qs],
        })

    def retrieve(self, request, pk=None):
        """La vista previa: el correo tal como saldría (o salió)."""
        c = self._correo(pk)
        asunto, texto, html = mensual.mensaje(c)
        return Response({**self._fila(c), "asunto": asunto, "texto": texto, "html": html,
                         "responder_a": mensual.responder_a(c.jugador)})

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        c = self._correo(pk)
        nombre, contenido = mensual.pdf_de(c)
        respuesta = HttpResponse(contenido, content_type="application/pdf")
        respuesta["Content-Disposition"] = content_disposition_header(True, nombre)
        return respuesta

    @action(detail=False, methods=["post"])
    def validar(self, request):
        """`ids`: los que se validan tal cual. Con uno solo se pueden mandar
        también los `destinatarios` escritos a mano (se guardan en la ficha)."""
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            raise ValidationError({"ids": "Indica qué correos validar."})
        destinatarios = request.data.get("destinatarios") if len(ids) == 1 else None
        validados, saltados = 0, []
        correos = list(mensual.visibles(request.user).filter(pk__in=ids).order_by("jugador__nombre"))
        if len(correos) < len(set(ids)):
            saltados.append("Hay correos de jugadores que no son de tu grupo: los valida su head coach o dirección.")
        for c in correos:
            try:
                mensual.validar(c, request.user, destinatarios)
                validados += 1
            except mensual.CorreoError as e:
                saltados.append(str(e))
        if len(ids) == 1 and saltados:
            raise ValidationError({"detail": saltados[0]})
        return Response({"validados": validados, "saltados": saltados})

    @action(detail=True, methods=["post"])
    def descartar(self, request, pk=None):
        return Response(self._fila(self._responder(mensual.descartar, self._correo(pk), request.user)))

    @action(detail=True, methods=["post"])
    def recuperar(self, request, pk=None):
        return Response(self._fila(self._responder(mensual.recuperar, self._correo(pk), request.user)))

    @action(detail=True, methods=["post"])
    def reintentar(self, request, pk=None):
        return Response(self._fila(self._responder(mensual.reintentar, self._correo(pk), request.user)))

    @action(detail=False, methods=["post"])
    def generar(self, request):
        """Prepara los que falten del mes (lo hace solo el programador el día
        1; esto es para dirección, por si alguien se apuntó después)."""
        if not es_direccion(request.user):
            raise PermissionDenied("Prepara los correos dirección.")
        mes = _mes(request.data.get("mes"))
        return Response({"creados": mensual.generar(mes, request.user), "mes": mes})

    @action(detail=False, methods=["get", "put"])
    def normas(self, request):
        """Las normas de torneos que van al final del correo. Las escribe dirección."""
        n = NormasTorneos.actuales()
        if request.method == "PUT":
            if not es_direccion(request.user):
                raise PermissionDenied("Las normas las escribe dirección.")
            n.texto = str(request.data.get("texto", n.texto))
            n.texto_en = str(request.data.get("texto_en", n.texto_en))
            n.actualizado_por = request.user
            n.save()
        return Response({"texto": n.texto, "texto_en": n.texto_en,
                         "actualizado_en": n.actualizado_en if n.pk else None,
                         "actualizado_por_nombre": nombre_de(n.actualizado_por),
                         "puede_editar": es_direccion(request.user)})
