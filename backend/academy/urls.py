from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("sedes", views.SedeViewSet)
router.register("pistas", views.PistaViewSet)
router.register("turnos", views.TurnoViewSet)
router.register("divisiones", views.DivisionViewSet)
router.register("entrenadores", views.EntrenadorViewSet)
router.register("jugadores", views.JugadorViewSet)
router.register("rencillas", views.RencillaViewSet)
router.register("contratos", views.ContratoViewSet)

urlpatterns = router.urls
