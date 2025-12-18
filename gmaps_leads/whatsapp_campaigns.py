import random
from typing import Any, Dict, List, Optional

from django.utils import timezone

from .models import (
    GmapsLead,
    WhatsAppCampaign,
    WhatsAppCampaignRecipient,
    WhatsAppContact,
    WhatsAppTemplate,
    WhatsAppTemplatePool,
)


def render_whatsapp_template(text: str, lead: GmapsLead) -> str:
    replacements = {
        "{{business_name}}": lead.title or "",
        "{{category}}": lead.category or "",
        "{{website}}": lead.website or "",
    }
    rendered = text
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


def compose_whatsapp_text(rendered_text: str, media_url: Optional[str]) -> str:
    """
    WhatsApp-friendly composition: append media URL to the message text so it is sent
    as part of the message (simple + reliable).
    """
    base = rendered_text or ""
    url = (media_url or "").strip()
    if not url:
        return base
    if url in base:
        return base
    base = base.rstrip()
    return f"{base}\n\n{url}" if base else url


def pick_template_from_pool(pool: Optional[WhatsAppTemplatePool], job_id: Optional[int]) -> Optional[WhatsAppTemplate]:
    if not pool or not pool.is_active:
        return None
    if job_id and pool.job_id and pool.job_id != job_id:
        return None
    templates = list(pool.templates.filter(is_active=True))
    if not templates:
        return None
    weights = [max(1, t.weight or 1) for t in templates]
    return random.choices(templates, weights=weights, k=1)[0]


def prepare_campaign_recipients(
    campaign: WhatsAppCampaign,
    limit: Optional[int] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """
    Create/update WhatsAppCampaignRecipient rows from job leads without sending messages.
    """
    leads_qs = (
        GmapsLead.objects.filter(job_id=campaign.job_id)
        .exclude(phone__isnull=True)
        .exclude(phone__exact="")
        .select_related("job")
        .order_by("-id")
    )
    if limit:
        leads_qs = leads_qs[:limit]

    created_contacts = 0
    created_recipients = 0
    updated_recipients = 0
    skipped_non_whatsapp = 0
    errors: List[Dict[str, Any]] = []

    for lead in leads_qs:
        if lead.phone_type != "whatsapp":
            skipped_non_whatsapp += 1
            continue

        try:
            contact = getattr(lead, "whatsapp_contact", None)
            if not contact:
                contact = WhatsAppContact.create_from_lead(lead)
                created_contacts += 1

            chosen_template = pick_template_from_pool(campaign.template_pool, campaign.job_id)
            text_source = chosen_template.text if chosen_template else (campaign.text_template or "")
            if not text_source.strip():
                errors.append({"lead_id": lead.id, "error": "No template text available (pool empty and fallback empty)."})
                continue

            rendered_text = render_whatsapp_template(text_source, lead)
            media_url = None
            if chosen_template and chosen_template.media_url:
                media_url = chosen_template.media_url
            elif campaign.media_url:
                media_url = campaign.media_url
            rendered_text = compose_whatsapp_text(rendered_text, media_url)

            recipient, created = WhatsAppCampaignRecipient.objects.get_or_create(
                campaign=campaign,
                lead=lead,
                defaults={
                    "whatsapp_contact": contact,
                    "template": chosen_template,
                    "media_url": media_url,
                    "rendered_text": rendered_text,
                    "status": "pending",
                },
            )
            if created:
                created_recipients += 1
                continue

            if overwrite:
                recipient.whatsapp_contact = contact
                recipient.template = chosen_template
                recipient.media_url = media_url
                recipient.rendered_text = rendered_text
                recipient.status = "pending"
                recipient.error = None
                recipient.message_id = None
                recipient.sent_at = None
                recipient.attempts = 0
                recipient.updated_at = timezone.now()
                recipient.save()
                updated_recipients += 1
                continue

            # Keep existing assignment unless missing data
            changed_fields = []
            if not recipient.whatsapp_contact_id and contact:
                recipient.whatsapp_contact = contact
                changed_fields.append("whatsapp_contact")
            if not recipient.rendered_text and rendered_text:
                recipient.rendered_text = rendered_text
                changed_fields.append("rendered_text")
            if recipient.template_id is None and chosen_template is not None:
                recipient.template = chosen_template
                changed_fields.append("template")
            if recipient.media_url is None and media_url is not None:
                recipient.media_url = media_url
                changed_fields.append("media_url")
            if recipient.rendered_text and media_url and media_url not in recipient.rendered_text:
                recipient.rendered_text = compose_whatsapp_text(recipient.rendered_text, media_url)
                changed_fields.append("rendered_text")
            if changed_fields:
                recipient.save(update_fields=changed_fields + ["updated_at"])
                updated_recipients += 1

        except Exception as exc:  # noqa: BLE001
            errors.append({"lead_id": lead.id, "error": str(exc)})

    total = WhatsAppCampaignRecipient.objects.filter(campaign=campaign).count()
    return {
        "campaign_id": campaign.id,
        "job_id": campaign.job_id,
        "total_recipients": total,
        "created_contacts": created_contacts,
        "created_recipients": created_recipients,
        "updated_recipients": updated_recipients,
        "skipped_non_whatsapp": skipped_non_whatsapp,
        "errors": errors,
    }
