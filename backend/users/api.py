from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


def _user_payload(user):
    entrenador_id = None
    if hasattr(user, "entrenador") and user.entrenador:
        entrenador_id = user.entrenador.id
    return {
        "username": user.username,
        "nombre": user.get_full_name() or user.username,
        "role": user.role,
        "is_superadmin": user.is_superadmin,
        "entrenador_id": entrenador_id,
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
