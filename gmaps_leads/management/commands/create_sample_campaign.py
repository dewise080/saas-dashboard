from django.core.management.base import BaseCommand, CommandError

from gmaps_leads.sample_campaign import create_sample_campaign


class Command(BaseCommand):
    help = "Generate a sample email campaign with synthetic leads and recipients from provided emails (max 10)."

    def add_arguments(self, parser):
        parser.add_argument("emails", nargs="+", help="Email addresses (1-10)")
        parser.add_argument(
            "--name",
            help="Optional campaign name. Defaults to 'Sample Campaign <timestamp>'.",
            default=None,
        )

    def handle(self, *args, **options):
        emails = options["emails"]
        name = options["name"]
        try:
            campaign, recipients = create_sample_campaign(emails, campaign_name=name)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(f"Created campaign '{campaign.name}' (slug: {campaign.slug})"))
        self.stdout.write(self.style.SUCCESS(f"Recipients: {len(recipients)}"))
        for r in recipients:
            addr = r.email_address.email if r.email_address else "(none)"
            self.stdout.write(f" - #{r.id} -> {addr} (status {r.status})")
