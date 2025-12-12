from django.urls import include, path

from . import views

app_name = 'gmaps_leads'

urlpatterns = [
    # API endpoints, exposed under /gmaps-leads/api/ when this URLConf is included
    # ==========================================================================
    # Template views - Jobs
    # ==========================================================================
    path('', views.job_list, name='job_list'),
    path('jobs/', views.job_list, name='jobs'),
    path('jobs/create/', views.job_create, name='job_create'),
    path('jobs/<int:pk>/', views.job_detail, name='job_detail'),
    path('jobs/<int:pk>/refresh/', views.job_refresh, name='job_refresh'),
    path('jobs/<int:pk>/import/', views.job_import, name='job_import'),
    
    # Template views - Leads
    path('leads/', views.leads_list, name='leads_list'),
    path('leads/<int:pk>/', views.lead_detail, name='lead_detail'),
    path('leads/export/', views.export_leads_csv, name='export_csv'),
]
