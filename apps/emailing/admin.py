from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.timezone import now
from django import forms
from ckeditor.widgets import CKEditorWidget
from .models import (
    CampaignRecipient,
    EmailAddress,
    EmailCampaign,
    EmailSend,
    EmailTemplate,
    Recipient,
)
from .services import send_email


class CampaignRecipientAdminForm(forms.ModelForm):
    class Meta:
        model = CampaignRecipient
        fields = "__all__"
        widgets = {
            "body_html": CKEditorWidget(),
        }


class EmailSendAdminForm(forms.ModelForm):
    class Meta:
        model = EmailSend
        fields = "__all__"
        widgets = {
            "html_body": CKEditorWidget(),
        }


class EmailAddressInline(admin.TabularInline):
    model = EmailAddress
    extra = 0
    fields = ["email", "label", "is_primary", "is_verified", "is_active", "last_used_at"]
    readonly_fields = ["last_used_at", "created_at", "updated_at"]


@admin.register(Recipient)
class RecipientAdmin(admin.ModelAdmin):
    list_display = ["full_name", "company", "primary_email", "created_at"]
    search_fields = ["first_name", "last_name", "company", "email_addresses__email"]
    inlines = [EmailAddressInline]
    readonly_fields = ["created_at", "updated_at"]

    def primary_email(self, obj):
        primary = obj.email_addresses.filter(is_primary=True).first() or obj.email_addresses.first()
        return primary.email if primary else "-"
    primary_email.short_description = "Email"


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "subject_template", "is_active", "updated_at"]
    list_filter = ["is_active", "created_at"]
    search_fields = ["name", "subject_template"]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        ("Metadata", {"fields": ("name", "description", "is_active", "metadata")}),
        ("Content", {"fields": ("subject_template", "html_template", "text_template")}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


class CampaignRecipientInline(admin.TabularInline):
    model = CampaignRecipient
    extra = 0
    fields = [
        "email_address",
        "status",
        "provider_alias",
        "subject",
        "sent_at",
        "message_id",
    ]
    readonly_fields = ["sent_at", "message_id", "attempted_at", "created_at", "updated_at"]


@admin.register(EmailCampaign)
class EmailCampaignAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "status",
        "provider_alias",
        "progress_bar",
        "sent_count",
        "failed_count",
        "skipped_count",
        "updated_at",
    ]
    list_filter = ["status", "provider_alias", "created_at"]
    search_fields = ["name", "slug", "description"]
    inlines = [CampaignRecipientInline]
    readonly_fields = ["sent_count", "failed_count", "skipped_count", "created_at", "updated_at", "last_dispatched_at"]
    actions = ["send_ready_recipients", "refresh_progress"]

    fieldsets = (
        ("Basics", {"fields": ("name", "slug", "description", "status")}),
        ("Delivery Defaults", {"fields": ("template", "default_from_name", "default_from_email", "provider_alias", "tags")}),
        ("Context & Metadata", {"fields": ("default_context", "metadata")}),
        ("Progress", {"fields": ("expected_recipients", "sent_count", "failed_count", "skipped_count", "last_dispatched_at")}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def progress_bar(self, obj):
        percent = obj.progress_percent
        color = "#28a745" if percent == 100 else "#17a2b8" if percent >= 50 else "#ffc107"
        return format_html(
            '<div style="width: 120px; background: #f1f1f1; border-radius: 4px;">'
            '<div style="width: {}%; background: {}; color: #fff; padding: 2px 6px; border-radius: 4px; text-align: right;">{}%</div>'
            "</div>",
            percent,
            color,
            percent,
        )
    progress_bar.short_description = "Progress"

    @admin.action(description="Send READY recipients now")
    def send_ready_recipients(self, request, queryset):
        from .models import CampaignRecipient

        total_sent = total_failed = total_skipped = 0
        for campaign in queryset.select_related("template"):
            ready_qs = campaign.recipients.filter(status__in=[CampaignRecipient.STATUS_READY, CampaignRecipient.STATUS_PENDING])
            sent = failed = skipped = 0
            for cr in ready_qs.select_related("recipient", "email_address", "campaign", "campaign__template"):
                try:
                    if not cr.email_address or not cr.email_address.is_active:
                        skipped += 1
                        cr.status = CampaignRecipient.STATUS_SKIPPED
                        cr.last_error = "Email missing or inactive"
                        cr.save(update_fields=["status", "last_error", "updated_at"])
                        continue
                    CampaignRecipientAdmin._send_recipient(self, request, cr)
                    sent += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    cr.status = CampaignRecipient.STATUS_FAILED
                    cr.last_error = str(exc)
                    cr.save(update_fields=["status", "last_error", "updated_at"])
            campaign.refresh_counters(commit=True)
            campaign.last_dispatched_at = now()
            campaign.save(update_fields=["last_dispatched_at", "updated_at"])
            total_sent += sent
            total_failed += failed
            total_skipped += skipped
        messages.info(
            request,
            f"Send complete. Sent: {total_sent}, Failed: {total_failed}, Skipped: {total_skipped}",
        )

    @admin.action(description="Refresh progress counters")
    def refresh_progress(self, request, queryset):
        for campaign in queryset:
            campaign.refresh_counters(commit=True)
        messages.success(request, f"Progress refreshed for {queryset.count()} campaign(s).")


@admin.register(CampaignRecipient)
class CampaignRecipientAdmin(admin.ModelAdmin):
    form = CampaignRecipientAdminForm
    list_display = ["campaign", "email_address", "status", "provider_alias", "sent_at", "attempted_at"]
    list_filter = ["status", "provider_alias", "campaign"]
    search_fields = ["email_address__email", "campaign__name", "subject", "message_id"]
    readonly_fields = ["message_id", "attempted_at", "sent_at", "created_at", "updated_at"]
    actions = ["send_selected_now", "mark_selected_skipped"]
    fieldsets = (
        ("Links", {"fields": ("campaign", "recipient", "email_address")}),
        ("Content", {"fields": ("status", "subject", "body_html", "body_text", "context", "provider_alias")}),
        ("Delivery", {"fields": ("message_id", "attempted_at", "sent_at", "last_error")}),
        ("Metadata", {"fields": ("metadata",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def _send_recipient(self, request, cr: CampaignRecipient) -> bool:
        """Send a single CampaignRecipient via send_email. Returns True if sent/attempted without crash."""
        if not cr.email_address:
            cr.status = CampaignRecipient.STATUS_SKIPPED
            cr.last_error = "No email address linked."
            cr.save(update_fields=["status", "last_error", "updated_at"])
            return False

        # Determine content: prefer stored per-recipient content; otherwise fall back to campaign template
        subject = cr.subject
        html_body = cr.body_html
        context = {
            **(cr.campaign.default_context or {}),
            **(cr.context or {}),
            "recipient_name": cr.recipient.full_name if cr.recipient else "",
            "company": cr.recipient.company if cr.recipient else "",
        }

        template_id = None
        if cr.campaign.template:
            template_id = cr.campaign.template_id
            subject = subject or cr.campaign.template.subject_template
            html_body = html_body or cr.campaign.template.html_template
        else:
            subject = subject or "Hello"
            html_body = html_body or "<p>Hello,</p><p>This is a sample message.</p>"

        metadata = {
            "campaign_id": cr.campaign_id,
            "campaign_recipient_id": cr.id,
            "recipient_id": cr.recipient_id,
            "email_address_id": cr.email_address_id,
            "provider": cr.provider_alias or cr.campaign.provider_alias or None,
            "template_id": template_id,
            "esp_metadata": {"admin_action": "send_now"},
        }

        send_email(
            to=cr.email_address,
            subject=subject,
            html_body=html_body,
            context=context,
            metadata=metadata,
        )
        return True

    @admin.action(description="Send selected now")
    def send_selected_now(self, request, queryset):
        sent = failed = skipped = 0
        for cr in queryset.select_related("campaign", "recipient", "email_address", "campaign__template"):
            try:
                if not cr.email_address or not cr.email_address.is_active:
                    skipped += 1
                    cr.status = CampaignRecipient.STATUS_SKIPPED
                    cr.last_error = "Email missing or inactive"
                    cr.save(update_fields=["status", "last_error", "updated_at"])
                    continue
                self._send_recipient(request, cr)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                cr.status = CampaignRecipient.STATUS_FAILED
                cr.last_error = str(exc)
                cr.save(update_fields=["status", "last_error", "updated_at"])
        # Refresh counters for affected campaigns
        campaign_ids = queryset.values_list("campaign_id", flat=True).distinct()
        for campaign_id in campaign_ids:
            campaign = EmailCampaign.objects.filter(id=campaign_id).first()
            if campaign:
                campaign.refresh_counters(commit=True)
        messages.info(request, f"Send action complete. Sent: {sent}, Failed: {failed}, Skipped: {skipped}")

    @admin.action(description="Mark selected as skipped")
    def mark_selected_skipped(self, request, queryset):
        count = queryset.update(status=CampaignRecipient.STATUS_SKIPPED, last_error="Manually skipped in admin", updated_at=now())
        campaign_ids = queryset.values_list("campaign_id", flat=True).distinct()
        for campaign_id in campaign_ids:
            campaign = EmailCampaign.objects.filter(id=campaign_id).first()
            if campaign:
                campaign.refresh_counters(commit=True)
        messages.info(request, f"Marked {count} recipients as skipped.")


@admin.register(EmailSend)
class EmailSendAdmin(admin.ModelAdmin):
    form = EmailSendAdminForm
    list_display = ["to_email", "status", "provider_alias", "campaign", "sent_at", "created_at"]
    list_filter = ["status", "provider_alias", "campaign"]
    search_fields = ["to_email", "subject", "message_id", "campaign__name"]
    readonly_fields = [
        "message_id",
        "created_at",
        "updated_at",
        "sent_at",
        "campaign",
        "campaign_recipient",
        "recipient",
        "email_address",
    ]
    fieldsets = (
        ("Message", {"fields": ("to_email", "subject", "status", "provider_alias", "backend_path")}),
        ("Content", {"fields": ("html_body", "text_body", "context", "metadata")}),
        ("Routing", {"fields": ("campaign", "campaign_recipient", "recipient", "email_address")}),
        ("ESP Details", {"fields": ("message_id", "error_message")}),
        ("Timestamps", {"fields": ("created_at", "updated_at", "sent_at"), "classes": ("collapse",)}),
    )
