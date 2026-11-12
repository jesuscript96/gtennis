from django.urls import path

from .api import CambiarPasswordView, CreateUserView, LoginView, MeView, PersonaFuncionView, PersonalView

urlpatterns = [
    path("token/", LoginView.as_view()),
    path("me/", MeView.as_view()),
    path("users/", CreateUserView.as_view()),
    path("password/", CambiarPasswordView.as_view()),
    path("personal/", PersonalView.as_view()),
    path("personal/<int:pk>/", PersonaFuncionView.as_view()),
]
