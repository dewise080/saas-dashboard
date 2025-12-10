"""
Management command to sync all jobs from the scraper API.

This will:
1. Fetch all jobs from GET /api/v1/jobs
2. Create ScrapeJob records for any new jobs not in our DB
3. Download CSVs for completed jobs
4. Parse and import leads

Usage:
    # Dry run - just show what would be imported
    python manage.py sync_scraper_jobs --dry-run
    
    # Sync all jobs
    python manage.py sync_scraper_jobs
    
    # Sync and import leads
    python manage.py sync_scraper_jobs --import-leads
"""
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from dateutil import parser as date_parser

from gmaps_leads.models import ScrapeJob, GmapsLead
from gmaps_leads.services import (
    GmapsScraperService, import_job_results
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Sync all jobs from the Google Maps Scraper API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be synced without making changes',
        )
        parser.add_argument(
            '--import-leads',
            action='store_true',
            help='Also import leads for completed jobs',
        )
        parser.add_argument(
            '--force-reimport',
            action='store_true',
            help='Re-import leads even if already imported',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        import_leads = options['import_leads']
        force_reimport = options['force_reimport']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        service = GmapsScraperService()
        
        # Fetch all jobs from API
        self.stdout.write('Fetching all jobs from scraper API...')
        api_jobs = service.get_all_jobs()
        
        if not api_jobs:
            self.stdout.write(self.style.WARNING('No jobs found in scraper API'))
            return
        
        self.stdout.write(f'Found {len(api_jobs)} jobs in scraper API')
        self.stdout.write('')
        
        # Get existing job IDs from our DB
        existing_ids = set(ScrapeJob.objects.values_list('external_id', flat=True))
        
        # Stats
        new_jobs = 0
        updated_jobs = 0
        imported_leads = 0
        
        for api_job in api_jobs:
            # API returns capitalized field names: ID, Name, Status, Data, Date
            job_id = api_job.get('ID') or api_job.get('id')
            job_name = api_job.get('Name') or api_job.get('name', 'Unnamed')
            job_status = api_job.get('Status') or api_job.get('status', 'unknown')
            job_date = api_job.get('Date') or api_job.get('date')
            job_data = api_job.get('Data') or api_job.get('data', {})
            
            # Skip jobs without ID
            if not job_id:
                self.stdout.write(self.style.WARNING(f'  [SKIP] Job without ID: {job_name}'))
                continue
            
            job_id_short = job_id[:8] if len(job_id) > 8 else job_id
            self.stdout.write(f'  [{job_status.upper():10}] {job_name} ({job_id_short}...)')
            
            if job_id in existing_ids:
                # Update existing job
                if not dry_run:
                    job = ScrapeJob.objects.get(external_id=job_id)
                    old_status = job.status
                    
                    # Map API status to our status
                    status_map = {
                        'pending': 'pending',
                        'running': 'running',
                        'completed': 'completed',
                        'failed': 'failed',
                        'done': 'completed',
                        'ok': 'completed',  # API uses 'ok' for completed jobs
                    }
                    new_status = status_map.get(job_status.lower(), job_status.lower())
                    
                    if old_status != new_status:
                        job.status = new_status
                        if new_status == 'completed':
                            job.completed_at = timezone.now()
                        job.save()
                        self.stdout.write(f'      → Status updated: {old_status} → {new_status}')
                        updated_jobs += 1
                    
                    # Import leads if requested
                    if import_leads and new_status == 'completed':
                        if job.leads_count == 0 or force_reimport:
                            if force_reimport and job.leads_count > 0:
                                self.stdout.write(f'      → Clearing {job.leads_count} existing leads...')
                                GmapsLead.objects.filter(job=job).delete()
                                job.leads_count = 0
                                job.save()
                            
                            try:
                                count = import_job_results(job)
                                imported_leads += count
                                self.stdout.write(self.style.SUCCESS(f'      → Imported {count} leads'))
                            except Exception as e:
                                self.stdout.write(self.style.ERROR(f'      → Import failed: {e}'))
                        else:
                            self.stdout.write(f'      → Already has {job.leads_count} leads (use --force-reimport to re-import)')
            else:
                # Create new job
                self.stdout.write(self.style.SUCCESS(f'      → NEW JOB'))
                new_jobs += 1
                
                if not dry_run:
                    # Parse date
                    created_at = None
                    if job_date:
                        try:
                            created_at = date_parser.parse(job_date)
                        except:
                            pass
                    
                    # Map API status
                    status_map = {
                        'pending': 'pending',
                        'running': 'running', 
                        'completed': 'completed',
                        'failed': 'failed',
                        'done': 'completed',
                        'ok': 'completed',  # API uses 'ok' for completed jobs
                    }
                    status = status_map.get(job_status.lower(), 'pending')
                    
                    # Create the job
                    job = ScrapeJob.objects.create(
                        external_id=job_id,
                        name=job_name,
                        keywords=job_data.get('keywords', []),
                        lang=job_data.get('lang', 'en'),
                        zoom=job_data.get('zoom', 15),
                        lat=job_data.get('lat'),
                        lon=job_data.get('lon'),
                        fast_mode=job_data.get('fast_mode', False),
                        radius=job_data.get('radius'),
                        depth=job_data.get('depth', 1),
                        email=job_data.get('email', False),
                        max_time=job_data.get('max_time', 3600),
                        proxies=job_data.get('proxies'),
                        status=status,
                        completed_at=timezone.now() if status == 'completed' else None,
                    )
                    
                    # Override created_at if we have it
                    if created_at:
                        ScrapeJob.objects.filter(pk=job.pk).update(created_at=created_at)
                    
                    # Import leads if requested and completed
                    if import_leads and status == 'completed':
                        try:
                            count = import_job_results(job)
                            imported_leads += count
                            self.stdout.write(self.style.SUCCESS(f'      → Imported {count} leads'))
                        except Exception as e:
                            self.stdout.write(self.style.ERROR(f'      → Import failed: {e}'))
        
        # Summary
        self.stdout.write('')
        self.stdout.write('=' * 50)
        self.stdout.write('SYNC SUMMARY')
        self.stdout.write('=' * 50)
        self.stdout.write(f'  Jobs in API:     {len(api_jobs)}')
        self.stdout.write(f'  New jobs:        {new_jobs}')
        self.stdout.write(f'  Updated jobs:    {updated_jobs}')
        if import_leads:
            self.stdout.write(f'  Leads imported:  {imported_leads}')
        
        if dry_run:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('DRY RUN - No changes were made'))
            self.stdout.write('Run without --dry-run to apply changes')
        
        # Final DB stats
        self.stdout.write('')
        self.stdout.write(f'Total jobs in DB:  {ScrapeJob.objects.count()}')
        self.stdout.write(f'Total leads in DB: {GmapsLead.objects.count()}')
