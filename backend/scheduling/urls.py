from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("semanas", views.SemanaViewSet)
router.register("disponibilidades", views.DisponibilidadViewSet, basename="disponibilidad")
router.register("disponibilidades-entrenador", views.DisponibilidadEntrenadorViewSet, basename="disponibilidad-entrenador")
router.register("asignaciones", views.AsignacionViewSet)

urlpatterns = router.urls + [
    path("configuracion/", views.ConfiguracionView.as_view()),
    path("ahora/", views.AhoraView.as_view()),
]
