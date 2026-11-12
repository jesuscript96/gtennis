from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import Funcion

from academy.models import Coach, Entrenador
from academy.permissions import es_direccion, resumen

User = get_user_model()


def _user_payload(user):
    entrenador = getattr(user, "entrenador", None)
    entrenador_info = None
    if entrenador is not None:
        entrenador_info = {
            "id": entrenador.id,
            "nombre": entrenador.nombre,
            "gestiona_todos": entrenador.gestiona_todos_jugadores,
        }
    coach = getattr(user, "coach", None)
    coach_info = None
    if coach is not None:
        coach_info = {
            "id": coach.id,
            "nombre": coach.nombre,
            "entrenadores_ids": list(coach.entrenadores.values_list("id", flat=True)),
        }
    return {
        "id": user.id,
        "username": user.username,
        "nombre": user.get_full_name() or user.username,
        "role": user.role,
        "is_superadmin": user.is_superadmin,
        "is_coach": bool(getattr(user, "is_coach", False)),
        "is_preparador": bool(getattr(user, "is_preparador", False)),
        "is_administracion": bool(getattr(user, "is_administracion", False)),
        **resumen(user),
        "entrenador_id": entrenador.id if entrenador else None,
        "entrenador": entrenador_info,
        "coach_id": coach.id if coach else None,
        "coach": coach_info,
    }


class LoginView(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, **_user_payload(user)})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_user_payload(request.user))


class CambiarPasswordView(APIView):
    """Cada uno cambia su propia contraseña.

    Hace falta la actual: si alguien se deja la sesión abierta, que no le puedan
    cambiar la contraseña sin saberla. Al cambiarla se renueva el token, así que
    las sesiones abiertas en otros sitios dejan de valer.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        actual = request.data.get("actual") or ""
        nueva = request.data.get("nueva") or ""
        if not request.user.check_password(actual):
            raise ValidationError({"actual": "La contraseña actual no es correcta."})
        if len(nueva) < 8:
            raise ValidationError(
                {"nueva": "La contraseña nueva necesita al menos 8 caracteres."})
        if nueva == actual:
            raise ValidationError({"nueva": "La nueva tiene que ser distinta."})
        request.user.set_password(nueva)
        request.user.save(update_fields=["password"])
        Token.objects.filter(user=request.user).delete()
        token = Token.objects.create(user=request.user)
        return Response({"ok": True, "token": token.key})


class CreateUserView(APIView):
    """Alta de usuarios con rol (#16):
      * Coach      → solo la dirección deportiva (Super Admin).
      * Entrenador → dirección o un coach (lo añade a su propio equipo).
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        actor = request.user
        role = (request.data.get("role") or "").upper()
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        nombre = (request.data.get("nombre") or "").strip() or username

        if role not in User.Role.values:
            raise ValidationError("Perfil inválido.")
        if role in (User.Role.SUPERADMIN, User.Role.PREPARADOR, User.Role.ADMINISTRACION) \
                and not actor.is_superadmin:
            raise PermissionDenied("Solo dirección da de alta ese perfil.")
        if not username or not password:
            raise ValidationError("username y password son obligatorios.")
        if role == User.Role.COACH and not actor.is_superadmin:
            raise PermissionDenied("Solo la dirección deportiva crea coaches.")
        if role == User.Role.ENTRENADOR and not (actor.is_superadmin or actor.is_coach):
            raise PermissionDenied("Solo dirección o un coach crean entrenadores.")
        if User.objects.filter(username=username).exists():
            raise ValidationError("Ya existe un usuario con ese nombre.")

        user = User(username=username, role=role, first_name=nombre)
        user.set_password(password)
        user.save()

        if role == User.Role.COACH:
            Coach.objects.create(user=user, nombre=nombre)
        elif role == User.Role.ENTRENADOR:
            entrenador = Entrenador.objects.create(user=user, nombre=nombre)
            actor_coach = getattr(actor, "coach", None)
            if actor_coach is not None:
                actor_coach.entrenadores.add(entrenador)

        return Response(_user_payload(user), status=status.HTTP_201_CREATED)


# --- Club → Personas y funciones (10/11/2026) --------------------------------
# Dirección asigna el perfil y las funciones de cada persona desde la
# aplicación, sin tocar el programa. Evaluar tenis o física de tardes es el
# equipo de Competición de tardes (`evaluaciones.MiembroTardes`).

TARDES = {"TARDES_TENIS": "TENIS", "TARDES_FISICO": "FISICO"}


def _persona(u):
    from evaluaciones.models import MiembroTardes

    tardes = set(MiembroTardes.objects.filter(usuario=u).values_list("funcion", flat=True))
    return {
        "id": u.id,
        "username": u.username,
        "nombre": u.get_full_name() or u.username,
        "role": u.role,
        "perfil": u.perfil,
        "activo": u.is_active,
        "funciones": sorted(u.codigos_funcion()),
        "tardes": sorted(tardes),
    }


class PersonalView(APIView):
    """GET: el personal con su perfil y sus funciones (solo dirección)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not es_direccion(request.user):
            raise PermissionDenied("Solo dirección ve las funciones del personal.")
        usuarios = User.objects.filter(is_active=True).prefetch_related("funciones").order_by(
            "first_name", "username")
        return Response({
            "personas": [_persona(u) for u in usuarios],
            "funciones": [{"codigo": c, "nombre": n} for c, n in Funcion.Codigo.choices]
                + [{"codigo": "TARDES_TENIS", "nombre": "Evalúa tenis de tardes"},
                   {"codigo": "TARDES_FISICO", "nombre": "Evalúa física de tardes"}],
            "perfiles": [{"role": r, "nombre": n} for r, n in User.Role.choices],
        })


class PersonaFuncionView(APIView):
    """POST {codigo, activa}: marca o quita una función. PATCH {role}: cambia
    el perfil. Solo dirección."""

    permission_classes = [IsAuthenticated]

    def _objetivo(self, request, pk):
        if not es_direccion(request.user):
            raise PermissionDenied("Solo dirección asigna funciones.")
        u = User.objects.filter(pk=pk).first()
        if u is None:
            raise ValidationError("No existe esa persona.")
        return u

    @transaction.atomic
    def post(self, request, pk):
        from evaluaciones.models import MiembroTardes

        u = self._objetivo(request, pk)
        codigo = request.data.get("codigo")
        activa = bool(request.data.get("activa"))
        if codigo in TARDES:
            qs = MiembroTardes.objects.filter(usuario=u, funcion=TARDES[codigo])
            if activa and not qs.exists():
                MiembroTardes.objects.create(usuario=u, funcion=TARDES[codigo], anadido_por=request.user)
            elif not activa:
                qs.delete()
        elif codigo in Funcion.Codigo.values:
            if activa:
                Funcion.objects.get_or_create(usuario=u, codigo=codigo,
                                              defaults={"asignada_por": request.user})
            else:
                Funcion.objects.filter(usuario=u, codigo=codigo).delete()
        else:
            raise ValidationError("Función desconocida.")
        u._funciones_cache = None
        return Response(_persona(u))

    @transaction.atomic
    def patch(self, request, pk):
        u = self._objetivo(request, pk)
        role = (request.data.get("role") or "").upper()
        if role not in User.Role.values:
            raise ValidationError("Perfil inválido.")
        if u.pk == request.user.pk and role != User.Role.SUPERADMIN:
            raise ValidationError("No puedes quitarte a ti mismo el perfil de dirección.")
        u.role = role
        u.save(update_fields=["role"])
        if role == User.Role.COACH and getattr(u, "coach", None) is None:
            Coach.objects.create(user=u, nombre=u.get_full_name() or u.username)
        return Response(_persona(u))
