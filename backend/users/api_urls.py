from django.urls import path

from .api import CreateUserView, LoginView, MeView

urlpatterns = [
    path("token/", LoginView.as_view()),
    path("me/", MeView.as_view()),
    path("users/", CreateUserView.as_view()),
]
