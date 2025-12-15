from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.emailing.models import (
    CampaignRecipient,
    EmailAddress,
    EmailCampaign,
    EmailTemplate,
    Recipient,
)


class Command(BaseCommand):
    help = "Seed sample email data (templates, campaigns, recipients, addresses, campaign recipients). Safe to run multiple times."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding email data..."))

        template, _ = EmailTemplate.objects.get_or_create(
            name="Sample Outreach Template",
            defaults={
                "description": "Example outreach template with placeholders.",
                "subject_template": "Quick intro for {{ recipient_name|default:'there' }}",
                "html_template": """
                    <p>Hi {{ recipient_name|default:'there' }},</p>
                    <p>I noticed {{ company|default:'your business' }} and thought this short demo might help.</p>
                    <ul>
                        <li>Context-aware outreach examples</li>
                        <li>Per-recipient personalization</li>
                        <li>ESP/SMTP provider switching</li>
                    </ul>
                    <p>Would you like me to send a brief walkthrough?</p>
                    <p>Thanks!</p>
                """.strip(),
                "text_template": "",
                "metadata": {"from_email": "noreply@example.com"},
            },
        )

        campaign, _ = EmailCampaign.objects.get_or_create(
            slug="sample-outreach",
            defaults={
                "name": "Sample Outreach Campaign",
                "description": "Demonstrates campaign + recipient + provider structure.",
                "template": template,
                "status": "ready",
                "provider_alias": "",
                "default_context": {"product": "Sample Product"},
                "expected_recipients": 3,
            },
        )

        recipients_seed = [
            {
                "first_name": "Ava",
                "last_name": "Lee",
                "company": "Northwind Bikes",
                "emails": [
                    {"email": "ava.lee@example.com", "label": "work", "is_primary": True},
                    {"email": "ava.personal@example.com", "label": "personal"},
                ],
            },
            {
                "first_name": "Ravi",
                "last_name": "Patel",
                "company": "Summit Legal",
                "emails": [
                    {"email": "ravi.patel@example.com", "label": "work", "is_primary": True},
                ],
            },
            {
                "first_name": "Mia",
                "last_name": "Gonzalez",
                "company": "Blue Harbor Studio",
                "emails": [
                    {"email": "hello@blueharbor.test", "label": "info", "is_primary": True},
                    {"email": "mia@blueharbor.test", "label": "founder"},
                ],
            },
        ]

        created_recipients = 0
        created_addresses = 0
        for rec in recipients_seed:
            recipient, was_created = Recipient.objects.get_or_create(
                first_name=rec["first_name"],
                last_name=rec["last_name"],
                company=rec["company"],
                defaults={"metadata": {"source": "seed"}},
            )
            if was_created:
                created_recipients += 1

            for email_info in rec["emails"]:
                _, addr_created = EmailAddress.objects.get_or_create(
                    recipient=recipient,
                    email=email_info["email"],
                    defaults={
                        "label": email_info.get("label", ""),
                        "is_primary": email_info.get("is_primary", False),
                        "is_verified": True,
                        "metadata": {"source": "seed"},
                    },
                )
                if addr_created:
                    created_addresses += 1

        # Attach campaign recipients using primary addresses when available
        total_campaign_recipients = 0
        for recipient in Recipient.objects.all():
            primary = recipient.email_addresses.filter(is_primary=True).first() or recipient.email_addresses.first()
            if not primary:
                continue
            _, cr_created = CampaignRecipient.objects.get_or_create(
                campaign=campaign,
                email_address=primary,
                defaults={
                    "recipient": recipient,
                    "status": CampaignRecipient.STATUS_READY,
                    "context": {"recipient_name": recipient.full_name, "company": recipient.company},
                },
            )
            if cr_created:
                total_campaign_recipients += 1

        # Add a sample failed record to illustrate error handling
        failed_email = EmailAddress.objects.filter(email__icontains="blueharbor").first()
        if failed_email:
            cr, _ = CampaignRecipient.objects.get_or_create(
                campaign=campaign,
                email_address=failed_email,
                defaults={"recipient": failed_email.recipient, "status": CampaignRecipient.STATUS_FAILED},
            )
            cr.last_error = "Example failure state (no send attempted)."
            cr.save(update_fields=["last_error", "updated_at"])

        campaign.refresh_counters(commit=True)
        campaign.expected_recipients = campaign.recipients.count()
        campaign.save(update_fields=["expected_recipients", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete. Templates: 1, Campaigns: 1, Recipients created: {created_recipients}, "
                f"Email addresses created: {created_addresses}, Campaign recipients added: {total_campaign_recipients}"
            )
        )
