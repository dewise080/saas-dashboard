from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'gmaps_leads'

# API Router
router = DefaultRouter()
router.register(r'jobs', views.ScrapeJobViewSet, basename='api-jobs')
router.register(r'leads', views.GmapsLeadViewSet, basename='api-leads')

urlpatterns = [
    # API endpoints (DRF Router)
    path('api/', include(router.urls)),
    
    # ==========================================================================
    # AI Email Generation API (OpenAPI 3.1)
    # ==========================================================================
    
    # Lead context for AI consumption
    path('api/leads/<int:lead_id>/context/', 
         views.LeadContextAPIView.as_view(), 
         name='api-lead-context'),
    
    # Email templates for a specific lead
    path('api/leads/<int:lead_id>/email-template/', 
         views.LeadEmailTemplateAPIView.as_view(), 
         name='api-lead-email-template'),
    path('api/leads/<int:lead_id>/email-templates/', 
         views.LeadEmailTemplateAPIView.as_view(), 
         name='api-lead-email-templates'),
    
    # Email template management
    path('api/email-templates/', 
         views.EmailTemplateListAPIView.as_view(), 
         name='api-email-templates'),
    path('api/email-templates/<int:template_id>/', 
         views.EmailTemplateAPIView.as_view(), 
         name='api-email-template-detail'),
    path('api/email-templates/<int:template_id>/status/', 
         views.EmailTemplateStatusAPIView.as_view(), 
         name='api-email-template-status'),
    
    # AI helper endpoint: leads ready for outreach
    path('api/leads/with-emails/', 
         views.LeadsWithEmailsAPIView.as_view(), 
         name='api-leads-with-emails'),
    
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
