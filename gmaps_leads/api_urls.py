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

    # WAHA (WhatsApp HTTP API)
    path("waha/health/", views.WahaHealthAPIView.as_view(), name="waha-health"),
    path("waha/contacts/sync/", views.WahaContactSyncAPIView.as_view(), name="waha-contact-sync"),
    path("waha/messages/send/", views.WahaSendMessageAPIView.as_view(), name="waha-send-message"),
    path("waha/messages/test/", views.WahaTestMessageAPIView.as_view(), name="waha-test-message"),
    path("waha/campaigns/", views.WhatsAppCampaignAPIView.as_view(), name="waha-campaigns"),
    path("waha/campaigns/<int:campaign_id>/prepare/", views.WhatsAppCampaignPrepareAPIView.as_view(), name="waha-campaign-prepare"),
    path("waha/campaigns/<int:campaign_id>/run/", views.WhatsAppCampaignRunAPIView.as_view(), name="waha-campaign-run"),
    path("waha/campaigns/<int:campaign_id>/recipients/", views.WhatsAppCampaignRecipientsAPIView.as_view(), name="waha-campaign-recipients"),
    path("waha/template-pools/", views.WhatsAppTemplatePoolAPIView.as_view(), name="waha-template-pools"),
    path("waha/templates/", views.WhatsAppTemplateAPIView.as_view(), name="waha-templates"),

    # Chatwoot contacts sync
    path("chatwoot/contacts/sync/", views.ChatwootContactSyncAPIView.as_view(), name="chatwoot-contact-sync"),

    # AI Assistant Memory (GET all, POST new)
    path("ai/memory/", views.AIMemoryListCreateAPIView.as_view(), name="ai-memory"),
]
