from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("torneos", views.TorneoViewSet, basename="torneo")
router.register("torneos-participantes", views.ParticipanteViewSet, basename="torneo-participante")

urlpatterns = router.urls
