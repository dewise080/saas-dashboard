"""
Management command to scrape websites from leads.

Extracts:
- Email addresses (from header, footer, contact sections)
- Structured content (headings, paragraphs)
- Meta information (title, description)
- Social media links
- Phone numbers

Usage:
    # Dry run - show what would be scraped
    python manage.py scrape_lead_websites --dry-run
    
    # Scrape all leads with websites
    python manage.py scrape_lead_websites
    
    # Scrape specific job's leads
    python manage.py scrape_lead_websites --job-id 1
    
    # Scrape specific lead
    python manage.py scrape_lead_websites --lead-id 123
    
    # Force re-scrape already scraped websites
    python manage.py scrape_lead_websites --force
    
    # Limit number of websites to scrape
    python manage.py scrape_lead_websites --limit 50
    
    # Show statistics only
    python manage.py scrape_lead_websites --stats
"""
import time
import logging
from django.core.management.base import BaseCommand
from django.db.models import Q

from gmaps_leads.models import GmapsLead, LeadWebsite
from gmaps_leads.website_scraper import scrape_lead_website

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Scrape websites from leads to extract emails and structured content'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be scraped without making changes',
        )
        parser.add_argument(
            '--job-id',
            type=int,
            help='Only scrape leads from this job',
        )
        parser.add_argument(
            '--lead-id',
            type=int,
            help='Scrape a specific lead by ID',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-scrape websites that have already been scraped',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Maximum number of websites to scrape',
        )
        parser.add_argument(
            '--stats',
            action='store_true',
            help='Show statistics only',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.0,
            help='Delay between requests in seconds (default: 1.0)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        job_id = options['job_id']
        lead_id = options['lead_id']
        force = options['force']
        limit = options['limit']
        stats_only = options['stats']
        delay = options['delay']
        
        # Build queryset
        leads = GmapsLead.objects.exclude(
            Q(website__isnull=True) | Q(website='')
        )
        
        if job_id:
            leads = leads.filter(job_id=job_id)
        
        if lead_id:
            leads = leads.filter(pk=lead_id)
        
        # Show statistics
        total_with_website = leads.count()
        already_scraped = LeadWebsite.objects.filter(lead__in=leads).count()
        pending = total_with_website - already_scraped if not force else total_with_website
        
        with_emails = LeadWebsite.objects.filter(lead__in=leads, emails_count__gt=0).count()
        total_emails = sum(
            LeadWebsite.objects.filter(lead__in=leads).values_list('emails_count', flat=True)
        )
        
        self.stdout.write('')
        self.stdout.write('=' * 60)
        self.stdout.write('WEBSITE SCRAPING STATISTICS')
        self.stdout.write('=' * 60)
        self.stdout.write(f'  Leads with websites:      {total_with_website:>8}')
        self.stdout.write(f'  Already scraped:          {already_scraped:>8}')
        self.stdout.write(f'  Pending to scrape:        {pending:>8}')
        self.stdout.write('')
        self.stdout.write(f'  Websites with emails:     {with_emails:>8}')
        self.stdout.write(f'  Total emails found:       {total_emails:>8}')
        self.stdout.write('=' * 60)
        
        if stats_only:
            # Show breakdown by status
            self.stdout.write('')
            self.stdout.write('STATUS BREAKDOWN:')
            for status in ['completed', 'failed', 'no_content', 'pending']:
                count = LeadWebsite.objects.filter(lead__in=leads, status=status).count()
                self.stdout.write(f'  {status:<15} {count:>8}')
            return
        
        # Filter to only pending if not force
        if not force:
            scraped_lead_ids = LeadWebsite.objects.filter(lead__in=leads).values_list('lead_id', flat=True)
            leads = leads.exclude(pk__in=scraped_lead_ids)
        
        # Apply limit
        if limit:
            leads = leads[:limit]
        
        to_scrape = leads.count()
        
        if to_scrape == 0:
            self.stdout.write(self.style.SUCCESS('No websites to scrape.'))
            return
        
        self.stdout.write('')
        self.stdout.write(f'Websites to scrape: {to_scrape}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN - Would scrape:'))
            for lead in leads[:20]:
                self.stdout.write(f'  {lead.title[:40]:<40} | {lead.website[:50]}')
            if to_scrape > 20:
                self.stdout.write(f'  ... and {to_scrape - 20} more')
            return
        
        # Scrape websites
        self.stdout.write('')
        self.stdout.write('Scraping websites...')
        
        scraped = 0
        emails_found = 0
        errors = 0
        
        for i, lead in enumerate(leads, 1):
            try:
                self.stdout.write(f'  [{i}/{to_scrape}] {lead.title[:40]:<40}', ending='')
                
                website_data = scrape_lead_website(lead, force=force)
                
                if website_data:
                    if website_data.status == 'completed':
                        scraped += 1
                        if website_data.emails_count > 0:
                            emails_found += website_data.emails_count
                            self.stdout.write(self.style.SUCCESS(f' ✓ {website_data.emails_count} emails'))
                        else:
                            self.stdout.write(self.style.SUCCESS(' ✓ no emails'))
                    elif website_data.status == 'no_content':
                        scraped += 1
                        self.stdout.write(self.style.WARNING(' ⚠ no content'))
                    else:
                        errors += 1
                        self.stdout.write(self.style.ERROR(f' ✗ {website_data.error_message[:30]}'))
                else:
                    self.stdout.write(self.style.WARNING(' ⚠ no website'))
                
                # Delay between requests
                if delay and i < to_scrape:
                    time.sleep(delay)
                    
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING('\n\nInterrupted by user'))
                break
            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f' ✗ Error: {str(e)[:30]}'))
                logger.exception(f'Error scraping {lead.website}')
        
        # Summary
        self.stdout.write('')
        self.stdout.write('=' * 60)
        self.stdout.write('SCRAPING SUMMARY')
        self.stdout.write('=' * 60)
        self.stdout.write(self.style.SUCCESS(f'  Scraped:         {scraped}'))
        self.stdout.write(f'  Emails found:    {emails_found}')
        if errors:
            self.stdout.write(self.style.ERROR(f'  Errors:          {errors}'))
        self.stdout.write('')
        self.stdout.write(f'  Total websites in DB: {LeadWebsite.objects.count()}')
        self.stdout.write(f'  Total emails in DB:   {sum(LeadWebsite.objects.values_list("emails_count", flat=True))}')
        self.stdout.write('=' * 60)
