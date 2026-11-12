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
from academy.permissions import (
    coordina_informes, envia_informes, evalua_fisico, evalua_tenis_solo_informes, valida_informes, ve_informes,
)
from academy.scope import jugadores_visibles, puede_ver_jugador

from . import catalogo, drive, fichero, ia, informes, pdf, traduccion
from .models import (
    AsignacionInforme, DatosInforme, Evaluacion, EvaluacionFisica, FotoJugador, Informe, MiembroTardes,
)
from .serializers import EvaluacionFisicaSerializer, EvaluacionSerializer, InformeSerializer, JugadorTardesSerializer


def _sin_duplicar(jugador, campo):
    """Un jugador de Competición de tardes tiene una sola evaluación de cada
    parte por informe: si ya hay una en marcha, se sigue con esa."""
    existente = informes.parte_existente(jugador, campo)
    if existente is not None:
        que = "de tenis" if campo == "tenis" else "física"
        raise ValidationError({"detail": f"Ya hay una evaluación {que} de este jugador en el informe en "
                                         f"curso: sigue con esa.", "existente": existente.pk})


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
        # Quien valida abre cualquier evaluación que esté en un informe, también
        # las de Alto rendimiento (decisiones 11 y 12).
        if valida_informes(user):
            filtro |= Q(informe__isnull=False)
        qs = Evaluacion.objects.filter(filtro).select_related("jugador").distinct()
        p = self.request.query_params
        if p.get("jugador"):
            qs = qs.filter(jugador_id=p["jugador"])
        if p.get("estado"):
            qs = qs.filter(estado=p["estado"])
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        jugador = serializer.validated_data["jugador"]
        if not self._jugadores().filter(pk=jugador.pk).exists():
            raise PermissionDenied("Ese jugador no está entre los tuyos.")
        _sin_duplicar(jugador, "tenis")
        ev = serializer.save(evaluador=user, nombre_evaluador=_nombre_evaluador(user))
        informes.vincular(ev)

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
            if ev._informe_cerrado():
                raise PermissionDenied("El informe ya está aprobado: para corregirlo, primero se reabre en Informes.")
            raise PermissionDenied("La cambian quien la hizo, quien coordina y quien valida.")
        return ev

    def perform_update(self, serializer):
        self._editable(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        if not instance.puede_borrar(self.request.user):
            raise PermissionDenied("La borran quien la hizo y quien coordina; un informe aprobado no se borra.")
        instance.delete()

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
        informe si hace falta y pasa a limpio las fortalezas y mejoras que ha
        escrito el entrenador (`fortalezas_original`, `mejoras_original`;
        desde el 02/11/2026 ya no las propone Claude)."""
        ev = self._editable(self.get_object())
        faltan = [b["titulo"] for b in catalogo.BLOQUES
                  if any(k not in ev.puntuaciones for k, _, _ in b["criterios"])]
        if faltan:
            raise ValidationError({"puntuaciones": f"Faltan notas en: {', '.join(faltan)}."})
        cambian = False
        for campo in ("fortalezas_original", "mejoras_original"):
            if campo in request.data:
                frases = request.data.get(campo)
                if not isinstance(frases, list) or len(frases) > 3 or not all(isinstance(f, str) for f in frases):
                    raise ValidationError({campo: "Van hasta tres frases."})
                frases = [f.strip() for f in frases if f.strip()]
                cambian = cambian or frases != getattr(ev, campo)
                setattr(ev, campo, frases)
        if not ev.fortalezas_original or not ev.mejoras_original:
            raise ValidationError({"detail": "Escribe al menos una fortaleza y un área de mejora."})
        avisos = []
        # Un comentario pulido en otro idioma (se cambió el idioma después) se vuelve a pasar.
        for bloque, com in list(ev.comentarios.items()):
            if com.get("pulido") and com.get("idioma") and com["idioma"] != ev.idioma:
                aviso = self._pulir(ev, bloque, com.get("original") or com["pulido"])
                if aviso:
                    avisos.append(aviso)
        if cambian or not (ev.fortalezas and ev.mejoras):
            try:
                ev.fortalezas, ev.mejoras = ia.pulir_frases(ev.fortalezas_original, ev.mejoras_original, ev.idioma)
            except ia.IANoDisponible as e:
                ev.fortalezas, ev.mejoras = list(ev.fortalezas_original), list(ev.mejoras_original)
                avisos.append(f"{e} Quedan tal como las escribiste.")
        ev.estado = Evaluacion.Estado.TERMINADA
        ev.terminada_en = ev.terminada_en or timezone.now()
        ev.save()
        informes.parte_terminada(ev)
        datos = self.get_serializer(ev).data
        return Response({**datos, "avisos": list(dict.fromkeys(avisos))})

    @action(detail=True, methods=["post"])
    def drive(self, request, pk=None):
        """Guarda (o reescribe) el informe terminado en la carpeta del jugador en Drive."""
        ev = self._editable(self.get_object())
        if ev.estado != Evaluacion.Estado.TERMINADA:
            raise ValidationError({"estado": "Solo se guardan en Drive los informes terminados."})
        if getattr(ev, "informe", None) is not None:
            # Competición de tardes: lo que va a Drive es el informe conjunto
            # (con el resumen ya retocado), cuando tenis y físico están listos.
            informes.parte_terminada(ev)
            return Response({**self.get_serializer(ev).data, "aviso": None})
        aviso = None
        idioma = informes.idioma_familia(ev.jugador, ev.idioma)
        try:
            traduccion.tenis(ev, idioma)
        except ia.IANoDisponible as e:
            idioma, aviso = ev.idioma, f"No se ha podido traducir el PDF ({e}); se guarda sin traducir."
        try:
            ev.drive_file_id, ev.drive_url = drive.subir(ev, idioma)
            ev.save(update_fields=["drive_file_id", "drive_url", "actualizada"])
        except drive.DriveNoDisponible as e:
            aviso = f"{e} El informe está guardado en la app; puedes reintentarlo desde su ficha."
        return Response({**self.get_serializer(ev).data, "aviso": aviso})

    @action(detail=True, url_path="pdf")
    def informe_pdf(self, request, pk=None):
        """El informe maquetado, para descargarlo: en el idioma de la familia."""
        ev = self.get_object()
        idioma = informes.idioma_familia(ev.jugador, ev.idioma)
        try:
            contenido = pdf.generar(ev, idioma)
        except ia.IANoDisponible as e:
            raise ValidationError({"detail": f"No se ha podido traducir el PDF: {e}"})
        respuesta = HttpResponse(contenido, content_type="application/pdf")
        respuesta["Content-Disposition"] = content_disposition_header(True, pdf.nombre(ev, idioma))
        return respuesta

    @action(detail=True, methods=["post"], url_path="idioma-familia")
    def idioma_familia(self, request, pk=None):
        """`{idioma}`: en qué idioma se le manda el PDF a la familia del jugador."""
        ev = self._editable(self.get_object())
        idioma = request.data.get("idioma")
        if idioma not in DatosInforme.Idioma.values:
            raise ValidationError({"detail": "Elige español o inglés."})
        DatosInforme.objects.update_or_create(jugador=ev.jugador, defaults={"idioma": idioma})
        ev.jugador.refresh_from_db()
        return Response(self.get_serializer(ev).data)

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
        _sin_duplicar(jugador, "fisica")
        ev = serializer.save(evaluador=self.request.user, nombre_evaluador=_nombre_evaluador(self.request.user))
        informes.vincular(ev)

    def _editable(self, ev):
        if not ev.puede_editar(self.request.user):
            if ev._informe_cerrado():
                raise PermissionDenied("El informe ya está aprobado: para corregirlo, primero se reabre en Informes.")
            raise PermissionDenied("La cambian quien la hizo y quien valida.")
        return ev

    def perform_update(self, serializer):
        self._editable(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        if not instance.puede_borrar(self.request.user):
            raise PermissionDenied("La borran quien la hizo y quien coordina; un informe aprobado no se borra.")
        instance.delete()

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
        informes.parte_terminada(ev)
        return Response(self.get_serializer(ev).data)


class InformeViewSet(viewsets.ReadOnlyModelViewSet):
    """Informes de Competición de tardes: tenis + físico en un PDF que valida
    gestión deportiva. Lo ven quienes evalúan esos alumnos y quienes validan.
    Filtros: `?estado=`, `?jugador=`."""

    serializer_class = InformeSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not ve_informes(request.user):
            raise PermissionDenied("Los informes son de quien evalúa, quien valida y quien los envía.")

    def get_queryset(self):
        """Tardes y, desde el 10/11/2026, Alto rendimiento (decisión 12). Los de
        Alto rendimiento los ven quien valida, quien envía y su evaluador."""
        u = self.request.user
        qs = Informe.objects.select_related("jugador", "jugador__escuela", "tenis", "fisica",
                                            "validado_por", "devuelto_por", "enviado_por")
        if not (valida_informes(u) or envia_informes(u)):
            qs = qs.filter(Q(jugador__escuela__solo_informes=True) | Q(tenis__evaluador=u))
        p = self.request.query_params
        if p.get("estado"):
            qs = qs.filter(estado=p["estado"])
        if p.get("jugador"):
            qs = qs.filter(jugador_id=p["jugador"])
        return qs

    def _validador(self):
        if not valida_informes(self.request.user):
            raise PermissionDenied("Validan quienes tienen la función «Valida informes» (Club → Personas y funciones).")

    @action(detail=False)
    def panel(self, request):
        """Cada jugador de Competición de tardes con su ciclo y su informe en curso."""
        hoy = timezone.localdate()
        abiertos = {}
        for inf in (Informe.objects.exclude(estado=Informe.Estado.VALIDADO)
                    .filter(jugador__escuela__solo_informes=True).select_related("tenis", "fisica")
                    .order_by("creado")):
            abiertos[inf.jugador_id] = inf
        fotos = set(FotoJugador.objects.values_list("jugador_id", flat=True))
        asignados = {a.jugador_id: a.evaluador for a in AsignacionInforme.objects.select_related("evaluador__entrenador")}
        out = []
        for j in jugadores_evaluables_fisico():
            inf = abiertos.get(j.id)
            c = informes.ciclo(j, hoy)
            ult = informes.ultimo_validado(j)
            out.append({
                "id": j.id, "nombre": j.nombre, "edad": j.edad, "foto": j.id in fotos,
                "evaluador": None if j.id not in asignados else {
                    "id": asignados[j.id].id, "nombre": _nombre_evaluador(asignados[j.id])},
                "ciclo": {"estado": c["estado"], "proxima": str(c["proxima"]) if c["proxima"] else None},
                "informe": None if inf is None else {
                    "id": inf.id, "estado": inf.estado,
                    "tenis": {"id": inf.tenis_id, "estado": inf.tenis.estado} if inf.tenis else None,
                    "fisica": {"id": inf.fisica_id, "estado": inf.fisica.estado} if inf.fisica else None,
                    "devuelto_partes": inf.devuelto_partes,
                },
                "ultimo": None if ult is None else {"id": ult.id, "fecha": str(timezone.localtime(ult.validado_en).date())},
            })
        return Response({"jugadores": out, "puede_validar": valida_informes(request.user),
                         "evalua_tenis": evalua_tenis_solo_informes(request.user),
                         "evalua_fisico": evalua_fisico(request.user),
                         "puede_asignar": coordina_informes(request.user), "yo": request.user.id,
                         "evaluadores": [{"id": u.id, "nombre": _nombre_evaluador(u)}
                                         for u in informes.evaluadores_tenis_por_defecto()]})

    @action(detail=False, methods=["post"])
    def asignar(self, request):
        """`{jugadores: [ids], evaluador: id | null}`: el coordinador reparte los
        informes de tenis. Devuelve el panel actualizado."""
        if not coordina_informes(request.user):
            raise PermissionDenied("Reparte los jugadores el coordinador de Competición de tardes.")
        try:
            ids = [int(x) for x in request.data.get("jugadores") or []]
            ev_id = request.data.get("evaluador")
            ev_id = int(ev_id) if ev_id not in (None, "") else None
        except (TypeError, ValueError):
            raise ValidationError({"detail": "Datos no válidos."})
        jugadores = list(jugadores_evaluables_fisico().filter(pk__in=ids))
        if not jugadores:
            raise ValidationError({"detail": "Elige algún jugador de Competición de tardes."})
        evaluador = None
        if ev_id is not None:
            evaluador = next((u for u in informes.evaluadores_tenis_por_defecto() if u.pk == ev_id), None)
            if evaluador is None:
                raise ValidationError({"detail": "Ese entrenador no hace informes de Competición de tardes."})
        informes.asignar(jugadores, evaluador, request.user)
        return self.panel(request)

    @action(detail=True)
    def pdf(self, request, pk=None):
        inf = self.get_object()
        if not inf.tenis:
            raise ValidationError({"detail": "Este informe aún no tiene la parte de tenis."})
        # En español para revisarlo; `?idioma=EN`, el que se envía a la familia.
        idioma = request.query_params.get("idioma") if request.query_params.get("idioma") in ("ES", "EN") else "ES"
        try:
            nombre, contenido = informes.pdf_de(inf, idioma)
        except ia.IANoDisponible as e:
            raise ValidationError({"detail": f"No se ha podido traducir el PDF: {e}"})
        respuesta = HttpResponse(contenido, content_type="application/pdf")
        respuesta["Content-Disposition"] = content_disposition_header(True, nombre)
        return respuesta

    @action(detail=True, methods=["post"])
    def aprobar(self, request, pk=None):
        """`{destinatarios: [{email, quien}]}`: se guardan para cuando haya envío por correo."""
        self._validador()
        inf = self.get_object()
        destinatarios = [
            {"email": str(d.get("email", "")).strip(), "quien": str(d.get("quien", "")).strip()}
            for d in (request.data.get("destinatarios") or []) if isinstance(d, dict) and str(d.get("email", "")).strip()
        ]
        try:
            aviso = informes.aprobar(inf, request.user, destinatarios)
        except informes.InformeError as e:
            raise ValidationError({"detail": str(e)})
        # «Aprobar y enviar» (decisión 13): si quien aprueba también envía.
        if request.data.get("enviar") and envia_informes(request.user):
            try:
                informes.enviar(inf, request.user)
            except informes.InformeError as e:
                aviso = " ".join(filter(None, [aviso, f"Aprobado, pero no enviado: {e}"]))
        return Response({**self.get_serializer(inf).data, "aviso": aviso})

    @action(detail=True, methods=["post"])
    def enviar(self, request, pk=None):
        """Envía a la familia un informe aprobado (dirección, Administración y
        quien tenga la función)."""
        if not envia_informes(request.user):
            raise PermissionDenied("Envían los informes dirección, Administración y quien tenga la función.")
        inf = self.get_object()
        try:
            informes.enviar(inf, request.user)
        except informes.InformeError as e:
            raise ValidationError({"detail": str(e)})
        return Response(self.get_serializer(inf).data)

    @action(detail=True, methods=["post"])
    def reabrir(self, request, pk=None):
        """Reabre un informe aprobado para corregirlo; después vuelve a validar."""
        self._validador()
        inf = self.get_object()
        try:
            informes.reabrir(inf, request.user)
        except informes.InformeError as e:
            raise ValidationError({"detail": str(e)})
        return Response(self.get_serializer(inf).data)

    @action(detail=True, methods=["post"])
    def devolver(self, request, pk=None):
        """`{partes: ["tenis", "fisico"], nota}`."""
        self._validador()
        inf = self.get_object()
        try:
            informes.devolver(inf, request.user, request.data.get("partes") or [], str(request.data.get("nota") or ""))
        except informes.InformeError as e:
            raise ValidationError({"detail": str(e)})
        return Response(self.get_serializer(inf).data)

    @action(detail=True, methods=["post"], url_path="guardar-drive")
    def guardar_drive(self, request, pk=None):
        inf = self.get_object()
        if not inf.completo:
            raise ValidationError({"detail": "Faltan partes por terminar."})
        if not (drive.configurado() or drive.ct_configurado()):
            return Response({**self.get_serializer(inf).data, "aviso": "Drive no está conectado."})
        aviso = informes.guardar_en_drive(inf)
        return Response({**self.get_serializer(inf).data, "aviso": aviso})

    @action(detail=False, methods=["get", "post"], url_path=r"foto/(?P<jugador_id>\d+)")
    def foto(self, request, jugador_id=None):
        """La foto del jugador para el informe. POST con el fichero en `foto`."""
        jugador = jugadores_evaluables_fisico().filter(pk=jugador_id).first()
        if jugador is None:
            raise ValidationError({"detail": "Ese jugador no está en Competición de tardes."})
        if request.method == "GET":
            f = FotoJugador.objects.filter(jugador=jugador).first()
            if f is None:
                return Response(status=404)
            return HttpResponse(bytes(f.imagen), content_type=f.tipo)
        subida = request.FILES.get("foto")
        if subida is None:
            raise ValidationError({"foto": "Falta la imagen."})
        if subida.size > 15_000_000:
            raise ValidationError({"foto": "La imagen es demasiado grande (máximo 15 MB)."})
        try:
            from io import BytesIO

            from PIL import Image, ImageOps
            img = ImageOps.exif_transpose(Image.open(subida)).convert("RGB")
            img.thumbnail((900, 900))
            buf = BytesIO()
            img.save(buf, "JPEG", quality=85)
        except Exception:  # noqa: BLE001
            raise ValidationError({"foto": "No se reconoce la imagen. Prueba con una foto JPG o PNG."})
        FotoJugador.objects.update_or_create(jugador=jugador, defaults={
            "imagen": buf.getvalue(), "tipo": "image/jpeg", "subida_por": request.user})
        return Response({"ok": True})


class _DeCoordinador:
    """Lo usa el coordinador de Competición de tardes (y gestión deportiva)."""

    permission_classes = [IsAuthenticated]
    pagination_class = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not coordina_informes(request.user):
            raise PermissionDenied("Esto lo lleva el coordinador de Competición de tardes.")


class JugadorTardesViewSet(_DeCoordinador, viewsets.ModelViewSet):
    """Altas, cambios y bajas de los jugadores de Competición de tardes
    (02/11/2026). Por defecto, los que siguen; `?bajas=1` también los de baja."""

    serializer_class = JugadorTardesSerializer
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        qs = (Jugador.objects.filter(escuela__solo_informes=True)
              .select_related("datos_informe", "asignacion_informe__evaluador__entrenador").order_by("nombre"))
        # La lista enseña los que siguen; una ficha concreta se abre siempre, para poder reactivarla.
        if self.action == "list" and self.request.query_params.get("bajas") not in ("1", "true", "si", "sí"):
            hoy = timezone.localdate()
            qs = qs.filter(Q(fecha_baja__isnull=True) | Q(fecha_baja__gte=hoy))
        return qs

    @action(detail=True, methods=["post"])
    def baja(self, request, pk=None):
        """`{fecha}`: desde ese día deja de salir en Informes y de tener recordatorios."""
        from datetime import date

        j = self.get_object()
        try:
            fecha = date.fromisoformat(str(request.data.get("fecha") or timezone.localdate()))
        except ValueError:
            raise ValidationError({"detail": "Fecha no válida."})
        j.fecha_baja = fecha
        j.save(update_fields=["fecha_baja"])
        return Response(self.get_serializer(j).data)

    @action(detail=True, methods=["post"])
    def reactivar(self, request, pk=None):
        j = self.get_object()
        j.fecha_baja = None
        j.save(update_fields=["fecha_baja"])
        return Response(self.get_serializer(j).data)


class EquipoTardesViewSet(_DeCoordinador, viewsets.ViewSet):
    """Quién hace los informes de Competición de tardes (02/11/2026). GET
    lista el equipo y los candidatos; POST `{usuario, funcion}` da de alta;
    DELETE da de baja."""

    def _fila(self, m):
        return {"id": m.id, "usuario": m.usuario_id, "nombre": _nombre_evaluador(m.usuario), "funcion": m.funcion}

    def list(self, request):
        from django.contrib.auth import get_user_model

        miembros = MiembroTardes.objects.select_related("usuario__entrenador").filter(usuario__is_active=True)
        candidatos = (get_user_model().objects.filter(is_active=True, role__in=["ENTRENADOR", "COACH", "PREPARADOR"])
                      .select_related("entrenador"))
        return Response({
            "miembros": sorted((self._fila(m) for m in miembros), key=lambda f: f["nombre"].lower()),
            "candidatos": sorted(({"id": u.id, "nombre": _nombre_evaluador(u)} for u in candidatos),
                                 key=lambda f: f["nombre"].lower()),
        })

    def create(self, request):
        from django.contrib.auth import get_user_model

        funcion = request.data.get("funcion")
        if funcion not in MiembroTardes.Funcion.values:
            raise ValidationError({"detail": "Elige tenis o preparación física."})
        u = get_user_model().objects.filter(pk=request.data.get("usuario"), is_active=True).first()
        if u is None:
            raise ValidationError({"detail": "Elige a una persona con usuario en la app."})
        m, _ = MiembroTardes.objects.get_or_create(usuario=u, funcion=funcion, defaults={"anadido_por": request.user})
        return Response(self._fila(m), status=201)

    def destroy(self, request, pk=None):
        MiembroTardes.objects.filter(pk=pk).delete()
        return Response(status=204)
