from typing import Any, Dict

from rest_framework import serializers

from .models import CampaignRecipient, EmailAddress, EmailCampaign, EmailTemplate, Recipient


class EmailAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailAddress
        fields = [
            "id",
            "email",
            "label",
            "is_primary",
            "is_verified",
            "is_active",
            "last_used_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["last_used_at", "created_at", "updated_at"]


class RecipientSerializer(serializers.ModelSerializer):
    email_addresses = EmailAddressSerializer(many=True, required=False)

    class Meta:
        model = Recipient
        fields = [
            "id",
            "first_name",
            "last_name",
            "company",
            "metadata",
            "email_addresses",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def create(self, validated_data: Dict[str, Any]) -> Recipient:
        addresses_data = validated_data.pop("email_addresses", [])
        recipient = Recipient.objects.create(**validated_data)
        for addr in addresses_data:
            EmailAddress.objects.create(recipient=recipient, **addr)
        return recipient

    def update(self, instance: Recipient, validated_data: Dict[str, Any]) -> Recipient:
        addresses_data = validated_data.pop("email_addresses", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if addresses_data is not None:
            # Overwrite addresses when provided explicitly
            instance.email_addresses.all().delete()
            for addr in addresses_data:
                EmailAddress.objects.create(recipient=instance, **addr)
        return instance


class EmailTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = [
            "id",
            "name",
            "description",
            "subject_template",
            "html_template",
            "text_template",
            "is_active",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class EmailCampaignSerializer(serializers.ModelSerializer):
    progress_percent = serializers.FloatField(read_only=True)

    class Meta:
        model = EmailCampaign
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "template",
            "status",
            "default_from_email",
            "default_from_name",
            "provider_alias",
            "default_context",
            "tags",
            "metadata",
            "expected_recipients",
            "sent_count",
            "failed_count",
            "skipped_count",
            "last_dispatched_at",
            "progress_percent",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "sent_count",
            "failed_count",
            "skipped_count",
            "last_dispatched_at",
            "progress_percent",
            "created_at",
            "updated_at",
        ]


class CampaignRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignRecipient
        fields = [
            "id",
            "campaign",
            "recipient",
            "email_address",
            "status",
            "subject",
            "body_html",
            "body_text",
            "context",
            "provider_alias",
            "message_id",
            "last_error",
            "attempted_at",
            "sent_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["attempted_at", "sent_at", "message_id", "created_at", "updated_at", "last_error"]

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        campaign = attrs.get("campaign") or getattr(self.instance, "campaign", None)
        email_address = attrs.get("email_address") or getattr(self.instance, "email_address", None)
        if campaign and email_address:
            exists = CampaignRecipient.objects.filter(campaign=campaign, email_address=email_address)
            if self.instance:
                exists = exists.exclude(pk=self.instance.pk)
            if exists.exists():
                raise serializers.ValidationError("This email address is already attached to the campaign.")
        return attrs
