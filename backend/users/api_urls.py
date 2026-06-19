from django.urls import path

from .api import LoginView, MeView

urlpatterns = [
    path("token/", LoginView.as_view()),
    path("me/", MeView.as_view()),
]
