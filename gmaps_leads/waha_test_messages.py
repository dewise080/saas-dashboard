import random
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.shortcuts import get_object_or_404

from .models import GmapsLead, WhatsAppCampaign, WhatsAppTemplate, WhatsAppTemplatePool
from .waha_client import WahaClient
from .whatsapp_campaigns import compose_whatsapp_text


def normalize_recipient(chat_id: Optional[str], jid: Optional[str], phone: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Return (chatId, digits_phone_or_none).
    Accepts chatId, WhatsApp JID, or a phone number.
    """
    if chat_id:
        return chat_id.strip(), None
    if jid:
        normalized = jid.strip()
        if normalized.endswith("@s.whatsapp.net"):
            local = normalized.split("@", 1)[0]
            digits = "".join(c for c in local if c.isdigit())
            if digits:
                return f"{digits}@c.us", digits
        raise ValueError("jid must look like 905XXXXXXXX@s.whatsapp.net")
    if phone:
        digits = "".join(c for c in str(phone) if c.isdigit())
        if not digits:
            raise ValueError("phone must contain digits")
        return f"{digits}@c.us", digits
    raise ValueError("Provide chat_id, jid, or phone")


def pick_weighted_template(pool: WhatsAppTemplatePool) -> Optional[WhatsAppTemplate]:
    templates = list(pool.templates.filter(is_active=True))
    if not templates:
        return None
    weights = [max(1, t.weight or 1) for t in templates]
    return random.choices(templates, weights=weights, k=1)[0]


def resolve_content_source(
    *,
    template_id: Optional[int],
    pool_id: Optional[int],
    campaign_id: Optional[int],
    text: Optional[str],
) -> tuple[Optional[WhatsAppCampaign], Optional[WhatsAppTemplate], str, Optional[str]]:
    campaign = get_object_or_404(WhatsAppCampaign, pk=campaign_id) if campaign_id else None

    chosen_template = None
    if template_id:
        chosen_template = get_object_or_404(WhatsAppTemplate.objects.select_related("pool"), pk=template_id)
    elif pool_id:
        pool = get_object_or_404(WhatsAppTemplatePool, pk=pool_id)
        chosen_template = pick_weighted_template(pool)
    elif campaign and campaign.template_pool_id:
        chosen_template = pick_weighted_template(campaign.template_pool)

    if chosen_template:
        text_source = chosen_template.text
        media_url = chosen_template.media_url or (campaign.media_url if campaign else None)
    else:
        # When not using templates, fall back to explicit text, then campaign fallback.
        text_source = text if text is not None else (campaign.text_template if campaign else "")
        media_url = campaign.media_url if campaign else None

    return campaign, chosen_template, text_source or "", media_url


def resolve_render_context(
    *,
    lead_id: Optional[int],
    business_name: Optional[str],
    category: Optional[str],
    website: Optional[str],
) -> tuple[Optional[int], str, str, str]:
    if lead_id:
        lead = get_object_or_404(GmapsLead, pk=lead_id)
        return lead.id, lead.title or "", lead.category or "", lead.website or ""
    return None, business_name or "", category or "", website or ""


def render_text(text_source: str, business_name: str, category: str, website: str) -> str:
    source = text_source or ""
    # If the caller didn't provide any context, keep placeholders intact so you can
    # visually inspect template formatting.
    if not (business_name or category or website):
        return source
    return (
        source
        .replace("{{business_name}}", business_name or "")
        .replace("{{category}}", category or "")
        .replace("{{website}}", website or "")
    )


def preview_waha_payload(
    *,
    chat_id: str,
    rendered_text: str,
    reply_to: Optional[str],
    link_preview: Optional[bool],
    link_preview_high_quality: Optional[bool],
) -> Dict[str, Any]:
    return {
        "chatId": chat_id,
        "text": rendered_text,
        "session": getattr(settings, "WAHA_SESSION", None),
        "reply_to": reply_to or None,
        "linkPreview": link_preview,
        "linkPreviewHighQuality": link_preview_high_quality,
    }


def run_test_message(validated_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Takes validated data (from WahaTestMessageSerializer) and returns preview or send result.
    """
    chat_id, phone_digits = normalize_recipient(
        validated_data.get("chat_id"),
        validated_data.get("jid"),
        validated_data.get("phone"),
    )

    campaign, template, text_source, media_url = resolve_content_source(
        template_id=validated_data.get("template_id"),
        pool_id=validated_data.get("pool_id"),
        campaign_id=validated_data.get("campaign_id"),
        text=validated_data.get("text"),
    )

    lead_id, business_name, category, website = resolve_render_context(
        lead_id=validated_data.get("lead_id"),
        business_name=validated_data.get("business_name"),
        category=validated_data.get("category"),
        website=validated_data.get("website"),
    )

    rendered = render_text(text_source, business_name, category, website)
    if not rendered.strip():
        raise ValueError("Rendered text is empty. Provide text or an active template.")
    rendered = compose_whatsapp_text(rendered, media_url)

    reply_to = (validated_data.get("reply_to") or "").strip() or None
    link_preview = validated_data.get("link_preview")
    link_preview_high_quality = validated_data.get("link_preview_high_quality")

    dry_run = bool(validated_data.get("dry_run", True))
    if dry_run:
        return {
            "dry_run": True,
            "chat_id": chat_id,
            "phone": phone_digits,
            "lead_id": lead_id,
            "campaign_id": campaign.id if campaign else None,
            "template_id": template.id if template else None,
            "media_url": media_url,
            "rendered_text": rendered,
            "waha_payload_preview": preview_waha_payload(
                chat_id=chat_id,
                rendered_text=rendered,
                reply_to=reply_to,
                link_preview=link_preview,
                link_preview_high_quality=link_preview_high_quality,
            ),
        }

    client = WahaClient()
    result = client.send_text(
        chat_id=chat_id,
        text=rendered,
        phone=phone_digits,
        reply_to=reply_to,
        link_preview=link_preview,
        link_preview_high_quality=link_preview_high_quality,
    )
    return {
        "dry_run": False,
        "chat_id": chat_id,
        "phone": phone_digits,
        "lead_id": lead_id,
        "campaign_id": campaign.id if campaign else None,
        "template_id": template.id if template else None,
        "media_url": media_url,
        "rendered_text": rendered,
        "waha": result,
    }
