"""
Management command to extract WhatsApp contacts from leads.

Usage:
    # Dry run - show what would be extracted
    python manage.py extract_whatsapp_contacts --dry-run
    
    # Extract all WhatsApp-eligible contacts
    python manage.py extract_whatsapp_contacts
    
    # Extract from specific job
    python manage.py extract_whatsapp_contacts --job-id 1
    
    # Show statistics only
    python manage.py extract_whatsapp_contacts --stats
"""
import logging
from django.core.management.base import BaseCommand
from django.db import IntegrityError

from gmaps_leads.models import GmapsLead, WhatsAppContact, ScrapeJob

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Extract WhatsApp contacts from leads with Turkish mobile numbers (905XX)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be extracted without saving',
        )
        parser.add_argument(
            '--job-id',
            type=int,
            help='Extract from a specific job only',
        )
        parser.add_argument(
            '--stats',
            action='store_true',
            help='Show phone number statistics only',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-extract even if WhatsApp contact already exists',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        job_id = options['job_id']
        stats_only = options['stats']
        force = options['force']
        
        # Get leads queryset
        leads = GmapsLead.objects.all()
        if job_id:
            leads = leads.filter(job_id=job_id)
        
        total_leads = leads.count()
        
        # Classify all leads by phone type
        whatsapp_leads = []
        local_leads = []
        other_leads = []
        no_phone_leads = []
        
        for lead in leads:
            phone_type = lead.phone_type
            if phone_type == 'whatsapp':
                whatsapp_leads.append(lead)
            elif phone_type == 'local':
                local_leads.append(lead)
            elif phone_type == 'other':
                other_leads.append(lead)
            else:
                no_phone_leads.append(lead)
        
        # Print statistics
        self.stdout.write('')
        self.stdout.write('=' * 60)
        self.stdout.write('PHONE NUMBER STATISTICS')
        self.stdout.write('=' * 60)
        self.stdout.write(f'  Total leads:              {total_leads:>8}')
        self.stdout.write(f'  WhatsApp (905XX):         {len(whatsapp_leads):>8}  ({len(whatsapp_leads)/total_leads*100:.1f}%)' if total_leads else f'  WhatsApp (905XX):         {len(whatsapp_leads):>8}')
        self.stdout.write(f'  Local landlines (902XX):  {len(local_leads):>8}  ({len(local_leads)/total_leads*100:.1f}%)' if total_leads else f'  Local landlines (902XX):  {len(local_leads):>8}')
        self.stdout.write(f'  Other numbers:            {len(other_leads):>8}  ({len(other_leads)/total_leads*100:.1f}%)' if total_leads else f'  Other numbers:            {len(other_leads):>8}')
        self.stdout.write(f'  No phone:                 {len(no_phone_leads):>8}  ({len(no_phone_leads)/total_leads*100:.1f}%)' if total_leads else f'  No phone:                 {len(no_phone_leads):>8}')
        self.stdout.write('=' * 60)
        
        # Website statistics
        with_website = leads.exclude(website__isnull=True).exclude(website='').count()
        without_website = total_leads - with_website
        self.stdout.write('')
        self.stdout.write('WEBSITE STATISTICS')
        self.stdout.write('=' * 60)
        self.stdout.write(f'  With website:             {with_website:>8}  ({with_website/total_leads*100:.1f}%)' if total_leads else f'  With website:             {with_website:>8}')
        self.stdout.write(f'  Without website:          {without_website:>8}  ({without_website/total_leads*100:.1f}%)' if total_leads else f'  Without website:          {without_website:>8}')
        self.stdout.write('=' * 60)
        
        if stats_only:
            return
        
        # Check existing WhatsApp contacts
        existing_contacts = WhatsAppContact.objects.count()
        existing_lead_ids = set(WhatsAppContact.objects.values_list('lead_id', flat=True))
        
        self.stdout.write('')
        self.stdout.write(f'Existing WhatsApp contacts: {existing_contacts}')
        
        # Filter leads that need processing
        if force:
            leads_to_process = whatsapp_leads
        else:
            leads_to_process = [l for l in whatsapp_leads if l.id not in existing_lead_ids]
        
        self.stdout.write(f'Leads to process:           {len(leads_to_process)}')
        
        if not leads_to_process:
            self.stdout.write(self.style.SUCCESS('No new WhatsApp contacts to extract.'))
            return
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN - Would extract the following:'))
            for lead in leads_to_process[:20]:  # Show first 20
                phone = lead.cleaned_phone
                self.stdout.write(f'  {lead.title[:40]:<40} | {lead.phone:<15} → {phone}@c.us')
            if len(leads_to_process) > 20:
                self.stdout.write(f'  ... and {len(leads_to_process) - 20} more')
            return
        
        # Extract contacts
        self.stdout.write('')
        self.stdout.write('Extracting WhatsApp contacts...')
        
        created = 0
        updated = 0
        errors = 0
        
        for lead in leads_to_process:
            try:
                if force and lead.id in existing_lead_ids:
                    # Update existing
                    contact = WhatsAppContact.objects.get(lead=lead)
                    phone = lead.cleaned_phone
                    contact.phone_number = phone
                    contact.chat_id = f"{phone}@c.us"
                    contact.jid = f"{phone}@s.whatsapp.net"
                    contact.business_name = lead.title
                    contact.category = lead.category
                    contact.save()
                    updated += 1
                else:
                    # Create new
                    WhatsAppContact.create_from_lead(lead)
                    created += 1
            except IntegrityError:
                # Already exists
                pass
            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f'  Error for {lead.title}: {e}'))
        
        # Summary
        self.stdout.write('')
        self.stdout.write('=' * 60)
        self.stdout.write('EXTRACTION SUMMARY')
        self.stdout.write('=' * 60)
        self.stdout.write(self.style.SUCCESS(f'  Created:  {created}'))
        if updated:
            self.stdout.write(f'  Updated:  {updated}')
        if errors:
            self.stdout.write(self.style.ERROR(f'  Errors:   {errors}'))
        self.stdout.write(f'  Total WhatsApp contacts: {WhatsAppContact.objects.count()}')
        self.stdout.write('=' * 60)
