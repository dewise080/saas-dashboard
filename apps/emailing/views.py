from rest_framework import mixins, viewsets

from .models import CampaignRecipient, EmailCampaign, EmailTemplate, Recipient
from .serializers import (
    CampaignRecipientSerializer,
    EmailCampaignSerializer,
    EmailTemplateSerializer,
    RecipientSerializer,
)


class EmailTemplateViewSet(viewsets.ModelViewSet):
    queryset = EmailTemplate.objects.all()
    serializer_class = EmailTemplateSerializer
    filterset_fields = ["is_active"]
    search_fields = ["name", "subject_template", "description"]


class EmailCampaignViewSet(viewsets.ModelViewSet):
    queryset = EmailCampaign.objects.all().select_related("template")
    serializer_class = EmailCampaignSerializer
    filterset_fields = ["status", "provider_alias"]
    search_fields = ["name", "slug", "description"]

    def perform_create(self, serializer):
        campaign = serializer.save()
        if campaign.expected_recipients == 0:
            campaign.expected_recipients = campaign.recipients.count()
            campaign.save(update_fields=["expected_recipients"])


class RecipientViewSet(viewsets.ModelViewSet):
    queryset = Recipient.objects.all()
    serializer_class = RecipientSerializer
    filterset_fields = ["company"]
    search_fields = ["first_name", "last_name", "company", "email_addresses__email"]


class CampaignRecipientViewSet(viewsets.ModelViewSet):
    queryset = CampaignRecipient.objects.select_related("campaign", "recipient", "email_address")
    serializer_class = CampaignRecipientSerializer
    filterset_fields = ["campaign", "status", "provider_alias"]
    search_fields = ["email_address__email", "campaign__name", "subject", "message_id"]
