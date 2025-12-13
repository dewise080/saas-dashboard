"""
Service layer for interacting with the Google Maps Scraper API.

Flow:
1. Create job via API → Get job ID → Store with 'pending' status
2. Poll for status (job takes ~3-5 minutes minimum)
3. When ready, download CSV to local file
4. Parse CSV file and import leads to database
"""
import csv
import io
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from django.conf import settings
from django.utils import timezone
import requests

from .models import ScrapeJob, GmapsLead

logger = logging.getLogger(__name__)

# API base URL - configure in settings.py
GMAPS_SCRAPER_API_URL = getattr(settings, 'GMAPS_SCRAPER_API_URL', 'http://localhost:8080')

# Directory to store downloaded CSV files
CSV_DOWNLOAD_DIR = getattr(settings, 'GMAPS_CSV_DOWNLOAD_DIR', os.path.join(settings.BASE_DIR, 'gmaps_downloads'))


class GmapsScraperService:
    """Service for interacting with Google Maps Scraper API."""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or GMAPS_SCRAPER_API_URL
        self.timeout = 60  # Increased timeout for large responses
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make HTTP request to the scraper API."""
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault('timeout', self.timeout)
        
        logger.info(f"Making {method} request to {url}")
        response = requests.request(method, url, **kwargs)
        return response
    
    def create_job(self, job_data: dict) -> dict:
        """
        Create a new scraping job.
        
        Args:
            job_data: Dictionary with job configuration
            
        Returns:
            Dictionary with job ID from API (e.g., {"id": "uuid-here"})
        """
        response = self._make_request(
            'POST',
            '/api/v1/jobs',
            json=job_data,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        return response.json()
    
    def get_job(self, job_id: str) -> Optional[dict]:
        """
        Get job details from API.
        
        Args:
            job_id: External job ID
            
        Returns:
            Dictionary with job details or None if not found
        """
        try:
            response = self._make_request('GET', f'/api/v1/jobs/{job_id}')
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error getting job {job_id}: {e}")
            return None
    
    def get_all_jobs(self) -> list:
        """
        Get all jobs from the scraper API.
        
        Returns:
            List of job dictionaries
        """
        try:
            response = self._make_request('GET', '/api/v1/jobs')
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error getting all jobs: {e}")
            return []
    
    def is_job_ready(self, job_id: str) -> Tuple[bool, str]:
        """
        Check if job is ready for download.
        
        Args:
            job_id: External job ID
            
        Returns:
            Tuple of (is_ready, status_string)
        """
        job_data = self.get_job(job_id)
        if not job_data:
            return False, 'not_found'
        
        # API may return 'Status' or 'status' (capitalized)
        status = (job_data.get('Status') or job_data.get('status', '')).lower()
        
        # Map various status strings
        if status in ['completed', 'done', 'finished', 'ready', 'ok']:
            return True, 'completed'
        elif status in ['failed', 'error']:
            return False, 'failed'
        elif status in ['pending', 'queued', 'waiting']:
            return False, 'pending'
        else:
            # Assume running/processing
            return False, 'running'
    
    def download_csv_to_file(self, job_id: str, output_path: str = None) -> Optional[str]:
        """
        Download job results as CSV and save to local file.
        This is more reliable than keeping large CSV in memory.
        
        Args:
            job_id: External job ID
            output_path: Optional path to save file. If None, uses temp directory.
            
        Returns:
            Path to downloaded file or None if failed
        """
        # Ensure download directory exists
        os.makedirs(CSV_DOWNLOAD_DIR, exist_ok=True)
        
        if output_path is None:
            output_path = os.path.join(CSV_DOWNLOAD_DIR, f"{job_id}.csv")
        
        try:
            # Stream download to avoid memory issues with large files
            response = self._make_request(
                'GET', 
                f'/api/v1/jobs/{job_id}/download',
                stream=True
            )
            
            if response.status_code == 404:
                logger.warning(f"CSV not ready yet for job {job_id}")
                return None
            
            response.raise_for_status()
            
            # Write to file in chunks
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"Downloaded CSV to {output_path}")
            return output_path
            
        except requests.RequestException as e:
            logger.error(f"Failed to download CSV for job {job_id}: {e}")
            return None
    
    def list_jobs(self) -> list:
        """List all jobs from API."""
        response = self._make_request('GET', '/api/v1/jobs')
        response.raise_for_status()
        return response.json()
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job from API."""
        response = self._make_request('DELETE', f'/api/v1/jobs/{job_id}')
        response.raise_for_status()
        return True


def create_scrape_job(job_data: dict, user=None) -> ScrapeJob:
    """
    Create a scrape job in the database and submit to the scraper API.
    
    The API accepts the job and returns a job ID. The actual scraping
    takes at least 3-5 minutes, so we store with 'pending' status
    and poll later.
    
    Args:
        job_data: Job configuration
        user: User creating the job
        
    Returns:
        Created ScrapeJob instance
    """
    service = GmapsScraperService()
    
    # Prepare API request
    api_request = {
        'name': job_data['name'],
        'keywords': job_data['keywords'],
        'lang': job_data.get('lang', 'en'),
        'zoom': job_data.get('zoom', 15),
        'depth': job_data.get('depth', 1),
        'max_time': job_data.get('max_time', 3600),
    }
    
    # Add optional fields
    if job_data.get('lat'):
        api_request['lat'] = job_data['lat']
    if job_data.get('lon'):
        api_request['lon'] = job_data['lon']
    if job_data.get('fast_mode'):
        api_request['fast_mode'] = job_data['fast_mode']
    if job_data.get('radius'):
        api_request['radius'] = job_data['radius']
    if job_data.get('email'):
        api_request['email'] = job_data['email']
    if job_data.get('proxies'):
        api_request['proxies'] = job_data['proxies']
    
    # Submit to API - if we get an ID back, the job was accepted (pending)
    try:
        api_response = service.create_job(api_request)
        external_id = api_response.get('id')
        
        if not external_id:
            raise ValueError("API did not return a job ID")
        
        # Job accepted = pending (will take 3-5+ minutes to complete)
        status = 'pending'
        logger.info(f"Job accepted by API with ID: {external_id}")
        
    except requests.RequestException as e:
        logger.error(f"Failed to create job via API: {e}")
        raise
    
    # Create local record with pending status
    job = ScrapeJob.objects.create(
        external_id=external_id,
        name=job_data['name'],
        keywords=job_data['keywords'],
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
        created_by=user,
    )
    
    return job


def refresh_job_status(job: ScrapeJob) -> ScrapeJob:
    """
    Check job status from the scraper API.
    
    Note: Jobs take at least 3-5 minutes to complete.
    Don't poll too frequently.
    
    Args:
        job: ScrapeJob instance to refresh
        
    Returns:
        Updated ScrapeJob instance
    """
    service = GmapsScraperService()
    
    is_ready, status = service.is_job_ready(job.external_id)
    
    if status == 'not_found':
        logger.warning(f"Job {job.external_id} not found in API")
        # Don't change local status - might be a temporary API issue
        return job
    
    if status == 'completed':
        job.status = 'completed'
        if not job.completed_at:
            job.completed_at = timezone.now()
    elif status == 'failed':
        job.status = 'failed'
        # Try to get error message
        job_data = service.get_job(job.external_id)
        if job_data:
            job.error_message = job_data.get('error', 'Job failed')
    elif status == 'running':
        job.status = 'running'
    # else keep as pending
    
    job.save()
    logger.info(f"Job {job.external_id} status: {job.status}")
    
    return job


def import_job_results(job: ScrapeJob) -> int:
    """
    Download CSV to local file and import leads into database.
    
    This approach:
    1. Downloads CSV to local file (avoids memory/HTTP timeout issues)
    2. Parses the local file
    3. Creates lead records
    
    Args:
        job: ScrapeJob instance
        
    Returns:
        Number of leads imported
    """
    service = GmapsScraperService()
    
    # First check if job is actually ready
    is_ready, status = service.is_job_ready(job.external_id)
    
    if not is_ready:
        if status == 'failed':
            raise ValueError(f"Job failed, cannot import results")
        elif status == 'not_found':
            raise ValueError(f"Job not found in API")
        else:
            raise ValueError(f"Job not ready yet (status: {status}). Please wait and try again.")
    
    # Download CSV to local file
    csv_path = service.download_csv_to_file(job.external_id)
    
    if not csv_path:
        raise ValueError("Failed to download CSV file. Job may not be ready yet.")
    
    # Parse local CSV file
    leads_created = 0
    duplicates_skipped = 0
    errors = []
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                try:
                    existing = _find_existing_lead(row, job)
                    if existing:
                        duplicates_skipped += 1
                        continue
                    
                    lead = _create_lead_from_csv_row(row, job)
                    if lead:
                        leads_created += 1
                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")
                    logger.warning(f"Failed to import row {row_num}: {e}")
        
        # Update job stats
        job.leads_count = job.leads.count()
        job.status = 'completed'
        job.completed_at = job.completed_at or timezone.now()
        job.csv_file_path = csv_path  # Store the CSV file path
        
        if errors:
            job.error_message = f"Imported with {len(errors)} errors. First error: {errors[0]}"
        elif duplicates_skipped:
            job.error_message = f"Skipped {duplicates_skipped} duplicate rows"
        else:
            job.error_message = None
        
        job.save()
        
        logger.info(f"Imported {leads_created} leads from job {job.external_id}")
        
    except Exception as e:
        logger.error(f"Failed to parse CSV file: {e}")
        raise
    
    return leads_created


def check_and_import_ready_jobs():
    """
    Background task to check pending jobs and import completed ones.
    
    This can be called by a cron job or Celery task every 5 minutes.
    Only checks jobs that are at least 3 minutes old (minimum scrape time).
    """
    from datetime import timedelta
    
    # Only check jobs that are pending/running and at least 3 minutes old
    min_age = timezone.now() - timedelta(minutes=3)
    
    pending_jobs = ScrapeJob.objects.filter(
        status__in=['pending', 'running'],
        created_at__lte=min_age
    )
    
    for job in pending_jobs:
        try:
            # Refresh status
            job = refresh_job_status(job)
            
            # If completed, import results
            if job.status == 'completed' and job.leads_count == 0:
                import_job_results(job)
                logger.info(f"Auto-imported {job.leads_count} leads for job {job.name}")
                
        except Exception as e:
            logger.error(f"Error processing job {job.external_id}: {e}")


def _parse_json_field(value: str) -> Optional[dict]:
    """Parse a JSON string field, returning None if empty or invalid."""
    if not value or value in ('{}', '[]', 'null', ''):
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _normalize_str(value: Optional[str], max_len: Optional[int] = None) -> Optional[str]:
    """Trim whitespace, normalize empty strings to None, and truncate if needed."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if max_len:
        return value[:max_len]
    return value


def _find_existing_lead(row: dict, job: ScrapeJob) -> Optional[GmapsLead]:
    """Check for an existing lead for this job using stable identifiers."""
    cid = _normalize_str(row.get('cid'), 100)
    data_id = _normalize_str(row.get('data_id'), 100)
    link = _normalize_str(row.get('link'), 2000)
    
    for field, value in (('cid', cid), ('data_id', data_id), ('link', link)):
        if not value:
            continue
        existing = GmapsLead.objects.filter(job=job, **{field: value}).first()
        if existing:
            return existing
    return None


def _create_lead_from_csv_row(row: dict, job: ScrapeJob) -> Optional[GmapsLead]:
    """
    Create a GmapsLead from a CSV row.
    
    Args:
        row: CSV row as dictionary
        job: Parent ScrapeJob
        
    Returns:
        Created GmapsLead or None if failed
    """
    try:
        # Parse numeric fields
        review_count = int(row.get('review_count', 0) or 0)
        review_rating = float(row.get('review_rating', 0) or 0) if row.get('review_rating') else None
        latitude = float(row.get('latitude')) if row.get('latitude') else None
        longitude = float(row.get('longitude')) if row.get('longitude') else None
        
        cid = _normalize_str(row.get('cid'), 100)
        data_id = _normalize_str(row.get('data_id'), 100)
        link = _normalize_str(row.get('link'), 2000)
        category = _normalize_str(row.get('category'), 255)
        phone = _normalize_str(row.get('phone'), 50)
        website = _normalize_str(row.get('website'), 2000)
        reviews_link = _normalize_str(row.get('reviews_link'), 2000)
        thumbnail = _normalize_str(row.get('thumbnail'), 2000)
        
        lead = GmapsLead.objects.create(
            job=job,
            input_id=row.get('input_id'),
            cid=cid,
            data_id=data_id,
            title=row.get('title', '')[:500],
            link=link,
            category=category,
            address=row.get('address'),
            phone=phone,
            website=website,
            plus_code=row.get('plus_code'),
            emails=row.get('emails'),
            latitude=latitude,
            longitude=longitude,
            timezone=row.get('timezone'),
            complete_address=_parse_json_field(row.get('complete_address')),
            open_hours=_parse_json_field(row.get('open_hours')),
            popular_times=_parse_json_field(row.get('popular_times')),
            review_count=review_count,
            review_rating=review_rating,
            reviews_per_rating=_parse_json_field(row.get('reviews_per_rating')),
            reviews_link=reviews_link,
            user_reviews=_parse_json_field(row.get('user_reviews')),
            user_reviews_extended=_parse_json_field(row.get('user_reviews_extended')),
            thumbnail=thumbnail,
            images=_parse_json_field(row.get('images')),
            status=row.get('status'),
            descriptions=row.get('descriptions'),
            price_range=row.get('price_range'),
            about=_parse_json_field(row.get('about')),
            reservations=_parse_json_field(row.get('reservations')),
            order_online=_parse_json_field(row.get('order_online')),
            menu=_parse_json_field(row.get('menu')),
            owner=_parse_json_field(row.get('owner')),
        )
        return lead
        
    except Exception as e:
        logger.error(f"Failed to create lead from row: {e}")
        return None
