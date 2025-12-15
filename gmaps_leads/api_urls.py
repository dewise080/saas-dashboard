from django.urls import path

from . import views

app_name = "gmaps_leads"

urlpatterns = [
    # AI Campaign
    path("ai/campaigns/", views.AICampaignListAPIView.as_view(), name="ai-campaigns"),
    path("ai/campaigns/<int:campaign_id>/recipients/status/", views.AICampaignRecipientStatusAPIView.as_view(), name="ai-campaign-recipient-status"),
    path("ai/campaigns/<int:campaign_id>/recipients/", views.AICampaignRecipientListAPIView.as_view(), name="ai-campaign-recipient-list"),
    path("ai/campaigns/<int:campaign_id>/recipients/<int:recipient_id>/context/", views.AICampaignRecipientContextAPIView.as_view(), name="ai-campaign-recipient-context"),
    path("ai/campaigns/<int:campaign_id>/recipients/<int:recipient_id>/content/", views.AICampaignRecipientContentAPIView.as_view(), name="ai-campaign-recipient-content"),
]
