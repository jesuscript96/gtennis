from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("users.api_urls")),
    path("api/", include("academy.urls")),
    path("api/", include("scheduling.urls")),
]
