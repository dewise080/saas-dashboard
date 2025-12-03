from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

app_name = "apps.pages"

urlpatterns = [
  path('', views.index,  name='index'),
  path('workflows/', views.workflows, name='workflows'),
  path('credentials/', views.credentials, name='credentials'),
  path('credentials/openai/save/', views.save_openai_key, name='save_openai_key'),
  path('credentials/openai/validate/', views.validate_openai_key, name='validate_openai_key'),
  path('whatsapp/connect/<str:instance_name>/', views.whatsapp_connect, name='whatsapp_connect'),
  path('whatsapp/refresh-qr/<str:instance_name>/', views.whatsapp_refresh_qr, name='whatsapp_refresh_qr'),
  path('whatsapp/status/<str:instance_name>/', views.whatsapp_status_api, name='whatsapp_status_api'),
  path('whatsapp/dashboard/<str:instance_name>/', views.whatsapp_dashboard, name='whatsapp_dashboard'),
  path('whatsapp/dashboard/<str:instance_name>/api/', views.whatsapp_dashboard_api, name='whatsapp_dashboard_api'),
  
  # API endpoints for Pengaa Flow
  path('api/n8n/credentials/', views.api_n8n_credentials, name='api_n8n_credentials'),
]
