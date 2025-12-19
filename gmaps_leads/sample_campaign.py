import random
import string
from typing import Iterable, List, Optional, Tuple

from django.utils.text import slugify
from django.utils import timezone

from gmaps_leads.models import GmapsLead, ScrapeJob, WhatsAppContact, WhatsAppCampaign, WhatsAppCampaignRecipient
from apps.emailing.models import EmailCampaign, CampaignRecipient, Recipient, EmailAddress


def _random_name(prefix: str = "Sample") -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"{prefix} {suffix}"


def create_sample_campaign(emails: Iterable[str], campaign_name: Optional[str] = None, created_by=None) -> Tuple[EmailCampaign, List[CampaignRecipient]]:
    """
    Create a sample email campaign with synthetic leads and recipients from user-provided emails.

    Args:
        emails: iterable of email strings (min 1, max 10).
        campaign_name: optional name, defaults to "Sample Campaign <timestamp>".
        created_by: optional user; used for provenance on generated leads.

    Returns:
        (campaign, list of CampaignRecipient)
    """
    emails = [e.strip() for e in emails if e and e.strip()]
    if not emails:
        raise ValueError("Provide at least one email.")
    if len(emails) > 10:
        raise ValueError("Maximum 10 emails allowed for sample generation.")

    campaign_name = campaign_name or f"Sample Campaign {timezone.now().strftime('%Y%m%d-%H%M%S')}"
    slug_base = slugify(campaign_name) or "sample-campaign"
    slug = slug_base
    i = 1
    while EmailCampaign.objects.filter(slug=slug).exists():
        slug = f"{slug_base}-{i}"
        i += 1

    campaign = EmailCampaign.objects.create(
        name=campaign_name,
        slug=slug,
        status=EmailCampaign.STATUS_READY if hasattr(EmailCampaign, "STATUS_READY") else "ready",
        default_from_email="no-reply@example.com",
        default_from_name="Sample Sender",
        expected_recipients=len(emails),
    )

    recipients: List[CampaignRecipient] = []

    for idx, email in enumerate(emails, start=1):
        # Create a synthetic lead for traceability
        lead = GmapsLead.objects.create(
            title=_random_name("Sample Lead"),
            category="Sample",
            address=f"123 Sample St #{idx}",
            phone="",
            emails=email,
            job=None,
        )

        # Create recipient and email address
        rec = Recipient.objects.create(first_name="Sample", last_name="Recipient", company=lead.title)
        addr = EmailAddress.objects.create(recipient=rec, email=email, is_primary=True, is_verified=True)

        # Create campaign recipient with placeholder content
        camp_rec = CampaignRecipient.objects.create(
            campaign=campaign,
            recipient=rec,
            email_address=addr,
            status=getattr(CampaignRecipient, "STATUS_READY", "ready"),
            subject=f"Hello from {campaign_name}",
            body_text=f"Hi {rec.full_name or 'there'}, this is a sample outreach for {lead.title}.",
            context={"lead_id": lead.id, "sample": True},
        )
        recipients.append(camp_rec)

    return campaign, recipients


def create_sample_whatsapp_campaign(
    numbers: Iterable[str],
    campaign_name: Optional[str] = None,
    text_template: Optional[str] = None,
    created_by=None,
) -> Tuple[WhatsAppCampaign, List[WhatsAppCampaignRecipient]]:
    """
    Create a sample WhatsApp campaign with synthetic leads and recipients from user-provided phone numbers.

    Args:
        numbers: iterable of phone numbers (digits). Min 1, max 10.
        campaign_name: optional name, defaults to "Sample WA Campaign <timestamp>".
        text_template: optional message template. Defaults to a simple greeting.
        created_by: optional user.

    Returns:
        (campaign, list of WhatsAppCampaignRecipient)
    """
    numbers = [("".join(filter(str.isdigit, n))).strip() for n in numbers if n and "".join(filter(str.isdigit, n)).strip()]
    if not numbers:
        raise ValueError("Provide at least one phone number.")
    if len(numbers) > 10:
        raise ValueError("Maximum 10 numbers allowed for sample generation.")

    campaign_name = campaign_name or f"Sample WA Campaign {timezone.now().strftime('%Y%m%d-%H%M%S')}"
    text_template = text_template or "Hello from {{business_name}}! This is a sample WhatsApp message."

    # Create a minimal scrape job to attach to the campaign
    ext_base = f"sample-wa-{timezone.now().strftime('%Y%m%d%H%M%S')}"
    external_id = ext_base
    i = 1
    while ScrapeJob.objects.filter(external_id=external_id).exists():
        external_id = f"{ext_base}-{i}"
        i += 1
    job = ScrapeJob.objects.create(
        external_id=external_id,
        name=campaign_name,
        keywords=["sample"],
        lang="en",
        zoom=15,
        depth=1,
        max_time=60,
        email=False,
        status="completed",
        created_by=created_by,
    )

    campaign = WhatsAppCampaign.objects.create(
        job=job,
        name=campaign_name,
        text_template=text_template,
        media_url=None,
        throttle_per_minute=20,
        delay_min_ms=1000,
        delay_max_ms=3000,
        status="draft",
        created_by=created_by,
    )

    recipients: List[WhatsAppCampaignRecipient] = []

    for idx, num in enumerate(numbers, start=1):
        # Ensure phone starts with country code for WhatsApp eligibility
        phone = num if num.startswith("90") else f"9{num}" if num.startswith("05") else num
        if not phone.startswith("90"):
            phone = f"90{phone}"
        lead = GmapsLead.objects.create(
            job=job,
            title=_random_name("Sample Lead"),
            category="Sample",
            address=f"Sample Address #{idx}",
            phone=phone,
            emails="",
        )

        wa_contact = WhatsAppContact.create_from_lead(lead)
        rendered_text = text_template.replace("{{business_name}}", lead.title)

        recip = WhatsAppCampaignRecipient.objects.create(
            campaign=campaign,
            lead=lead,
            whatsapp_contact=wa_contact,
            template=None,
            media_url=None,
            rendered_text=rendered_text,
            status="pending",
        )
        recipients.append(recip)

    return campaign, recipients
