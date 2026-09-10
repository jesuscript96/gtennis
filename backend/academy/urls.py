from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("sedes", views.SedeViewSet)
router.register("pistas", views.PistaViewSet)
router.register("turnos", views.TurnoViewSet)
router.register("divisiones", views.DivisionViewSet)
router.register("entrenadores", views.EntrenadorViewSet)
router.register("coaches", views.CoachViewSet)
router.register("mi-agenda", views.MiAgendaViewSet, basename="mi-agenda")
router.register("jugadores", views.JugadorViewSet)
router.register("rencillas", views.RencillaViewSet)
router.register("contratos", views.ContratoViewSet)
router.register("responsables", views.ResponsableJugadorViewSet)
router.register("vacaciones", views.VacacionesEntrenadorViewSet)
router.register("escuelas", views.EscuelaViewSet)
router.register("preferencias-superficie", views.PreferenciaSuperficieViewSet)
router.register("avisos", views.AvisoViewSet, basename="aviso")
router.register("invitados", views.InvitadoViewSet, basename="invitado")
router.register("mantenimiento", views.TareaMantenimientoViewSet)
router.register("feedback", views.FeedbackViewSet)

urlpatterns = router.urls
