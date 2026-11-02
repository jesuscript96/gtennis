from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("evaluaciones", views.EvaluacionViewSet, basename="evaluacion")
router.register("evaluaciones-fisicas", views.EvaluacionFisicaViewSet, basename="evaluacion-fisica")
router.register("informes", views.InformeViewSet, basename="informe")
router.register("tardes/jugadores", views.JugadorTardesViewSet, basename="tardes-jugador")
router.register("tardes/equipo", views.EquipoTardesViewSet, basename="tardes-equipo")

urlpatterns = router.urls
