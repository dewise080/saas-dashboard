"""core URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token # <-- NEW
from rest_framework.renderers import JSONOpenAPIRenderer
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from drf_spectacular.renderers import OpenApiJsonRenderer

urlpatterns = [
    path("", include(("accounts_plus.urls", "accounts_plus"), namespace="accounts_plus")),
    path('', include(("apps.pages.urls", "apps.pages"), namespace="apps.pages")),
    path('', include('apps.pages.dashboard_urls')),
    path("n8n/", include("n8n_mirror.urls")),
    path("explorer/", include("explorer.urls")),  # SQL Explorer
    path("gmaps-leads/", include("gmaps_leads.urls")),  # Google Maps Leads
    path("", include('admin_datta.urls')),
    path("admin/", admin.site.urls),
    
    # OpenAPI 3.1 Schema (for AI/LLM integration)
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),  # YAML format
    path('api/openapi.json', SpectacularAPIView.as_view(renderer_classes=[OpenApiJsonRenderer]), name='schema-json'),  # JSON for LLMs
    path('api/schema/swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

# Lazy-load on routing is needed
# During the first build, API is not yet generated
try:
    urlpatterns.append( path("api/"      , include("api.urls"))    )
    urlpatterns.append( path("login/jwt/", view=obtain_auth_token) )
except:
    pass

# Debug toolbar URLs (only in DEBUG mode)
if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        path("__debug__/", include(debug_toolbar.urls)),
    ] + urlpatterns
