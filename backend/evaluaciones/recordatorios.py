"""Recordatorios del ciclo de informes de Competición de tardes (27/10/2026).

Una vez al día (lo llama el programador): a quien evalúa se le recuerda la
primera evaluación de un jugador nuevo a la semana de su alta, y la siguiente
a los 75 días («toca pronto») y a los 90 («vencido») de validar el último; a
los 90 se avisa también a quien valida. Cada recordatorio se da una sola vez
(`RecordatorioInforme`) y se agrupa en un aviso por persona con la lista de
jugadores, para no llenar la bandeja de avisos.
"""
from collections import defaultdict
from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from academy.models import Aviso, Jugador
from academy.permissions import usuarios_valida_informes

from . import informes
from .models import AsignacionInforme, Informe, RecordatorioInforme

SIN_ALTA = date(2000, 1, 1)
ETAPA = {"primera": RecordatorioInforme.Etapa.PRIMERA, "pronto": RecordatorioInforme.Etapa.D75,
         "vencido": RecordatorioInforme.Etapa.D90}


def _jugadores():
    hoy = timezone.localdate()
    from django.db.models import Q
    return (Jugador.objects.filter(escuela__solo_informes=True)
            .filter(Q(fecha_baja__isnull=True) | Q(fecha_baja__gte=hoy)).select_related("escuela"))


def revisar(hoy=None):
    """Da los recordatorios que tocan hoy. Devuelve cuántos jugadores entraron."""
    hoy = hoy or timezone.localdate()
    por_usuario = defaultdict(lambda: defaultdict(list))  # usuario -> etapa -> [nombres]
    usuarios = {}
    nuevos = 0
    validadores = usuarios_valida_informes()
    # Sin entrenador asignado, el recordatorio va al coordinador para que lo reparta.
    sin_asignar = informes.coordinadores() or informes.evaluadores_tenis_por_defecto()
    asignados = dict(AsignacionInforme.objects.filter(evaluador__is_active=True)
                     .values_list("jugador_id", "evaluador_id"))
    fisicos = informes.preparadores()
    for j in _jugadores():
        c = informes.ciclo(j, hoy)
        if c["estado"] not in ETAPA:
            continue
        # Si ya hay un informe en marcha después del último validado, no hace falta recordar.
        abierto = informes.informe_abierto(j, crear=False)
        if abierto is not None and (abierto.tenis_id or abierto.fisica_id):
            continue
        # Fecha fija de cada ciclo (alta o última validación); sin alta, una fija
        # para que el «primer informe» se recuerde una vez y no cada día.
        referencia = c["desde"] or SIN_ALTA
        try:
            with transaction.atomic():
                RecordatorioInforme.objects.create(jugador=j, etapa=ETAPA[c["estado"]], referencia=referencia)
        except IntegrityError:
            continue  # ya recordado
        nuevos += 1
        destinatarios = [(u, c["estado"]) for u in fisicos]
        if j.id in asignados:
            destinatarios.append((asignados[j.id], c["estado"]))
        else:
            destinatarios += [(u, "sin_asignar") for u in sin_asignar]
        if c["estado"] == "vencido":
            destinatarios += [(u, c["estado"]) for u in validadores]
        for u, etapa in destinatarios:
            if u is None:
                continue
            if isinstance(u, int):
                u = usuarios.get(u) or get_user_model().objects.get(pk=u)
            usuarios[u.pk] = u
            if j.nombre not in por_usuario[u.pk][etapa]:
                por_usuario[u.pk][etapa].append(j.nombre)
    textos = {
        "primera": ("Toca el primer informe", "Jugadores de Competición de tardes que aún no tienen informe"),
        "pronto": ("Toca pronto el siguiente informe", "Han pasado 75 días desde su último informe"),
        "vencido": ("Informe vencido", "Han pasado 90 días desde su último informe"),
        "sin_asignar": ("Toca informe y no tienen entrenador",
                        "Les toca el informe y aún no tienen entrenador asignado"),
    }
    for uid, etapas in por_usuario.items():
        for etapa, nombres in etapas.items():
            titulo, explica = textos[etapa]
            lista = ", ".join(nombres[:12]) + (f" y {len(nombres) - 12} más" if len(nombres) > 12 else "")
            Aviso.objects.create(usuario=usuarios[uid], tipo=Aviso.Tipo.GENERAL,
                                 titulo=f"{titulo}: {len(nombres)} jugador{'es' if len(nombres) != 1 else ''}",
                                 mensaje=f"{explica}: {lista}. Lo tienes en Informes.")
    return nuevos
