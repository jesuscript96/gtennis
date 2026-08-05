from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


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
    return {
        "username": user.username,
        "nombre": user.get_full_name() or user.username,
        "role": user.role,
        "is_superadmin": user.is_superadmin,
        "entrenador_id": entrenador.id if entrenador else None,
        "entrenador": entrenador_info,
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
