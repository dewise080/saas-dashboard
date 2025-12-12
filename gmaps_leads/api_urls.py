from django.urls import path

from . import views

app_name = "gmaps_leads"

urlpatterns = [
    # Minimal API: contactable leads + email template CRUD
    path("leads/contactable/", views.ContactableLeadsAPIView.as_view(), name="api-leads-contactable"),
    # AI Integration: Lead category stats for GPT onboarding
    path("leads/category-stats/", views.LeadCategoryStatsAPIView.as_view(), name="api-leads-category-stats"),
    # AI Integration: Lead context for personalization
    path("leads/<int:lead_id>/context/", views.LeadContextAPIView.as_view(), name="api-lead-context"),
    # AI Integration: Customized contact CRUD for a specific lead
    path("leads/<int:lead_id>/customized-contact/", views.LeadEmailTemplateAPIView.as_view(), name="api-lead-customized-contact"),
    path("customized-contacts/", views.EmailTemplateListAPIView.as_view(), name="api-customized-contacts"),
    path("customized-contacts/<int:template_id>/", views.EmailTemplateAPIView.as_view(), name="api-customized-contact-detail"),
    path("customized-contacts/<int:template_id>/status/", views.EmailTemplateStatusAPIView.as_view(), name="api-customized-contact-status"),
]
