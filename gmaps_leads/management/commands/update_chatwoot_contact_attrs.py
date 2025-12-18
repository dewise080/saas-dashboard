import time
from typing import Any, Dict

from django.core.management.base import BaseCommand

from gmaps_leads.models import ChatwootContactSync
from apps.emailing.chatwoot import ChatwootClient


class Command(BaseCommand):
    help = "Update Chatwoot contact custom attributes for synced leads."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200, help="Max contacts to update (default 200)")
        parser.add_argument("--offset", type=int, default=0, help="Offset into synced ledger rows")
        parser.add_argument("--sleep", type=float, default=0.2, help="Delay between API calls to avoid rate limits")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview only; do not PATCH Chatwoot",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        offset = options["offset"]
        sleep_s = options["sleep"]
        dry_run = options["dry_run"]

        client = ChatwootClient()
        if not client.configured:
            self.stderr.write(self.style.ERROR("Chatwoot is not configured (check CHATWOOT_* env vars)."))
            return

        qs = ChatwootContactSync.objects.filter(status="synced").order_by("id")
        total = qs.count()
        rows = qs[offset : offset + limit]

        self.stdout.write(f"Synced ledger rows: {total}")
        self.stdout.write(f"Processing rows {offset}..{offset + len(rows) - 1} (limit={limit})")
        if not rows:
            self.stdout.write(self.style.WARNING("No rows to process."))
            return

        updated = 0
        errors = 0
        samples: list[Dict[str, Any]] = []

        for ledger in rows:
            lead = ledger.lead
            contact_id = ledger.chatwoot_contact_id
            if not contact_id:
                continue

            # Build attributes similarly to sync payload
            wa_attrs = {}
            wa = getattr(lead, "whatsapp_contact", None)
            if wa:
                if getattr(wa, "chat_id", None):
                    wa_attrs["whatsapp_chat_id"] = wa.chat_id
                    wa_attrs["waha_whatsapp_chat_id"] = wa.chat_id
                if getattr(wa, "jid", None):
                    wa_attrs["whatsapp_jid"] = wa.jid
                    wa_attrs["waha_whatsapp_jid"] = wa.jid
                if getattr(wa, "lid", None):
                    wa_attrs["whatsapp_lid"] = wa.lid
                    wa_attrs["waha_whatsapp_lid"] = wa.lid

            attrs = {
                "gmaps_lead_id": lead.id,
                "category": lead.category,
                "website": lead.website,
                "scrape_job": lead.job_id,
                **wa_attrs,
            }

            # Collect emails and social links if present
            emails = []
            try:
                import json

                if lead.emails:
                    parsed = json.loads(lead.emails) if isinstance(lead.emails, str) else lead.emails
                    if isinstance(parsed, list):
                        emails.extend([e for e in parsed if e])
                    elif isinstance(parsed, str):
                        emails.append(parsed)
            except Exception:
                pass
            try:
                if hasattr(lead, "website_data") and lead.website_data:
                    if getattr(lead.website_data, "emails", None):
                        emails.extend([e for e in lead.website_data.emails if e])
            except Exception:
                pass
            if emails:
                # dedupe
                seen = set()
                uniq = []
                for e in emails:
                    if e not in seen:
                        uniq.append(e)
                        seen.add(e)
                attrs["emails"] = uniq

            try:
                social_links = getattr(getattr(lead, "website_data", None), "social_links", None)
                if social_links:
                    attrs["social_links"] = social_links
            except Exception:
                pass

            if len(samples) < 3:
                samples.append({"contact_id": contact_id, "attrs": attrs})

            if dry_run:
                continue

            try:
                client._request(
                    "PATCH",
                    f"/accounts/{client.account_id}/contacts/{contact_id}",
                    json={"custom_attributes": attrs},
                )
                updated += 1
            except Exception as exc:
                errors += 1
                self.stderr.write(self.style.ERROR(f"Contact {contact_id} failed: {exc}"))
            time.sleep(sleep_s)

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run - no updates sent. Samples:"))
            for s in samples:
                self.stdout.write(str(s))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated: {updated}, Errors: {errors}"))
