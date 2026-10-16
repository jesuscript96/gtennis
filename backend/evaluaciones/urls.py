from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("evaluaciones", views.EvaluacionViewSet, basename="evaluacion")

urlpatterns = router.urls
