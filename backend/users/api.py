from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from academy.models import Coach, Entrenador

User = get_user_model()


def _user_payload(user):
    entrenador = getattr(user, "entrenador", None)
    entrenador_info = None
    if entrenador is not None:
        entrenador_info = {
            "id": entrenador.id,
            "nombre": entrenador.nombre,
            "gestiona_todos": entrenador.gestiona_todos_jugadores,
            # Vacío cuando gestiona a todos (no hace falta enumerarlos).
            "jugadores_ids": (
                []
                if entrenador.gestiona_todos_jugadores
                else list(
                    entrenador.jugadores_gestionados.values_list("id", flat=True)
                )
            ),
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
        "username": user.username,
        "nombre": user.get_full_name() or user.username,
        "role": user.role,
        "is_superadmin": user.is_superadmin,
        "is_coach": bool(getattr(user, "is_coach", False)),
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

        if role not in (User.Role.COACH, User.Role.ENTRENADOR):
            raise ValidationError("Rol inválido: usa COACH o ENTRENADOR.")
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
        else:
            entrenador = Entrenador.objects.create(user=user, nombre=nombre)
            actor_coach = getattr(actor, "coach", None)
            if actor_coach is not None:
                actor_coach.entrenadores.add(entrenador)

        return Response(_user_payload(user), status=status.HTTP_201_CREATED)
