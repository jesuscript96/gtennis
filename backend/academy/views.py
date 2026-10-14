from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import pesos
from .models import (
    Aviso,
    Coach,
    Contrato,
    Division,
    Entrenador,
    Escuela,
    Feedback,
    Invitado,
    HorarioEntrenador,
    HorarioJugador,
    Jugador,
    Pista,
    PreferenciaPareja,
    PreferenciaSuperficie,
    Rencilla,
    ResponsableJugador,
    Sede,
    TareaMantenimiento,
    Turno,
    VacacionesEntrenador,
    VetoEntrenador,
)
from .permissions import DireccionOrCoachWrite, ReadOnlyOrDireccion
from .scope import (
    coaches_del_entrenador,
    coaches_visibles,
    entrenadores_visibles,
    jugadores_visibles,
)
from .serializers import (
    AvisoSerializer,
    CoachSerializer,
    ContratoSerializer,
    DivisionSerializer,
    EntrenadorSerializer,
    EscuelaSerializer,
    FeedbackSerializer,
    InvitadoSerializer,
    JugadorSerializer,
    JugadorTurnosSerializer,
    PistaSerializer,
    PreferenciaSuperficieSerializer,
    RencillaSerializer,
    ResponsableJugadorSerializer,
    SedeSerializer,
    TareaMantenimientoSerializer,
    TurnoSerializer,
    VacacionesEntrenadorSerializer,
)


class SedeViewSet(viewsets.ModelViewSet):
    queryset = Sede.objects.prefetch_related("pistas").all()
    serializer_class = SedeSerializer
    permission_classes = [ReadOnlyOrDireccion]


class PistaViewSet(viewsets.ModelViewSet):
    queryset = Pista.objects.select_related("sede").all()
    serializer_class = PistaSerializer
    permission_classes = [ReadOnlyOrDireccion]


class TurnoViewSet(viewsets.ModelViewSet):
    queryset = Turno.objects.all()
    serializer_class = TurnoSerializer
    permission_classes = [ReadOnlyOrDireccion]

    def get_queryset(self):
        """Por defecto solo los turnos en uso.

        Las franjas de escuela de noche existen en la base pero están fuera
        del reparto; si la API las devuelve, acaban en los desplegables y
        alguien acaba eligiendo un turno que no se monta. Dirección puede
        verlas todas con `?todos=1`.
        """
        qs = Turno.objects.all()
        if self.request.query_params.get("todos"):
            return qs
        return qs.filter(activo=True)


class DivisionViewSet(viewsets.ModelViewSet):
    queryset = Division.objects.all()
    serializer_class = DivisionSerializer
    permission_classes = [ReadOnlyOrDireccion]


class EntrenadorViewSet(viewsets.ModelViewSet):
    queryset = Entrenador.objects.all()
    serializer_class = EntrenadorSerializer
    permission_classes = [DireccionOrCoachWrite]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nombre"]
    ordering_fields = ["nombre", "activo"]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return super().get_queryset()
        return entrenadores_visibles(user)

    def perform_create(self, serializer):
        # Un coach que da de alta un entrenador lo añade a su propio equipo.
        ent = serializer.save()
        coach = getattr(self.request.user, "coach", None)
        if coach is not None:
            coach.entrenadores.add(ent)


class CoachViewSet(viewsets.ModelViewSet):
    """Gestión de coaches (#16). Solo la dirección deportiva los administra;
    un coach puede consultar su propia ficha."""

    queryset = Coach.objects.prefetch_related("entrenadores").all()
    serializer_class = CoachSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        u = self.request.user
        qs = Coach.objects.prefetch_related("entrenadores")
        if u.is_superadmin:
            return qs
        coach = getattr(u, "coach", None)
        return qs.filter(pk=coach.pk) if coach else qs.none()

    def _assert_direccion(self):
        if not self.request.user.is_superadmin:
            raise PermissionDenied("Solo la dirección deportiva gestiona coaches.")

    def perform_create(self, serializer):
        self._assert_direccion()
        serializer.save()

    def perform_update(self, serializer):
        u = self.request.user
        if not u.is_superadmin:
            coach = getattr(u, "coach", None)
            if coach is None or serializer.instance.pk != coach.pk:
                raise PermissionDenied("No puedes editar este coach.")
        serializer.save()

    def perform_destroy(self, instance):
        self._assert_direccion()
        instance.delete()


class JugadorViewSet(viewsets.ModelViewSet):
    queryset = Jugador.objects.filter(activo=True).select_related("division", "entrenador_responsable").all()
    serializer_class = JugadorSerializer

    def get_serializer_class(self):
        """El entrenador no gestiona la ficha del alumno.

        Lo único que declara es cuándo entrena: su franja de mañana, la de
        tarde y los cambios por día. Datos personales, división, escuela,
        contactos y notas quedan fuera de su serializer — no los ve ni los
        puede escribir. Dirección y coaches siguen con la ficha completa.
        """
        user = self.request.user
        if (user.is_authenticated and not user.is_superadmin
                and not getattr(user, "is_coach", False)
                and getattr(user, "entrenador", None) is not None):
            return JugadorTurnosSerializer
        return JugadorSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nombre"]
    ordering_fields = ["nombre", "edad"]

    def get_queryset(self):
        base = Jugador.objects.select_related(
            "division", "entrenador_responsable", "escuela"
        ).prefetch_related("cogestores")
        # La lista enseña solo a los que están en activo, pero una ficha
        # concreta se abre siempre: si no, al alumno que se dio de baja no hay
        # manera de volver a darle de alta ni de corregirle nada — desaparece.
        pide_todos = self.request.query_params.get("todos") in (
            "1", "true", "si", "sí",
        )
        if self.action == "list" and not pide_todos:
            base = base.filter(activo=True)
        escuela = self.request.query_params.get("escuela")
        if escuela == "sin":
            base = base.filter(escuela__isnull=True)
        elif escuela and escuela.isdigit():
            base = base.filter(escuela_id=escuela)
        user = self.request.user
        if not user.is_authenticated:
            return base
        return jugadores_visibles(user, base=base)

    DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

    @action(detail=True, methods=["get"])
    def agenda(self, request, pk=None):
        """La agenda del propio alumno: lo que tiene hoy y lo que tiene esta
        semana.

        El entrenador abre a un jugador suyo y quiere saber cuándo entrena y
        con quién, no solo qué franjas tiene declaradas. Si la semana ya está
        generada se devuelve el cuadrante real (pista, hora, entrenador y
        compañeros); si todavía no lo está, se devuelve lo previsto según su
        horario, marcado como tal para no confundir una cosa con la otra.
        """
        from collections import defaultdict
        from datetime import date, timedelta

        from scheduling.models import (
            Asignacion, AusenciaJugador, Disponibilidad, Estado, Semana,
        )

        jugador = self.get_object()
        try:
            fecha = date.fromisoformat(request.query_params["fecha"])
        except (KeyError, ValueError):
            fecha = date.today()
        lunes = fecha - timedelta(days=fecha.weekday())
        semana = Semana.objects.filter(fecha_inicio=lunes).first()

        sesiones = defaultdict(list)
        if semana is not None:
            mias = list(
                Asignacion.objects.filter(semana=semana, jugador=jugador)
                .select_related("turno", "pista", "pista__sede", "entrenador")
                .order_by("dia", "turno__orden")
            )
            companeros = defaultdict(list)
            if mias:
                filtro = Q()
                for a in mias:
                    filtro |= Q(dia=a.dia, turno_id=a.turno_id, pista_id=a.pista_id)
                for otro in (
                    Asignacion.objects.filter(semana=semana).filter(filtro)
                    .exclude(jugador=jugador).select_related("jugador")
                ):
                    companeros[(otro.dia, otro.turno_id, otro.pista_id)].append(
                        otro.jugador.nombre
                    )
            from scheduling.serializers import falta_de

            faltas = {}
            for a in mias:
                inicio, fin = a.turno.horas(lunes + timedelta(days=a.dia))
                sesiones[a.dia].append({
                    "falta": falta_de(a, faltas),
                    "turno": a.turno.codigo,
                    "hora_inicio": inicio.strftime("%H:%M"),
                    "hora_fin": fin.strftime("%H:%M"),
                    "pista": a.pista.numero,
                    "sede": a.pista.sede.nombre,
                    "es_satelite": a.pista.sede.es_satelite,
                    "entrenador": a.entrenador.nombre if a.entrenador_id else None,
                    "estado": a.estado,
                    "companeros": sorted(
                        companeros.get((a.dia, a.turno_id, a.pista_id), [])
                    ),
                    "previsto": False,
                })

        # Lo previsto: su horario declarado, para los días que el cuadrante aún
        # no cubre. Sin esto la pantalla sale vacía hasta que dirección genera
        # la semana, que es justo cuando el entrenador la mira.
        turnos = {t.id: t for t in Turno.objects.all()}
        horario = {h.dia: h for h in jugador.horario.all()}
        for d in range(6):
            if sesiones[d]:
                continue
            fila = horario.get(d)
            if fila is not None:
                ids = [fila.turno_manana_id, fila.turno_tarde_id]
            else:
                ids = [jugador.turno_manana_id, jugador.turno_tarde_id]
            dia_fecha = lunes + timedelta(days=d)
            for tid in ids:
                t = turnos.get(tid)
                if t is None:
                    continue
                inicio, fin = t.horas(dia_fecha)
                sesiones[d].append({
                    "turno": t.codigo,
                    "hora_inicio": inicio.strftime("%H:%M"),
                    "hora_fin": fin.strftime("%H:%M"),
                    "pista": None, "sede": None, "es_satelite": False,
                    "entrenador": None, "estado": None, "companeros": [],
                    "previsto": True,
                })

        # Lo que su entrenador ha apuntado de más: «el jueves viene también a
        # M2». Si ya está colocado sale además como sesión; si no, sale aquí.
        extras = defaultdict(list)
        if semana is not None:
            for dsp in Disponibilidad.objects.filter(
                semana=semana, jugador=jugador, estado=Estado.EXTRA
            ):
                extras[dsp.dia].append(dsp.ambito)

        bajas = list(
            AusenciaJugador.objects.filter(
                jugador=jugador,
                fecha_inicio__lte=lunes + timedelta(days=5),
                fecha_fin__gte=lunes,
            )
        )
        hoy = date.today()
        dias = []
        for d in range(6):
            dia_fecha = lunes + timedelta(days=d)
            baja = next(
                (b for b in bajas if b.fecha_inicio <= dia_fecha <= b.fecha_fin), None
            )
            dias.append({
                "dia": d,
                "nombre": self.DIAS_SEMANA[d],
                "fecha": dia_fecha,
                "es_hoy": dia_fecha == hoy,
                "sesiones": sesiones[d],
                "alta": jugador.en_alta(dia_fecha),
                "extras": sorted(extras[d]),
                "ausencia": None if baja is None else {
                    "estado": baja.get_estado_display(),
                    "ambito": baja.get_ambito_display(),
                    "nota": baja.nota,
                },
            })
        return Response({
            "jugador": {
                "id": jugador.id,
                "nombre": jugador.nombre,
                "division": jugador.division.nivel if jugador.division_id else None,
                "escuela": jugador.escuela.nombre if jugador.escuela_id else None,
                "fecha_alta": jugador.fecha_alta,
            },
            "fecha": fecha,
            "hay_semana": semana is not None,
            "semana": None if semana is None else {
                "fecha_inicio": semana.fecha_inicio,
                "estado": semana.estado,
            },
            "hoy": next((d for d in dias if d["es_hoy"]), None),
            "dias": dias,
        })

    @action(detail=True, methods=["post", "delete"])
    def extra(self, request, pk=None):
        """Excepción puntual: ese día, en esa franja, el alumno viene aunque su
        horario no lo diga.

        La apunta su entrenador (o dirección). Queda como un parte de la semana
        con estado «viene además», que el motor lee como «entra sí o sí» cada
        vez que genera. Si la semana ya está generada, además se le busca sitio
        ahora mismo: una pista de esa franja con hueco, sin vetos y con
        compañeros a ±1 división. Si no cabe, se dice; no se le cuela.

        POST {fecha, turno, nota?}  ·  DELETE ?fecha=…&turno=…
        """
        from collections import defaultdict
        from datetime import date, timedelta

        from engine.service import hay_entrenamiento
        from scheduling.models import Asignacion, Disponibilidad, Estado, Semana

        jugador = self.get_object()
        datos = request.data if request.method == "POST" else request.query_params
        try:
            fecha = date.fromisoformat(str(datos.get("fecha")))
        except ValueError:
            return Response({"error": "Falta la fecha."}, status=400)
        turno = Turno.objects.filter(codigo=datos.get("turno"), activo=True).first()
        if turno is None:
            return Response({"error": "Esa franja no existe."}, status=400)
        dia = fecha.weekday()
        if dia > 5 or not hay_entrenamiento(dia, turno.bloque):
            return Response({"error": "Ese día no se entrena en esa franja."}, status=400)
        lunes = fecha - timedelta(days=dia)

        from scheduling.avisos_corte import avisar
        from scheduling.corte import cerrado

        # Pasado el corte de ese día (01/10/2026) el cuadrante no se toca solo:
        # se apunta, se avisa y se cambia a mano.
        cerrada = cerrado(fecha)
        if request.method == "DELETE":
            semana = Semana.objects.filter(fecha_inicio=lunes).first()
            if semana is not None:
                Disponibilidad.objects.filter(
                    semana=semana, jugador=jugador, dia=dia,
                    ambito=turno.codigo, estado=Estado.EXTRA,
                ).delete()
                if cerrada:
                    avisar(jugador, fecha, fecha, turno.codigo, "falta",
                           request.user, "ya no viene además")
                else:
                    Asignacion.objects.filter(
                        semana=semana, jugador=jugador, dia=dia, turno=turno,
                        estado=Estado.EXTRA,
                    ).delete()
            return Response(status=204)

        semana, _ = Semana.objects.get_or_create(fecha_inicio=lunes)
        Disponibilidad.objects.update_or_create(
            semana=semana, jugador=jugador, dia=dia, ambito=turno.codigo,
            defaults={"estado": Estado.EXTRA, "tardia": cerrada,
                      "nota": str(datos.get("nota", ""))[:200]},
        )
        if Asignacion.objects.filter(
            semana=semana, jugador=jugador, dia=dia, turno=turno
        ).exists():
            return Response({"ok": True, "colocado": True,
                             "mensaje": "Ya tenía sesión en esa franja."})
        if cerrada:
            avisar(jugador, fecha, fecha, turno.codigo, "viene", request.user,
                   str(datos.get("nota", ""))[:200])
            return Response({"ok": True, "colocado": False,
                             "mensaje": "Apuntado. El cuadrante de ese día ya está "
                                        "cerrado: se ha avisado para que le hagan "
                                        "hueco a mano."})
        if not semana.generado_at:
            return Response({"ok": True, "colocado": False,
                             "mensaje": "Apuntado. Entrará cuando se genere la semana."})

        # La semana ya está hecha: se le busca hueco ahora.
        vetos = set()
        for r in Rencilla.objects.filter(activa=True).filter(
            Q(jugador_a=jugador) | Q(jugador_b=jugador)
        ):
            vetos.add(r.jugador_b_id if r.jugador_a_id == jugador.id else r.jugador_a_id)
        mi_div = jugador.division.nivel if jugador.division_id else None
        por_pista = defaultdict(list)
        for a in (Asignacion.objects.filter(semana=semana, dia=dia, turno=turno)
                  .select_related("pista__sede", "jugador__division")):
            por_pista[a.pista].append(a)
        opciones = []
        for pista, filas in por_pista.items():
            tope = pista.sede.densidad_max or pista.sede.densidad_default
            if len(filas) >= tope or any(f.jugador_id in vetos for f in filas):
                continue
            divs = [f.jugador.division.nivel for f in filas if f.jugador.division_id]
            if mi_div is not None and any(abs(mi_div - d) > 1 for d in divs):
                continue
            opciones.append(((len(filas), pista.sede.es_satelite, pista.numero),
                             pista, filas))
        if not opciones:
            return Response({"ok": True, "colocado": False,
                             "mensaje": "Apuntado, pero ahora mismo no cabe en ninguna "
                                        "pista de esa franja: dirección tendrá que "
                                        "hacerle hueco."})
        _clave, pista, filas = min(opciones, key=lambda o: o[0])
        entrenador_id = next((f.entrenador_id for f in filas if f.entrenador_id), None)
        Asignacion.objects.create(
            semana=semana, dia=dia, turno=turno, pista=pista, jugador=jugador,
            entrenador_id=entrenador_id, estado=Estado.EXTRA, manual=True,
        )
        return Response({"ok": True, "colocado": True,
                         "mensaje": f"Colocado en {pista.sede.nombre} · pista {pista.numero}."})

    def perform_destroy(self, instance):
        self._assert_direccion()
        instance.delete()

    @action(detail=True, methods=["get", "post"])
    def entrenadores(self, request, pk=None):
        """Quién gestiona al alumno (responsable) y con quién entrena (porcentajes).

        GET  → {jugador, responsable, entrenadores, minimo_secundario, propuesta}
        POST → {responsable, entrenadores: [{entrenador, prioridad, porcentaje}]}
        """
        from .models import ResponsableJugador
        from .pesos import MINIMO_SECUNDARIO, errores, guardar, propuesta

        jugador = self.get_object()
        if request.method == "POST":
            from .permissions import es_coach, es_direccion

            if not (es_direccion(request.user) or es_coach(request.user)):
                raise PermissionDenied(
                    "Los porcentajes los ponen dirección y los coaches."
                )
            try:
                responsable_id = request.data.get("responsable")
                responsable_id = int(responsable_id) if responsable_id else None
                filas = [
                    (int(f["entrenador"]), int(f["prioridad"]),
                     int(f.get("porcentaje") or 0))
                    for f in request.data.get("entrenadores") or []
                ]
            except (KeyError, TypeError, ValueError):
                return Response(
                    {"detail": "Cada entrenador necesita papel y porcentaje."},
                    status=400,
                )
            fallos = errores(filas)
            ids = {e for e, _p, _c in filas} | ({responsable_id} if responsable_id else set())
            if Entrenador.objects.filter(pk__in=ids).count() != len(ids):
                fallos.append("Algún entrenador no existe.")
            if fallos:
                return Response({"detail": " ".join(fallos)}, status=400)
            # Responsable y porcentajes van juntos: o se guardan los dos o nada.
            with transaction.atomic():
                jugador.entrenador_responsable_id = responsable_id
                jugador.save(update_fields=["entrenador_responsable"])
                guardar(jugador, filas)

        filas_db = list(
            ResponsableJugador.objects.filter(jugador=jugador, activo=True)
            .select_related("entrenador")
            .order_by("prioridad", "-porcentaje_objetivo", "id")
        )
        resp_param = request.query_params.get("responsable")
        if resp_param and str(resp_param).isdigit():
            ent_resp = Entrenador.objects.filter(pk=int(resp_param)).first()
            prop = propuesta(ent_resp)
        else:
            prop = propuesta(jugador.entrenador_responsable)

        ent_ids = [e for e, _p, _c in prop]
        ent_nombres = dict(
            Entrenador.objects.filter(pk__in=ent_ids).values_list("id", "nombre")
        )

        return Response({
            "jugador": {"id": jugador.id, "nombre": jugador.nombre},
            "responsable": jugador.entrenador_responsable_id,
            "entrenadores": [
                {
                    "entrenador": r.entrenador_id,
                    "nombre": r.entrenador.nombre,
                    "prioridad": r.prioridad,
                    "porcentaje": r.porcentaje_objetivo,
                }
                for r in filas_db
            ],
            "minimo_secundario": MINIMO_SECUNDARIO,
            "propuesta": [
                {
                    "entrenador": e,
                    "nombre": ent_nombres.get(e, ""),
                    "prioridad": p,
                    "porcentaje": c,
                }
                for e, p, c in prop
            ],
        })

    def perform_create(self, serializer):
        self._assert_direccion()
        serializer.save()

    def _assert_direccion(self):
        user = self.request.user
        if not (user.is_authenticated and user.is_superadmin):
            raise PermissionDenied(
                "Solo la dirección deportiva da de alta o de baja jugadores."
            )

    def perform_update(self, serializer):
        # #18: al dar de baja (activo True->False) se avisa a dirección in-app.
        antes_activo = serializer.instance.activo
        jugador = serializer.save()
        if antes_activo and not jugador.activo:
            Aviso.objects.create(
                para_direccion=True,
                tipo=Aviso.Tipo.GENERAL,
                titulo=f"Baja de jugador: {jugador.nombre}",
                mensaje=f"{jugador.nombre} se ha dado de baja (marcado como inactivo).",
            )

    @action(detail=True, methods=["post"])
    def reportar_movimiento(self, request, pk=None):
        """#4: un entrenador/coach avisa de que ve a un jugador (suyo o de otra
        escuela) que parece haber cambiado de escuela. Crea avisos a dirección,
        al entrenador responsable y a su coach. No cambia la escuela: es un aviso.
        El scope de get_object() ya restringe a jugadores visibles por el usuario.
        """
        jugador = self.get_object()
        escuela_obs = (request.data.get("escuela_observada") or "").strip()
        nota = (request.data.get("nota") or "").strip()
        titulo = f"Posible movimiento de escuela: {jugador.nombre}"
        partes = []
        if escuela_obs:
            partes.append(f"Escuela observada: {escuela_obs}.")
        if nota:
            partes.append(nota)
        actor = getattr(request.user, "entrenador", None) or getattr(request.user, "coach", None)
        if actor is not None:
            partes.append(f"Reportado por {actor.nombre}.")
        mensaje = " ".join(partes)

        Aviso.objects.create(
            para_direccion=True, tipo=Aviso.Tipo.MOVIMIENTO, titulo=titulo, mensaje=mensaje,
        )
        ent = jugador.entrenador_responsable
        destinatarios = []
        if ent is not None and ent.user_id:
            destinatarios.append(ent.user)
        destinatarios.extend(coaches_del_entrenador(ent))
        for user in destinatarios:
            Aviso.objects.create(
                usuario=user, tipo=Aviso.Tipo.MOVIMIENTO, titulo=titulo, mensaje=mensaje,
            )
        return Response({"ok": True, "avisos_creados": 1 + len(destinatarios)})


class RencillaViewSet(viewsets.ModelViewSet):
    queryset = Rencilla.objects.all()
    serializer_class = RencillaSerializer
    permission_classes = [DireccionOrCoachWrite]


class ContratoViewSet(viewsets.ModelViewSet):
    queryset = Contrato.objects.all()
    serializer_class = ContratoSerializer
    permission_classes = [DireccionOrCoachWrite]


class ResponsableJugadorViewSet(viewsets.ModelViewSet):
    serializer_class = ResponsableJugadorSerializer
    permission_classes = [DireccionOrCoachWrite]
    queryset = ResponsableJugador.objects.select_related(
        "jugador", "entrenador"
    ).all()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # Fuera de dirección, solo responsables de jugadores dentro del alcance.
        if user.is_authenticated and not user.is_superadmin:
            qs = qs.filter(jugador__in=jugadores_visibles(user))
        jugador = self.request.query_params.get("jugador")
        return qs.filter(jugador=jugador) if jugador else qs

    def perform_create(self, serializer):
        # Al añadir un responsable se re-reparte el % (#12: 70/15/15 auto).
        rj = serializer.save()
        rj.jugador.repartir_porcentajes()

    def perform_destroy(self, instance):
        jugador = instance.jugador
        instance.delete()
        jugador.repartir_porcentajes()


class VacacionesEntrenadorViewSet(viewsets.ModelViewSet):
    queryset = VacacionesEntrenador.objects.select_related("entrenador").all()
    serializer_class = VacacionesEntrenadorSerializer
    permission_classes = [DireccionOrCoachWrite]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["fecha_inicio", "fecha_fin"]

    def get_queryset(self):
        qs = VacacionesEntrenador.objects.select_related("entrenador")
        user = self.request.user
        if user.is_authenticated and not user.is_superadmin:
            coach = getattr(user, "coach", None)
            if coach is not None:
                return qs.filter(entrenador__in=coach.entrenadores.all())
            ent = getattr(user, "entrenador", None)
            return qs.filter(entrenador=ent) if ent else qs.none()
        return qs


class EscuelaViewSet(viewsets.ModelViewSet):
    queryset = Escuela.objects.all()
    serializer_class = EscuelaSerializer
    permission_classes = [ReadOnlyOrDireccion]


class PreferenciaSuperficieViewSet(viewsets.ModelViewSet):
    """Preferencias de superficie por jugador (#1).

    Se declaran también desde el calendario de faltas («del 5 al 9, resina»),
    así que llevan el mismo alcance que una falta: cada entrenador solo ve y
    toca las de sus alumnos.
    """

    serializer_class = PreferenciaSuperficieSerializer
    queryset = PreferenciaSuperficie.objects.select_related("jugador").all()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_superadmin:
            from .scope import jugadores_visibles

            qs = qs.filter(jugador__in=jugadores_visibles(user))
        jugador = self.request.query_params.get("jugador")
        return qs.filter(jugador=jugador) if jugador else qs

    def _assert_puede(self, jugador):
        user = self.request.user
        if user.is_superadmin:
            return
        from .scope import puede_ver_jugador

        # Desde el 06/10/2026 la declara también el entrenador, para los
        # alumnos que ve, con aviso a su head coach (`_avisar_head_coach`).
        if not puede_ver_jugador(user, jugador):
            raise PermissionDenied("Ese jugador no es de los tuyos.")

    def _avisar_head_coach(self, pref, accion):
        """Si la toca un entrenador, se entera su head coach."""
        user = self.request.user
        ent = getattr(user, "entrenador", None)
        if user.is_superadmin or user.is_coach or ent is None:
            return
        sup = pref.get_superficie_display().lower()
        cuando = ""
        if pref.fecha_desde and pref.fecha_hasta:
            cuando = (f" el {pref.fecha_desde:%d/%m}" if pref.fecha_desde == pref.fecha_hasta
                      else f" del {pref.fecha_desde:%d/%m} al {pref.fecha_hasta:%d/%m}")
        titulo = (f"Superficie: {pref.jugador.nombre} entrena en {sup}{cuando}"
                  if accion == "pone" else
                  f"Superficie quitada: {pref.jugador.nombre} ({sup}{cuando})")
        mensaje = f"{'Declarado' if accion == 'pone' else 'Quitado'} por {ent.nombre}."
        for u in coaches_del_entrenador(ent):
            Aviso.objects.create(
                usuario=u, tipo=Aviso.Tipo.GENERAL, titulo=titulo[:160], mensaje=mensaje,
            )

    def perform_create(self, serializer):
        self._assert_puede(serializer.validated_data["jugador"])
        self._avisar_head_coach(serializer.save(), "pone")

    def perform_update(self, serializer):
        self._assert_puede(serializer.instance.jugador)
        self._assert_puede(serializer.validated_data.get("jugador", serializer.instance.jugador))
        self._avisar_head_coach(serializer.save(), "pone")

    def perform_destroy(self, instance):
        self._assert_puede(instance.jugador)
        self._avisar_head_coach(instance, "quita")
        instance.delete()


class AvisoViewSet(viewsets.ModelViewSet):
    """Avisos in-app mostrados en el perfil. Cada usuario ve los suyos; el Super
    Admin ve además los dirigidos a dirección."""

    serializer_class = AvisoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        u = self.request.user
        qs = Aviso.objects.all()
        if u.is_superadmin:
            return qs.filter(Q(usuario=u) | Q(para_direccion=True))
        return qs.filter(usuario=u)

    @action(detail=True, methods=["post"])
    def leer(self, request, pk=None):
        aviso = self.get_object()
        aviso.leido = True
        aviso.save(update_fields=["leido"])
        return Response({"ok": True})


def _jugador_previo(inv):
    """El jugador de la última vez que vino, si esta invitación repite."""
    vista = set()
    previa = inv.repite_de
    while previa is not None and previa.pk not in vista:
        if previa.jugador_creado_id:
            return previa.jugador_creado
        vista.add(previa.pk)
        previa = previa.repite_de
    return None


def _jugador_de_invitado(inv, escuela_default):
    """El jugador que sale de un invitado aprobado: un alta como cualquier
    otra, con su ficha deportiva y todo lo que mira el motor, y de alta solo
    entre sus fechas (14/10/2026).

    Si vuelve (otra invitación copiada de una anterior), es el mismo jugador:
    se le ponen las fechas y la ficha de esta vez y conserva su historial. Lo
    que mira el motor (semana, superficie, parejas, rencillas, entrenadores)
    queda exactamente como dice esta invitación."""
    solicitante = inv.entrenador_solicitante
    campos = dict(
        activo=True,
        escuela_id=inv.escuela_id or escuela_default,
        entrenador_responsable=solicitante,
        division=inv.division,
        edad=inv.edad,
        sexo=inv.sexo,
        vecindad=inv.vecindad or Jugador.Vecindad.CLUB,
        pareja_division=inv.pareja_division or None,
        sin_prioridad=inv.sin_prioridad,
        fecha_alta=inv.fecha_desde,
        fecha_baja=inv.fecha_hasta,
        notas=(f"Invitado de {solicitante.nombre}"
               + (f": {inv.nota}" if inv.nota else ""))[:200],
        **({"sesiones_dia_max": inv.sesiones_dia_max}
           if inv.sesiones_dia_max else {}),
    )
    jugador = _jugador_previo(inv)
    if jugador is None:
        jugador = Jugador.objects.create(nombre=f"{inv.nombre} (invitado)", **campos)
    else:
        for k, v in campos.items():
            setattr(jugador, k, v)
        jugador.save()
        jugador.cogestores.clear()
        HorarioJugador.objects.filter(jugador=jugador).delete()
        PreferenciaSuperficie.objects.filter(
            jugador=jugador, fecha_desde__isnull=True, fecha_hasta__isnull=True).delete()
        PreferenciaPareja.objects.filter(jugador=jugador).delete()
        Rencilla.objects.filter(Q(jugador_a=jugador) | Q(jugador_b=jugador)).delete()
        Contrato.objects.filter(jugador=jugador).delete()
        VetoEntrenador.objects.filter(jugador=jugador).delete()
    pesos.guardar(jugador, pesos.propuesta(solicitante))
    # La semana que viene: una fila por día de lunes a sábado. Los días que
    # no se marcan, no viene (sin fila el motor le daría por venir).
    turnos = {t.codigo: t for t in Turno.objects.filter(codigo__in=["M1", "M2", "T1", "T2"])}
    for dia in range(6):
        fila = (inv.dias or {}).get(str(dia)) or {}
        manana, tarde = fila.get("manana"), fila.get("tarde")
        HorarioJugador.objects.create(
            jugador=jugador, dia=dia,
            entrena_manana=manana is not None,
            entrena_tarde=tarde is not None,
            turno_manana=turnos.get(manana) if manana else None,
            turno_tarde=turnos.get(tarde) if tarde else None,
        )
    if inv.superficie_pref:
        PreferenciaSuperficie.objects.create(
            jugador=jugador, superficie=inv.superficie_pref,
            estricta=inv.superficie_estricta,
        )
    if inv.jugar_con_id:
        PreferenciaPareja.objects.create(
            jugador=jugador, jugador_objetivo=inv.jugar_con,
            tipo=(PreferenciaPareja.Tipo.HARD if inv.pareja_estricta
                  else PreferenciaPareja.Tipo.SOFT),
        )
    for otro in inv.no_coincidir_con.all():
        Rencilla.objects.get_or_create(
            jugador_a=jugador, jugador_b=otro,
            defaults={"motivo": "Invitado: no coincidir"})
    if inv.entrena_con_id:
        Contrato.objects.create(
            jugador=jugador, entrenador=inv.entrena_con,
            tipo=(Contrato.Tipo.DURO if inv.entrena_con_estricto
                  else Contrato.Tipo.BLANDO),
        )
    for ent in inv.no_entrena_con.all():
        VetoEntrenador.objects.create(jugador=jugador, entrenador=ent)
    return jugador


class InvitadoViewSet(viewsets.ModelViewSet):
    """Invitados propuestos por entrenadores; aprobación por el Super Admin (#5)."""

    serializer_class = InvitadoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        u = self.request.user
        qs = Invitado.objects.select_related(
            "entrenador_solicitante", "grupo_anfitrion"
        )
        if u.is_superadmin:
            return qs
        coach = getattr(u, "coach", None)
        if coach is not None:
            return qs.filter(entrenador_solicitante__in=coach.entrenadores.all())
        ent = getattr(u, "entrenador", None)
        return qs.filter(entrenador_solicitante=ent) if ent else qs.none()

    def perform_create(self, serializer):
        u = self.request.user
        ent = getattr(u, "entrenador", None)
        solicitante = serializer.validated_data.get("entrenador_solicitante") or ent
        if solicitante is None:
            raise PermissionDenied("Tu usuario no está enlazado a un entrenador.")
        inv = serializer.save(entrenador_solicitante=solicitante)
        Aviso.objects.create(
            para_direccion=True,
            tipo=Aviso.Tipo.INVITADO,
            titulo=f"Invitado pendiente: {inv.nombre}",
            mensaje=f"{solicitante.nombre} solicita añadir a «{inv.nombre}». Requiere tu aprobación.",
        )
        # Notificar siempre al Coach del entrenador solicitante (#5).
        from .scope import coaches_del_entrenador
        for coach_user in coaches_del_entrenador(solicitante):
            Aviso.objects.create(
                usuario=coach_user,
                tipo=Aviso.Tipo.INVITADO,
                titulo=f"Invitado propuesto por {solicitante.nombre}",
                mensaje=f"«{inv.nombre}» — pendiente de aprobación por dirección.",
            )

    def perform_update(self, serializer):
        # Mientras está pendiente se corrige aquí; aprobado, ya es un jugador y
        # su ficha se toca en Jugadores.
        if serializer.instance.estado != Invitado.Estado.PENDIENTE:
            raise PermissionDenied(
                "El invitado ya está resuelto: cambia su ficha en Jugadores.")
        serializer.save()

    def _avisar_solicitante(self, inv, titulo, mensaje):
        user = getattr(inv.entrenador_solicitante, "user", None)
        if user:
            Aviso.objects.create(
                usuario=user, tipo=Aviso.Tipo.INVITADO, titulo=titulo, mensaje=mensaje
            )

    @action(detail=True, methods=["post"])
    def aprobar(self, request, pk=None):
        if not request.user.is_superadmin:
            raise PermissionDenied("Solo la dirección deportiva aprueba invitados.")
        inv = self.get_object()
        if inv.estado != Invitado.Estado.PENDIENTE:
            return Response({"error": "El invitado ya está resuelto."}, status=409)
        if not (inv.fecha_desde and inv.fecha_hasta and inv.dias):
            raise ValidationError(
                "Antes de aprobarlo, indica las fechas y los días que viene.")
        # Asociación por entrenador solicitante (#5 feedback Sergio): el grupo
        # del invitado se entiende por el entrenador que lo propone, no por un
        # 'grupo_anfitrión'. Derivamos escuela y responsable de ahí.
        solicitante = inv.entrenador_solicitante
        escuela_default = (
            Jugador.objects.filter(
                entrenadores_gestores=solicitante, activo=True
            ).values_list("escuela_id", flat=True).first()
        )
        if escuela_default is None:
            # Si el entrenador no tiene jugadores activos,alto rendimiento por defecto.
            from .models import Escuela
            escuela_default = (
                Escuela.objects.filter(nombre__icontains="alto rendimiento")
                .values_list("id", flat=True).first()
            )
        with transaction.atomic():
            jugador = _jugador_de_invitado(inv, escuela_default)
            inv.estado = Invitado.Estado.APROBADO
            inv.aprobado_por = request.user
            inv.jugador_creado = jugador
            inv.save()
        self._avisar_solicitante(
            inv, f"Invitado aprobado: {inv.nombre}",
            "Entra en el cuadrante los días y fechas que se indicaron; su ficha, "
            "en Jugadores.",
        )
        return Response(InvitadoSerializer(inv).data)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        if not request.user.is_superadmin:
            raise PermissionDenied("Solo la dirección deportiva rechaza invitados.")
        inv = self.get_object()
        if inv.estado != Invitado.Estado.PENDIENTE:
            return Response({"error": "El invitado ya está resuelto."}, status=409)
        inv.estado = Invitado.Estado.RECHAZADO
        inv.aprobado_por = request.user
        inv.save()
        self._avisar_solicitante(
            inv, f"Invitado rechazado: {inv.nombre}", request.data.get("motivo", "")
        )
        return Response(InvitadoSerializer(inv).data)


class TareaMantenimientoViewSet(viewsets.ModelViewSet):
    queryset = TareaMantenimiento.objects.all()
    serializer_class = TareaMantenimientoSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["titulo", "descripcion", "responsable"]
    ordering_fields = ["fecha_limite", "estado", "created_at"]

    def perform_create(self, serializer):
        tarea = serializer.save()
        # Aviso in-app a dirección (sin notificación externa por ahora).
        Aviso.objects.create(
            para_direccion=True,
            tipo=Aviso.Tipo.MANTENIMIENTO,
            titulo=f"Nueva tarea de mantenimiento: {tarea.titulo}",
            mensaje=(f"Responsable: {tarea.responsable}. " if tarea.responsable else "")
            + (f"Límite: {tarea.fecha_limite}." if tarea.fecha_limite else ""),
        )


class FeedbackViewSet(viewsets.ModelViewSet):
    # Orden por severidad (Alta > Media > Baja) y luego por más reciente.
    queryset = Feedback.objects.annotate(
        _sev=Case(
            When(prioridad="ALTA", then=Value(0)),
            When(prioridad="MEDIA", then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )
    ).order_by("_sev", "-created_at")
    serializer_class = FeedbackSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["autor", "titulo", "descripcion"]
    ordering_fields = ["created_at", "prioridad", "estado"]

    def get_queryset(self):
        qs = super().get_queryset()
        # Filtrado por estado: acepta lista separada por comas
        # (?estado=NUEVO,EN_PROGRESO) para que el frontend pueda agrupar
        # varios estados bajo una misma pestaña.
        estados = self.request.query_params.get("estado")
        if estados:
            qs = qs.filter(estado__in=[e.strip() for e in estados.split(",") if e.strip()])
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(creado_por=user)


def _coach_activo(user):
    """El Coach del usuario, si lo tiene y está activo."""
    coach = getattr(user, "coach", None)
    return coach if (coach is not None and coach.activo) else None


class MiAgendaViewSet(viewsets.ViewSet):
    """Lo que el entrenador ve de SÍ MISMO: su jornada semanal y sus ausencias
    largas. Nada del resto de la app.

    Tres vistas, que son las tres cosas que necesita:
      * `dia`      — hoy, si trabaja de mañana, de tarde o ambas;
      * `semana`   — los cinco días de un vistazo, editable;
      * `ausencias`— periodos con fecha de ida y de vuelta, a meses vista.
    """

    DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

    def _puede_mirar_a_otros(self):
        """Dirección, y el coach sobre su propio bloque. Nadie más."""
        user = self.request.user
        return bool(user.is_superadmin or _coach_activo(user))

    def _agendas_visibles(self):
        """Entrenadores cuya agenda puede abrir este usuario."""
        user = self.request.user
        if user.is_superadmin:
            qs = Entrenador.objects.all()
        else:
            coach = _coach_activo(user)
            qs = coach.entrenadores.all() if coach else Entrenador.objects.none()
        return qs.filter(activo=True).order_by("nombre")

    def _entrenador(self):
        """El entrenador cuya agenda se está viendo.

        Normalmente el del propio usuario. Dirección puede mirar la de
        cualquiera, y un coach la de los de su bloque, pasando
        `?entrenador=<id>`: hace falta para rellenarle la jornada a quien no
        entre nunca a la app. Sin elegir a nadie se abre el primero de la
        lista, para que la pantalla cargue en vez de dar un error.
        """
        user = self.request.user
        pedido = self.request.query_params.get("entrenador") or \
            self.request.data.get("entrenador")
        propio = getattr(user, "entrenador", None)

        if pedido:
            if propio is not None and str(propio.pk) == str(pedido):
                return propio
            if not self._puede_mirar_a_otros():
                raise PermissionDenied(
                    "Solo dirección, o el coach de su bloque, puede ver la "
                    "agenda de otro."
                )
            ent = self._agendas_visibles().filter(pk=pedido).first()
            if ent is None:
                raise NotFound("Ese entrenador no está en tu equipo.")
            return ent

        if propio is not None:
            return propio
        ent = self._agendas_visibles().first()
        if ent is None:
            raise PermissionDenied(
                "Tu usuario no tiene ficha de entrenador ni entrenadores a "
                "cargo."
            )
        return ent

    @action(detail=False, methods=["get"])
    def entrenadores(self, request):
        """Para el selector: a quién se le puede mirar la agenda."""
        if not self._puede_mirar_a_otros():
            raise PermissionDenied("Solo dirección o coach.")
        return Response([
            {"id": e.id, "nombre": e.nombre} for e in self._agendas_visibles()
        ])

    def _semana(self, ent):
        filas = {h.dia: h for h in ent.horario.all()}
        out = []
        for d in range(6):
            h = filas.get(d)
            out.append({
                "dia": d, "nombre": self.DIAS[d],
                # Sin fila guardada, jornada completa: es el caso normal y no
                # obliga a nadie a rellenar nada para empezar.
                "manana": h.manana if h else True,
                "tarde": h.tarde if h else True,
            })
        return out

    def list(self, request):
        ent = self._entrenador()
        return Response({"entrenador": ent.nombre, "semana": self._semana(ent)})

    @action(detail=False, methods=["get"])
    def sesiones(self, request):
        """Sus pistas de un día: turno, hora, número de pista y quién le toca.

        Es lo primero que quiere ver un entrenador al entrar — no su jornada
        en abstracto, sino dónde tiene que estar y con quién.
        """
        from datetime import date, timedelta

        from scheduling.models import Asignacion, Semana

        ent = self._entrenador()
        try:
            fecha = date.fromisoformat(request.query_params["fecha"])
        except (KeyError, ValueError):
            fecha = date.today()
        lunes = fecha - timedelta(days=fecha.weekday())
        semana = Semana.objects.filter(fecha_inicio=lunes).first()
        if semana is None:
            return Response({"fecha": fecha, "hay_semana": False, "pistas": []})

        filas = (
            Asignacion.objects
            .filter(semana=semana, dia=fecha.weekday(), entrenador=ent)
            .select_related("turno", "pista", "pista__sede", "jugador",
                            "jugador__division")
            .order_by("turno__orden", "pista__numero", "jugador__nombre")
        )
        # Se devuelve lo mismo que pinta el cuadrante de dirección —foto,
        # división y estado— para que la pista se dibuje igual aquí.
        from scheduling.serializers import falta_de

        pistas = {}
        faltas = {}
        for a in filas:
            clave = (a.turno_id, a.pista_id)
            ficha = pistas.get(clave)
            if ficha is None:
                inicio, fin = a.turno.horas(fecha)
                ficha = pistas[clave] = {
                    "turno": a.turno.codigo,
                    "turno_orden": a.turno.orden,
                    "hora_inicio": inicio.strftime("%H:%M"),
                    "hora_fin": fin.strftime("%H:%M"),
                    "pista": a.pista.numero,
                    "sede": a.pista.sede.nombre,
                    "es_satelite": a.pista.sede.es_satelite,
                    "superficie": a.pista.superficie,
                    "superficie_nombre": a.pista.get_superficie_display(),
                    "jugadores": [],
                }
            ficha["jugadores"].append({
                "id": a.jugador_id,
                "nombre": a.jugador.nombre,
                "foto": a.jugador.foto_url or "",
                "division": a.jugador.division.nivel if a.jugador.division_id else None,
                "estado": a.estado,
                "falta": falta_de(a, faltas),
            })
        return Response({
            "fecha": fecha,
            "hay_semana": True,
            "semana": semana.fecha_inicio,
            "estado_semana": semana.estado,
            "entrenador": {"nombre": ent.nombre, "foto": ent.foto_url or ""},
            "pistas": list(pistas.values()),
        })

    @action(detail=False, methods=["get"])
    def dia(self, request):
        """Hoy: si trabaja de mañana, de tarde, o está fuera."""
        from datetime import date

        ent = self._entrenador()
        hoy = date.today()
        fila = next((d for d in self._semana(ent) if d["dia"] == hoy.weekday()), None)
        vacs = list(VacacionesEntrenador.objects.filter(
            entrenador=ent, fecha_inicio__lte=hoy, fecha_fin__gte=hoy
        ))
        # Una ausencia de una franja (solo M1) no le quita la mañana entera.
        fuera = {v.ambito for v in vacs}
        vac = next((v for v in vacs if v.ambito == "DIA"), vacs[0] if vacs else None)
        return Response({
            "fecha": hoy,
            "dia": fila["nombre"] if fila else None,
            "manana": bool(fila and fila["manana"]) and not (fuera & {"DIA", "MANANA"}),
            "tarde": bool(fila and fila["tarde"]) and not (fuera & {"DIA", "TARDE"}),
            "ausente": "DIA" in fuera,
            "motivo": vac.motivo if vac else "",
            "franjas_fuera": sorted(fuera - {"DIA", "MANANA", "TARDE"}),
        })

    @action(detail=False, methods=["put", "patch"])
    def semana(self, request):
        """Guarda la jornada de la semana entera de una vez."""
        ent = self._entrenador()
        for fila in request.data.get("semana", []):
            d = int(fila["dia"])
            manana, tarde = bool(fila.get("manana")), bool(fila.get("tarde"))
            if manana and tarde:
                # Jornada completa es el valor por defecto: no se guarda fila,
                # así la tabla solo contiene excepciones.
                HorarioEntrenador.objects.filter(entrenador=ent, dia=d).delete()
            else:
                HorarioEntrenador.objects.update_or_create(
                    entrenador=ent, dia=d,
                    defaults={"manana": manana, "tarde": tarde},
                )
        return Response({"semana": self._semana(ent)})

    @action(detail=False, methods=["get", "post"])
    def ausencias(self, request):
        """Periodos largos con fecha de ida y de vuelta (el calendario anual)."""
        ent = self._entrenador()
        if request.method == "POST":
            ambito = request.data.get("ambito") or VacacionesEntrenador.Ambito.DIA
            if ambito not in VacacionesEntrenador.Ambito.values:
                return Response({"error": "Esa franja no existe."}, status=400)
            VacacionesEntrenador.objects.create(
                entrenador=ent,
                fecha_inicio=request.data["fecha_inicio"],
                fecha_fin=request.data["fecha_fin"],
                motivo=request.data.get("motivo", ""),
                ambito=ambito,
            )
        return Response(VacacionesEntrenadorSerializer(
            ent.vacaciones.order_by("fecha_inicio"), many=True).data)

    @action(detail=False, methods=["delete"], url_path=r"ausencias/(?P<pk>\d+)")
    def borrar_ausencia(self, request, pk=None):
        ent = self._entrenador()
        ent.vacaciones.filter(pk=pk).delete()
        return Response(status=204)


class GrupoViewSet(viewsets.ViewSet):
    """Los grupos de entrenamiento: cada entrenador con los alumnos que lleva.

    El grupo de alguien son los alumnos de los que es RESPONSABLE
    (`Jugador.entrenador_responsable`): su sub-columna del organigrama, la
    gente por la que responde. Eso es lo que dirección reparte y lo que se
    edita aquí.

    Sus porcentajes (`ResponsableJugador`: con quién más entrena) no salen
    aquí: el club no quiere el «también entrena a N» (13/10/2026).

    Los bloques (Dani Gimeno, Pablo Gil, Santi Panzarasa…) son los `Coach`.
    Los que tienen color son los grupos de gestión de la tabla del club
    (13/10/2026): salen primero, pintados de su color, y cada entrenador está
    en el suyo aunque figure además en los bloques de Sergio e Iván, que
    abarcan a todos. Quien comparte la gestión (`cogestores`) tiene a esos
    alumnos en su columna igual que el responsable.

    El head coach de un color (Dani, Pablo, Santi) gestiona a todos los
    alumnos de su color: los cambia de columna, los deja sin grupo y coloca a
    las altas nuevas. Cambiar a un entrenador de bloque sigue siendo cosa de
    dirección.
    """

    # El organigrama lo ve todo el mundo igual (14/10/2026): dirección,
    # coaches y entrenadores. Reorganizarlo es cosa de dirección y del head
    # coach de cada color; el entrenador solo mira.
    permission_classes = [DireccionOrCoachWrite]

    def _ficha(self, j, con=None):
        return {
            "id": j.id,
            "nombre": j.nombre,
            "division": j.division.nivel if j.division_id else None,
            "escuela": j.escuela.nombre if j.escuela_id else None,
            "foto": j.foto_url or "",
            # Gestión compartida: con quién lleva esta columna al alumno.
            "con": con or [],
        }

    def _assert_direccion(self):
        if not self.request.user.is_superadmin:
            raise PermissionDenied(
                "Solo la dirección deportiva reorganiza los grupos."
            )

    def _color_propio(self):
        """Los entrenadores del grupo de color del usuario, si es su head
        coach; si no, None."""
        coach = _coach_activo(self.request.user)
        if coach is None or not coach.color:
            return None
        return set(coach.entrenadores.values_list("pk", flat=True))

    def _puede_ordenar(self, coach_id):
        """Ordenar las columnas de un bloque: dirección, o su head coach."""
        if self.request.user.is_superadmin:
            return True
        coach = _coach_activo(self.request.user)
        return coach is not None and bool(coach.color) and coach.pk == coach_id

    def _assert_gestiona(self, jugador, entrenador):
        """Dirección mueve a cualquiera; el head coach, dentro de su color: el
        alumno es de una columna de su color (o no tiene grupo) y la columna
        a la que va o de la que sale, también."""
        if self.request.user.is_superadmin:
            return
        suyos = self._color_propio()
        responsable = jugador.entrenador_responsable
        if suyos is not None and entrenador.pk in suyos and (
                responsable is None or not responsable.activo
                or responsable.pk in suyos):
            return
        raise PermissionDenied(
            "Solo puedes mover a los alumnos de tu grupo de color."
        )

    def list(self, request):
        from collections import defaultdict

        # Todos ven la página entera, como dirección: no se filtra por usuario.
        entrenadores = list(
            Entrenador.objects.filter(activo=True)
            .prefetch_related("coaches")
            .order_by("orden_grupo", "nombre")
        )
        ids = {e.id for e in entrenadores}
        nombres = {e.id: e.nombre for e in entrenadores}
        jugadores = {
            j.id: j
            for j in Jugador.objects.filter(activo=True).select_related(
                "division", "escuela", "entrenador_responsable"
            ).prefetch_related("cogestores")
        }

        propios = defaultdict(list)
        gestores = {}
        for j in sorted(jugadores.values(), key=lambda x: x.nombre):
            if j.entrenador_responsable_id not in ids:
                continue
            gestores[j.id] = [j.entrenador_responsable_id] + [
                c.id for c in j.cogestores.all() if c.id in ids]
            for g in gestores[j.id]:
                propios[g].append(self._ficha(j, con=[
                    nombres[o] for o in gestores[j.id] if o != g]))

        def bloque_de(e):
            """Su grupo de gestión (el bloque con color) y, si no tiene, el
            primero de los suyos."""
            suyos = sorted((c for c in e.coaches.all() if c.activo),
                           key=lambda c: (not c.color, c.nombre))
            return suyos[0] if suyos else None

        por_bloque = defaultdict(list)
        for e in entrenadores:
            coach = bloque_de(e)
            # El head coach no sale como columna de su propio grupo si no lleva
            # a nadie: ya está en la cabecera (Dani Gimeno).
            if (coach is not None and coach.color and coach.user_id
                    and coach.user_id == e.user_id and not propios[e.id]):
                continue
            # Los niveles de sus alumnos, para situarse: la división ya no dice
            # a quién puede entrenar.
            niveles = sorted({f["division"] for f in propios[e.id] if f["division"]})
            por_bloque[coach.id if coach else None].append({
                "entrenador": {
                    "id": e.id,
                    "nombre": e.nombre,
                    "foto": e.foto_url or "",
                    "divisiones": " · ".join(f"D{n}" for n in niveles) or "—",
                },
                "jugadores": propios[e.id],
            })

        # Se devuelven TODOS los bloques, también los que se han quedado sin
        # entrenadores: si no, no habría dónde soltar al que se arrastra.
        orden = {v: i for i, v in enumerate(Coach.Color.values)}
        # Los bloques sin color (Sergio, Iván, Álvaro…) solo le sirven a
        # dirección, que es quien coloca ahí columnas: los demás ven los grupos.
        direccion = bool(request.user.is_superadmin)
        visibles = Coach.objects.filter(activo=True)
        if not direccion:
            visibles = visibles.exclude(color="")
        coaches = sorted(visibles,
                         key=lambda c: (orden.get(c.color, len(orden)), c.nombre))
        bloques = [
            {
                "coach": {"id": c.id, "nombre": c.nombre, "color": c.color,
                          "color_nombre": c.get_color_display() if c.color else ""},
                "grupos": por_bloque.get(c.id, []),
            }
            for c in coaches
        ]
        if direccion:
            bloques.append({"coach": None, "grupos": por_bloque.get(None, [])})

        # Sin grupo es quien no tiene responsable (o lo tiene de baja). El
        # coach ve además a alumnos que gestiona otro color porque los
        # entrenan los suyos: esos tienen grupo, no van aquí.
        sin_grupo = [
            self._ficha(j) for j in sorted(jugadores.values(), key=lambda x: x.nombre)
            if j.entrenador_responsable_id not in ids and (
                j.entrenador_responsable is None
                or not j.entrenador_responsable.activo)
        ]
        return Response({
            "bloques": bloques,
            "sin_grupo": sin_grupo,
            "entrenadores": [{"id": e.id, "nombre": e.nombre} for e in entrenadores],
            # Alumnos: dirección y el head coach de un color. Columnas
            # (entrenadores de un bloque a otro): solo dirección.
            "puede_editar": direccion or self._color_propio() is not None,
            "puede_mover_entrenadores": direccion,
            # Bloques cuyas columnas puede ordenar (todos, para dirección).
            "puede_ordenar": [c.id for c in coaches if self._puede_ordenar(c.id)],
        })

    def _jugador(self, request):
        jugador = Jugador.objects.filter(pk=request.data.get("jugador")).first()
        if jugador is None:
            raise NotFound("Ese jugador no existe.")
        return jugador

    def _entrenador(self, request, obligatorio=True):
        valor = request.data.get("entrenador")
        if valor in (None, "", "null"):
            if obligatorio:
                raise NotFound("Falta el entrenador.")
            return None
        ent = Entrenador.objects.filter(pk=valor).first()
        if ent is None:
            raise NotFound("Ese entrenador no existe.")
        return ent

    @action(detail=False, methods=["post"])
    def mover(self, request):
        """Mete al alumno en el grupo de este entrenador.

        Pasa a ser su responsable y su principal, y el resto del bloque, sus
        secundarios al 10%: la misma regla del organigrama. Los retoques, luego,
        en su ficha."""
        jugador, entrenador = self._jugador(request), self._entrenador(request)
        self._assert_gestiona(jugador, entrenador)
        with transaction.atomic():
            pesos.guardar(jugador, pesos.propuesta(entrenador))
            jugador.entrenador_responsable = entrenador
            jugador.save(update_fields=["entrenador_responsable"])
            # Cambia de columna: quien compartía la gestión ya no la comparte.
            jugador.cogestores.clear()
        return Response({"ok": True})

    @action(detail=False, methods=["post"])
    def ordenar(self, request):
        """Las columnas de un bloque, de izquierda a derecha: `orden` es la
        lista de entrenadores en el orden en que se quieren ver."""
        try:
            coach_id = int(request.data.get("coach"))
            orden = [int(i) for i in request.data.get("orden") or []]
        except (TypeError, ValueError):
            raise ValidationError("Falta el bloque o el orden.")
        if not self._puede_ordenar(coach_id):
            raise PermissionDenied("Solo puedes ordenar las columnas de tu grupo.")
        with transaction.atomic():
            for i, eid in enumerate(orden):
                Entrenador.objects.filter(pk=eid).update(orden_grupo=i + 1)
        return Response({"ok": True})

    @action(detail=False, methods=["post"])
    def anadir(self, request):
        """Añade al alumno como "también le entrena", sin sacarlo de su grupo."""
        self._assert_direccion()
        jugador, entrenador = self._jugador(request), self._entrenador(request)
        ResponsableJugador.objects.get_or_create(
            jugador=jugador, entrenador=entrenador,
            defaults={"prioridad": 1, "activo": True},
        )
        return Response({"ok": True})

    @action(detail=False, methods=["post"])
    def mover_entrenador(self, request):
        """Cambia a un entrenador de bloque: pasa al equipo de ese coach.

        Sus alumnos van con él —siguen siendo suyos— así que la columna entera
        se muda de sitio. Los porcentajes de sus alumnos no cambian: se
        retocan en la ficha de cada uno.

        Sin `coach`, se queda fuera de todos los bloques (independiente).

        Sale del bloque en el que se veía (`desde`) y de cualquier grupo de
        gestión, pero no de los bloques de Sergio e Iván, que abarcan a todos.
        Sin `desde`, sale de todos.
        """
        self._assert_direccion()
        ent = self._entrenador(request)
        destino = request.data.get("coach")
        coach = None
        if destino not in (None, "", "null"):
            coach = Coach.objects.filter(pk=destino).first()
            if coach is None:
                raise NotFound("Ese coach no existe.")
        desde = request.data.get("desde")
        salen = ent.coaches.all()
        if desde not in (None, "", "null"):
            salen = salen.filter(Q(pk=desde) | ~Q(color=""))
        for c in salen:
            c.entrenadores.remove(ent)
        if coach is not None:
            coach.entrenadores.add(ent)
        return Response({"ok": True})

    @action(detail=False, methods=["post"])
    def quitar(self, request):
        """Este entrenador deja de llevar a este alumno.

        Si era su grupo (su responsable), el alumno sale del grupo entero: sin
        responsable ni porcentajes, a «Sin grupo». Si solo le entrenaba, se le
        quita a él y su parte pasa al principal."""
        jugador, entrenador = self._jugador(request), self._entrenador(request)
        self._assert_gestiona(jugador, entrenador)
        with transaction.atomic():
            if jugador.entrenador_responsable_id == entrenador.id:
                pesos.guardar(jugador, [])
                jugador.entrenador_responsable = None
                jugador.save(update_fields=["entrenador_responsable"])
                jugador.cogestores.clear()
            elif jugador.cogestores.filter(pk=entrenador.pk).exists():
                # Compartía la gestión: deja de compartirla, nada más.
                jugador.cogestores.remove(entrenador)
            else:
                pesos.quitar(jugador, entrenador.id)
        return Response({"ok": True})
