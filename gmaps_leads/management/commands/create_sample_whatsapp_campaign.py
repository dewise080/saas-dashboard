from django.core.management.base import BaseCommand, CommandError

from gmaps_leads.sample_campaign import create_sample_whatsapp_campaign


class Command(BaseCommand):
    help = "Generate a sample WhatsApp campaign with synthetic leads/recipients from provided phone numbers (max 10)."

    def add_arguments(self, parser):
        parser.add_argument("numbers", nargs="+", help="Phone numbers (WhatsApp eligible, digits)")
        parser.add_argument(
            "--name",
            help="Optional campaign name. Defaults to 'Sample WA Campaign <timestamp>'.",
            default=None,
        )
        parser.add_argument(
            "--text",
            help="Optional text template. Defaults to a simple greeting with business name.",
            default=None,
        )

    def handle(self, *args, **options):
        numbers = options["numbers"]
        name = options["name"]
        text = options["text"]
        try:
            campaign, recipients = create_sample_whatsapp_campaign(numbers, campaign_name=name, text_template=text)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(f"Created WA campaign '{campaign.name}' (id: {campaign.id})"))
        self.stdout.write(self.style.SUCCESS(f"Recipients: {len(recipients)}"))
        for r in recipients:
            chat_id = r.whatsapp_contact.chat_id if r.whatsapp_contact else "(none)"
            self.stdout.write(f" - #{r.id} -> {chat_id} (status {r.status})")
