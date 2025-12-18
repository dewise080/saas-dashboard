from __future__ import annotations

from email.utils import formataddr
from typing import Any, Dict, Optional, Tuple, Union

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template import engines
from django.utils import timezone
from django.utils.html import strip_tags

from .chatwoot import ChatwootClient
from .models import CampaignRecipient, EmailAddress, EmailCampaign, EmailSend, EmailTemplate, Recipient

RecipientType = Union[str, EmailAddress, Recipient]


def _resolve_provider(alias: Optional[str]) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    providers = getattr(settings, "EMAIL_PROVIDERS", {}) or {}
    default_alias = getattr(settings, "EMAIL_PROVIDER", None)
    resolved_alias = alias or default_alias
    provider = providers.get(resolved_alias) or providers.get(default_alias, {}) or {}
    backend_path = provider.get("BACKEND", getattr(settings, "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"))

    connection_kwargs = provider.get("OPTIONS", {}).copy() if provider.get("OPTIONS") else {}
    if backend_path.endswith("smtp.EmailBackend"):
        connection_kwargs.update(
            {
                "host": provider.get("HOST", getattr(settings, "EMAIL_HOST", None)),
                "port": provider.get("PORT", getattr(settings, "EMAIL_PORT", None)),
                "username": provider.get("USERNAME", getattr(settings, "EMAIL_HOST_USER", None)),
                "password": provider.get("PASSWORD", getattr(settings, "EMAIL_HOST_PASSWORD", None)),
                "use_tls": provider.get("USE_TLS", getattr(settings, "EMAIL_USE_TLS", None)),
                "use_ssl": provider.get("USE_SSL", getattr(settings, "EMAIL_USE_SSL", None)),
                "timeout": provider.get("TIMEOUT", None),
            }
        )
    return resolved_alias or "", backend_path, connection_kwargs


def _render_templates(
    subject: str,
    html_body: str,
    text_body: Optional[str],
    context: Optional[Dict[str, Any]],
) -> Tuple[str, str, str]:
    """Render Django templates when context is provided."""
    if not context:
        rendered_html = html_body
        rendered_subject = subject
        rendered_text = text_body or strip_tags(rendered_html)
        return rendered_subject, rendered_html, rendered_text

    template_engine = engines["django"]
    rendered_subject = template_engine.from_string(subject).render(context)
    rendered_html = template_engine.from_string(html_body).render(context)
    rendered_text = (
        template_engine.from_string(text_body).render(context)
        if text_body
        else strip_tags(rendered_html)
    )
    return rendered_subject, rendered_html, rendered_text


def _extract_email(to: RecipientType) -> Tuple[str, Optional[EmailAddress], Optional[Recipient]]:
    if isinstance(to, EmailAddress):
        return to.email, to, to.recipient
    if isinstance(to, Recipient):
        email_obj = to.email_addresses.filter(is_primary=True).first() or to.email_addresses.first()
        if not email_obj:
            return "", None, to
        return email_obj.email, email_obj, to
    return str(to), None, None


def send_email(
    to: RecipientType,
    subject: str,
    html_body: str,
    context: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> EmailSend:
    """
    Send a single email with per-recipient rendering and pluggable providers.

    Parameters:
        to: email string, EmailAddress instance, or Recipient (primary email is used).
        subject: either a literal subject or a Django template string.
        html_body: full HTML content (rendered or templated). If a stored template is provided
                   in metadata['template'] or metadata['template_id'], it will override this value.
        context: optional dict used to render subject/body when templated content is provided.
        metadata: optional dict supporting:
            - provider: key from settings.EMAIL_PROVIDERS to override the default backend
            - from_email / reply_to / tags / esp_metadata / headers
            - template / template_id: EmailTemplate to render subject/body
            - campaign_id / campaign_recipient_id / recipient_id / email_address_id for tracking
    """

    context = context or {}
    metadata = metadata or {}

    # Resolve recipient and basic validation
    to_email, email_address, recipient = _extract_email(to)
    if not to_email:
        record = EmailSend.objects.create(
            to_email="",
            subject=subject,
            html_body=html_body,
            text_body="",
            context=context,
            metadata=metadata,
            status=EmailSend.STATUS_SKIPPED,
            error_message="No email address available for recipient",
        )
        return record

    if email_address and not email_address.is_active:
        record = EmailSend.objects.create(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body="",
            context=context,
            metadata=metadata,
            status=EmailSend.STATUS_SKIPPED,
            error_message="Email address is marked inactive",
            recipient=recipient,
            email_address=email_address,
        )
        return record

    template_obj = metadata.get("template")
    if template_obj and not isinstance(template_obj, EmailTemplate):
        template_obj = EmailTemplate.objects.filter(pk=template_obj).first()
    if not template_obj and metadata.get("template_id"):
        template_obj = EmailTemplate.objects.filter(pk=metadata["template_id"]).first()

    base_subject = subject
    base_html = html_body
    base_text = None

    if template_obj:
        base_subject = template_obj.subject_template
        base_html = template_obj.html_template
        base_text = template_obj.text_template or None

    rendered_subject, rendered_html, rendered_text = _render_templates(
        base_subject, base_html, base_text, context
    )

    campaign = None
    campaign_recipient = None
    if metadata.get("campaign_id"):
        campaign = EmailCampaign.objects.filter(pk=metadata["campaign_id"]).first()
    if metadata.get("campaign_recipient_id"):
        campaign_recipient = CampaignRecipient.objects.filter(pk=metadata["campaign_recipient_id"]).first()
        if campaign_recipient and not campaign:
            campaign = campaign_recipient.campaign
        if campaign_recipient and not recipient:
            recipient = campaign_recipient.recipient
        if campaign_recipient and not email_address:
            email_address = campaign_recipient.email_address

    provider_key = (
        metadata.get("provider")
        or (campaign_recipient.provider_alias if campaign_recipient else None)
        or (campaign.provider_alias if campaign else None)
    )
    provider_alias, backend_path, connection_kwargs = _resolve_provider(provider_key)

    from_email = (
        metadata.get("from_email")
        or (campaign.default_from_email if campaign and campaign.default_from_email else None)
        or (template_obj.metadata.get("from_email") if template_obj and template_obj.metadata else None)
        or getattr(settings, "DEFAULT_FROM_EMAIL", None)
    )
    from_name = (
        metadata.get("from_name")
        or (campaign.default_from_name if campaign and campaign.default_from_name else None)
        or (template_obj.metadata.get("from_name") if template_obj and template_obj.metadata else None)
        or ""
    )
    if from_name and from_email and "<" not in from_email:
        from_email = formataddr((from_name, from_email))

    connection = get_connection(backend=backend_path, **{k: v for k, v in connection_kwargs.items() if v is not None})

    record = EmailSend.objects.create(
        to_email=to_email,
        subject=rendered_subject,
        html_body=rendered_html,
        text_body=rendered_text,
        context=context,
        metadata=metadata,
        provider_alias=provider_alias,
        backend_path=backend_path,
        campaign=campaign,
        campaign_recipient=campaign_recipient,
        recipient=recipient,
        email_address=email_address,
    )

    if campaign_recipient:
        campaign_recipient.status = CampaignRecipient.STATUS_SENDING
        campaign_recipient.attempted_at = timezone.now()
        campaign_recipient.save(update_fields=["status", "attempted_at", "updated_at"])

    message = EmailMultiAlternatives(
        subject=rendered_subject,
        body=rendered_text,
        from_email=from_email,
        to=[to_email],
        connection=connection,
    )
    message.attach_alternative(rendered_html, "text/html")

    if metadata.get("reply_to"):
        message.reply_to = metadata["reply_to"] if isinstance(metadata["reply_to"], (list, tuple)) else [metadata["reply_to"]]
    if metadata.get("headers"):
        message.extra_headers = metadata["headers"]
    if metadata.get("tags"):
        setattr(message, "tags", metadata["tags"])
    if metadata.get("esp_metadata"):
        setattr(message, "metadata", metadata["esp_metadata"])

    try:
        message.send()
        record.status = EmailSend.STATUS_SENT
        record.sent_at = timezone.now()
        record.message_id = getattr(message, "anymail_message_id", "") or getattr(message, "message_id", "")
        record.save(update_fields=["status", "sent_at", "message_id", "updated_at"])

        if email_address:
            email_address.last_used_at = record.sent_at
            email_address.save(update_fields=["last_used_at"])

        if campaign_recipient:
            campaign_recipient.status = CampaignRecipient.STATUS_SENT
            campaign_recipient.sent_at = record.sent_at
            campaign_recipient.message_id = record.message_id
            campaign_recipient.provider_alias = provider_alias or campaign_recipient.provider_alias
            campaign_recipient.save(
                update_fields=["status", "sent_at", "message_id", "provider_alias", "updated_at"]
            )
            campaign_recipient.campaign.refresh_counters(commit=True)
        # Chatwoot threading (optional, non-blocking)
        chatwoot = ChatwootClient()
        if chatwoot.configured:
            try:
                cw_result = chatwoot.log_outgoing_email(
                    to_email=to_email,
                    subject=rendered_subject,
                    text_body=rendered_text,
                    html_body=rendered_html,
                    from_email=from_email or "",
                    context=context,
                    send_metadata={
                        "campaign_id": campaign.id if campaign else None,
                        "campaign_recipient_id": campaign_recipient.id if campaign_recipient else None,
                        "email_send_id": record.id,
                        "provider_alias": provider_alias,
                        "metadata": metadata,
                    },
                )
                updated_meta = record.metadata or {}
                updated_meta["chatwoot"] = cw_result
                record.metadata = updated_meta
                record.save(update_fields=["metadata", "updated_at"])
            except Exception as exc:  # noqa: BLE001
                updated_meta = record.metadata or {}
                updated_meta["chatwoot_error"] = str(exc)
                record.metadata = updated_meta
                record.save(update_fields=["metadata", "updated_at"])
        return record
    except Exception as exc:  # noqa: BLE001
        record.status = EmailSend.STATUS_FAILED
        record.error_message = str(exc)
        record.save(update_fields=["status", "error_message", "updated_at"])

        if campaign_recipient:
            campaign_recipient.status = CampaignRecipient.STATUS_FAILED
            campaign_recipient.last_error = str(exc)
            campaign_recipient.save(update_fields=["status", "last_error", "updated_at"])
            campaign_recipient.campaign.refresh_counters(commit=True)
        raise
