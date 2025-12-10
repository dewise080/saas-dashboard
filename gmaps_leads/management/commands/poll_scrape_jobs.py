"""
Management command to poll for completed scrape jobs and import results.

Usage:
    # Run once
    python manage.py poll_scrape_jobs
    
    # Dry run - validate CSV without importing
    python manage.py poll_scrape_jobs --dry-run
    
    # Run continuously (every 5 minutes)
    python manage.py poll_scrape_jobs --daemon
    
    # With cron (every 5 minutes):
    */5 * * * * cd /path/to/project && python manage.py poll_scrape_jobs
"""
import csv
import time
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from gmaps_leads.models import ScrapeJob, GmapsLead
from gmaps_leads.services import (
    refresh_job_status, import_job_results, GmapsScraperService,
    _parse_json_field, CSV_DOWNLOAD_DIR
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Poll for completed scrape jobs and import results'

    def add_arguments(self, parser):
        parser.add_argument(
            '--daemon',
            action='store_true',
            help='Run continuously, polling every 5 minutes',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate CSV data without importing (checks field compatibility)',
        )
        parser.add_argument(
            '--job-id',
            type=int,
            help='Process a specific job by Django ID',
        )
        parser.add_argument(
            '--external-id',
            type=str,
            help='Process a specific job by external API ID (UUID)',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=300,  # 5 minutes
            help='Polling interval in seconds (default: 300)',
        )
        parser.add_argument(
            '--min-age',
            type=int,
            default=600,  # 10 minutes - safe window for cron
            help='Minimum job age in seconds before checking (default: 600 = 10 minutes)',
        )

    def handle(self, *args, **options):
        daemon_mode = options['daemon']
        dry_run = options['dry_run']
        job_id = options['job_id']
        external_id = options['external_id']
        interval = options['interval']
        min_age_seconds = options['min_age']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No data will be imported'))
        
        # Process specific job by external ID (UUID)
        if external_id:
            try:
                job = ScrapeJob.objects.get(external_id=external_id)
                self._process_job(job, dry_run=dry_run)
            except ScrapeJob.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Job with external_id {external_id} not found'))
            return
        
        # Process specific job by Django ID
        if job_id:
            try:
                job = ScrapeJob.objects.get(pk=job_id)
                self._process_job(job, dry_run=dry_run)
            except ScrapeJob.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Job {job_id} not found'))
            return
        
        if daemon_mode:
            self.stdout.write(f'Starting daemon mode, polling every {interval} seconds...')
            while True:
                self._poll_jobs(min_age_seconds, dry_run=dry_run)
                time.sleep(interval)
        else:
            self._poll_jobs(min_age_seconds, dry_run=dry_run)
    
    def _poll_jobs(self, min_age_seconds, dry_run=False):
        """Check pending jobs and import completed ones."""
        min_age = timezone.now() - timedelta(seconds=min_age_seconds)
        
        # Find jobs that need checking
        pending_jobs = ScrapeJob.objects.filter(
            status__in=['pending', 'running'],
            created_at__lte=min_age
        )
        
        count = pending_jobs.count()
        if count == 0:
            self.stdout.write('No pending jobs to check.')
            return
        
        self.stdout.write(f'Checking {count} pending job(s)...')
        
        for job in pending_jobs:
            self._process_job(job, dry_run=dry_run)
    
    def _process_job(self, job, dry_run=False):
        """Process a single job: refresh status and import if ready."""
        self.stdout.write(f'\n  Checking job: {job.name} ({job.external_id})')
        
        try:
            # Refresh status from API
            job = refresh_job_status(job)
            self.stdout.write(f'    Status: {job.status}')
            
            # If completed and no leads imported yet, import them
            if job.status == 'completed' and job.leads_count == 0:
                if dry_run:
                    self._dry_run_import(job)
                else:
                    self.stdout.write(f'    Importing results...')
                    count = import_job_results(job)
                    self.stdout.write(
                        self.style.SUCCESS(f'    Imported {count} leads!')
                    )
            elif job.status == 'failed':
                self.stdout.write(
                    self.style.ERROR(f'    Job failed: {job.error_message}')
                )
            elif job.status in ['pending', 'running']:
                # Calculate time since creation
                age = timezone.now() - job.created_at
                self.stdout.write(f'    Still processing (age: {age})')
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'    Error: {str(e)}')
            )
            logger.exception(f'Error processing job {job.external_id}')
    
    def _dry_run_import(self, job):
        """Validate CSV data without importing."""
        self.stdout.write(self.style.WARNING(f'    [DRY RUN] Validating CSV...'))
        
        service = GmapsScraperService()
        
        # Check if ready
        is_ready, status = service.is_job_ready(job.external_id)
        if not is_ready:
            self.stdout.write(self.style.ERROR(f'    Job not ready: {status}'))
            return
        
        # Download CSV
        csv_path = service.download_csv_to_file(job.external_id)
        if not csv_path:
            self.stdout.write(self.style.ERROR(f'    Failed to download CSV'))
            return
        
        self.stdout.write(f'    Downloaded CSV to: {csv_path}')
        
        # Validate each row
        errors = []
        warnings = []
        valid_rows = 0
        total_rows = 0
        
        # Field length limits from model
        field_limits = {
            'title': 500,
            'link': 2000,
            'category': 255,
            'phone': 50,
            'website': 2000,
            'plus_code': 100,
            'timezone': 100,
            'reviews_link': 2000,
            'thumbnail': 2000,
            'status': 100,
            'price_range': 50,
            'cid': 100,
            'data_id': 100,
            'input_id': 255,
        }
        
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                # Check CSV headers
                csv_fields = reader.fieldnames or []
                self.stdout.write(f'    CSV columns ({len(csv_fields)}): {", ".join(csv_fields[:10])}...')
                
                for row_num, row in enumerate(reader, start=2):
                    total_rows += 1
                    row_errors = []
                    row_warnings = []
                    
                    # Validate required field
                    if not row.get('title'):
                        row_errors.append('Missing required field: title')
                    
                    # Validate field lengths
                    for field, max_len in field_limits.items():
                        value = row.get(field, '')
                        if value and len(value) > max_len:
                            row_warnings.append(f'{field} too long ({len(value)} > {max_len}), will be truncated')
                    
                    # Validate numeric fields
                    for field in ['review_count', 'latitude', 'longitude', 'review_rating']:
                        value = row.get(field, '')
                        if value:
                            try:
                                if field == 'review_count':
                                    int(value)
                                else:
                                    float(value)
                            except ValueError:
                                row_errors.append(f'{field} is not a valid number: {value[:20]}')
                    
                    # Validate JSON fields
                    json_fields = ['open_hours', 'popular_times', 'reviews_per_rating', 
                                   'user_reviews', 'user_reviews_extended', 'images',
                                   'complete_address', 'about', 'reservations', 
                                   'order_online', 'menu', 'owner']
                    for field in json_fields:
                        value = row.get(field, '')
                        if value and value not in ('{}', '[]', 'null', ''):
                            try:
                                import json
                                json.loads(value)
                            except:
                                row_warnings.append(f'{field} has invalid JSON')
                    
                    if row_errors:
                        errors.append(f'Row {row_num}: {"; ".join(row_errors)}')
                    else:
                        valid_rows += 1
                    
                    if row_warnings:
                        warnings.extend([f'Row {row_num}: {w}' for w in row_warnings])
            
            # Print summary
            self.stdout.write('')
            self.stdout.write(f'    ╔══════════════════════════════════════╗')
            self.stdout.write(f'    ║        DRY RUN VALIDATION REPORT     ║')
            self.stdout.write(f'    ╠══════════════════════════════════════╣')
            self.stdout.write(f'    ║  Total rows:     {total_rows:>18} ║')
            self.stdout.write(f'    ║  Valid rows:     {valid_rows:>18} ║')
            self.stdout.write(f'    ║  Invalid rows:   {len(errors):>18} ║')
            self.stdout.write(f'    ║  Warnings:       {len(warnings):>18} ║')
            self.stdout.write(f'    ╚══════════════════════════════════════╝')
            
            if valid_rows == total_rows:
                self.stdout.write(self.style.SUCCESS(f'    ✓ All rows are valid and ready for import!'))
            else:
                self.stdout.write(self.style.WARNING(f'    ⚠ {len(errors)} rows have errors'))
            
            # Show first few errors
            if errors:
                self.stdout.write('')
                self.stdout.write(self.style.ERROR('    ERRORS (first 10):'))
                for err in errors[:10]:
                    self.stdout.write(f'      • {err}')
                if len(errors) > 10:
                    self.stdout.write(f'      ... and {len(errors) - 10} more errors')
            
            # Show first few warnings
            if warnings:
                self.stdout.write('')
                self.stdout.write(self.style.WARNING('    WARNINGS (first 10):'))
                for warn in warnings[:10]:
                    self.stdout.write(f'      • {warn}')
                if len(warnings) > 10:
                    self.stdout.write(f'      ... and {len(warnings) - 10} more warnings')
            
            self.stdout.write('')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'    Failed to validate CSV: {e}'))
            logger.exception('Dry run validation failed')
