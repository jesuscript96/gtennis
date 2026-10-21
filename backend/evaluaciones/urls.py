from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("evaluaciones", views.EvaluacionViewSet, basename="evaluacion")
router.register("evaluaciones-fisicas", views.EvaluacionFisicaViewSet, basename="evaluacion-fisica")

urlpatterns = router.urls
