from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class ScrapeJob(models.Model):
    """
    Model to track Google Maps scraping jobs.
    
    Flow:
    1. Job created → status='pending'
    2. API accepts job → we store external_id
    3. Wait 3-5+ minutes for scraping to complete
    4. Poll API for status → update to 'running' or 'completed'
    5. Download CSV → import leads → status='completed'
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    # Job identification
    external_id = models.CharField(max_length=100, unique=True, help_text="External job ID from scraper API")
    name = models.CharField(max_length=255, help_text="Job name/description")
    
    # Job configuration
    keywords = models.JSONField(help_text="List of search keywords")
    lang = models.CharField(max_length=10, default='en', help_text="Language code")
    zoom = models.IntegerField(default=15, help_text="Map zoom level")
    lat = models.CharField(max_length=50, blank=True, null=True, help_text="Latitude")
    lon = models.CharField(max_length=50, blank=True, null=True, help_text="Longitude")
    fast_mode = models.BooleanField(default=False, help_text="Enable fast mode")
    radius = models.IntegerField(blank=True, null=True, help_text="Search radius")
    depth = models.IntegerField(default=1, help_text="Search depth")
    email = models.BooleanField(default=False, help_text="Extract emails")
    max_time = models.IntegerField(default=3600, help_text="Maximum time in seconds")
    proxies = models.JSONField(blank=True, null=True, help_text="List of proxies")
    
    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)
    leads_count = models.IntegerField(default=0, help_text="Number of leads found")
    csv_file_path = models.CharField(max_length=500, blank=True, null=True, help_text="Path to downloaded CSV file")
    
    # Ownership
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='scrape_jobs')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Scrape Job"
        verbose_name_plural = "Scrape Jobs"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.status})"
    
    @property
    def age_seconds(self):
        """Return job age in seconds."""
        return (timezone.now() - self.created_at).total_seconds()
    
    @property
    def age_display(self):
        """Return human-readable age."""
        seconds = self.age_seconds
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m"
        else:
            return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"
    
    @property
    def is_ready_to_poll(self):
        """Check if job is old enough to poll (at least 3 minutes)."""
        return self.age_seconds >= 180  # 3 minutes


class GmapsLead(models.Model):
    """
    Model to store Google Maps business leads data.
    Fields are based on the CSV export format from Google Maps scraping.
    """
    
    # Link to scrape job
    job = models.ForeignKey(ScrapeJob, on_delete=models.CASCADE, related_name='leads', null=True, blank=True)
    
    # Identifiers
    input_id = models.CharField(max_length=255, blank=True, null=True, help_text="Input batch ID")
    cid = models.CharField(max_length=100, blank=True, null=True, db_index=True, help_text="Google Maps CID")
    data_id = models.CharField(max_length=100, blank=True, null=True, help_text="Google Maps data ID")
    
    # Basic Info
    title = models.CharField(max_length=500, help_text="Business name")
    link = models.URLField(max_length=2000, blank=True, null=True, help_text="Google Maps link")
    category = models.CharField(max_length=255, blank=True, null=True, help_text="Business category")
    
    # Contact Info
    address = models.TextField(blank=True, null=True, help_text="Full address")
    phone = models.CharField(max_length=50, blank=True, null=True, help_text="Phone number")
    website = models.URLField(max_length=2000, blank=True, null=True, help_text="Business website")
    plus_code = models.CharField(max_length=100, blank=True, null=True, help_text="Google Plus Code")
    emails = models.TextField(blank=True, null=True, help_text="Email addresses (comma-separated or JSON)")
    
    # Location
    latitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    timezone = models.CharField(max_length=100, blank=True, null=True, help_text="Timezone")
    
    # Complete Address (parsed)
    complete_address = models.JSONField(blank=True, null=True, help_text="Parsed address as JSON (borough, street, city, postal_code, state, country)")
    
    # Hours & Times
    open_hours = models.JSONField(blank=True, null=True, help_text="Opening hours as JSON")
    popular_times = models.JSONField(blank=True, null=True, help_text="Popular times data as JSON")
    
    # Reviews
    review_count = models.IntegerField(default=0, help_text="Number of reviews")
    review_rating = models.DecimalField(max_digits=3, decimal_places=1, blank=True, null=True, help_text="Average rating")
    reviews_per_rating = models.JSONField(blank=True, null=True, help_text="Review distribution per rating as JSON")
    reviews_link = models.URLField(max_length=2000, blank=True, null=True, help_text="Link to reviews")
    user_reviews = models.JSONField(blank=True, null=True, help_text="User reviews as JSON")
    user_reviews_extended = models.JSONField(blank=True, null=True, help_text="Extended user reviews as JSON")
    
    # Media
    thumbnail = models.URLField(max_length=2000, blank=True, null=True, help_text="Thumbnail image URL")
    images = models.JSONField(blank=True, null=True, help_text="Images as JSON array")
    
    # Business Details
    status = models.CharField(max_length=100, blank=True, null=True, help_text="Business status")
    descriptions = models.TextField(blank=True, null=True, help_text="Business descriptions")
    price_range = models.CharField(max_length=50, blank=True, null=True, help_text="Price range indicator")
    about = models.JSONField(blank=True, null=True, help_text="About section as JSON (accessibility, amenities, etc.)")
    
    # Links & Services
    reservations = models.JSONField(blank=True, null=True, help_text="Reservation links as JSON")
    order_online = models.JSONField(blank=True, null=True, help_text="Online ordering links as JSON")
    menu = models.JSONField(blank=True, null=True, help_text="Menu link as JSON")
    
    # Owner Info
    owner = models.JSONField(blank=True, null=True, help_text="Owner information as JSON (id, name, link)")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Google Maps Lead"
        verbose_name_plural = "Google Maps Leads"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['title']),
            models.Index(fields=['category']),
            models.Index(fields=['phone']),
            models.Index(fields=['review_rating']),
        ]

    def __str__(self):
        return f"{self.title} - {self.category or 'No category'}"
    
    @property
    def phone_type(self):
        """
        Classify phone number type.
        Returns: 'whatsapp', 'local', 'other', or 'none'
        """
        if not self.phone:
            return 'none'
        
        # Clean the phone number
        cleaned = ''.join(c for c in self.phone if c.isdigit())
        
        # Turkish mobile numbers (WhatsApp eligible): 905XX
        if cleaned.startswith('905') and len(cleaned) >= 12:
            return 'whatsapp'
        # Turkish landlines: 90212, 90216, etc.
        elif cleaned.startswith('90') and len(cleaned) >= 11:
            prefix = cleaned[2:5] if len(cleaned) > 5 else ''
            if prefix.startswith('2') or prefix.startswith('3') or prefix.startswith('4'):
                return 'local'
            return 'other'
        else:
            return 'other'
    
    @property
    def cleaned_phone(self):
        """Return phone with only digits."""
        if not self.phone:
            return None
        return ''.join(c for c in self.phone if c.isdigit())
    
    @property
    def has_website(self):
        """Check if lead has a website."""
        return bool(self.website)


class WhatsAppContact(models.Model):
    """
    Model to store WhatsApp contact information extracted from leads.
    Stores formatted WhatsApp IDs for integration with WhatsApp Business API.
    """
    
    # Link to original lead
    lead = models.OneToOneField(GmapsLead, on_delete=models.CASCADE, related_name='whatsapp_contact')
    
    # Raw phone number (digits only)
    phone_number = models.CharField(max_length=20, db_index=True, help_text="Phone number (digits only)")
    
    # WhatsApp formatted IDs
    chat_id = models.CharField(max_length=50, db_index=True, help_text="WhatsApp Chat ID (905XXXXXXXX@c.us)")
    jid = models.CharField(max_length=50, db_index=True, help_text="WhatsApp JID (905XXXXXXXX@s.whatsapp.net)")
    lid = models.CharField(max_length=100, blank=True, null=True, help_text="WhatsApp LID (reserved for future use)")
    
    # Contact info from lead (denormalized for quick access)
    business_name = models.CharField(max_length=500, help_text="Business name from lead")
    category = models.CharField(max_length=255, blank=True, null=True, help_text="Business category")
    
    # Status tracking
    is_verified = models.BooleanField(default=False, help_text="Whether this WhatsApp number has been verified")
    is_valid = models.BooleanField(default=True, help_text="Whether this is a valid WhatsApp number")
    last_checked = models.DateTimeField(blank=True, null=True, help_text="Last time the number was validated")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "WhatsApp Contact"
        verbose_name_plural = "WhatsApp Contacts"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['phone_number']),
            models.Index(fields=['chat_id']),
            models.Index(fields=['is_verified']),
        ]

    def __str__(self):
        return f"{self.business_name} - {self.chat_id}"
    
    @classmethod
    def create_from_lead(cls, lead: GmapsLead) -> 'WhatsAppContact':
        """
        Create a WhatsAppContact from a GmapsLead.
        
        Args:
            lead: GmapsLead instance with a WhatsApp-eligible phone number
            
        Returns:
            WhatsAppContact instance
        """
        if lead.phone_type != 'whatsapp':
            raise ValueError(f"Lead phone is not WhatsApp eligible: {lead.phone}")
        
        phone = lead.cleaned_phone
        
        # Format: 905XXXXXXXX@c.us (Chat ID)
        chat_id = f"{phone}@c.us"
        
        # Format: 905XXXXXXXX@s.whatsapp.net (JID)
        jid = f"{phone}@s.whatsapp.net"
        
        return cls.objects.create(
            lead=lead,
            phone_number=phone,
            chat_id=chat_id,
            jid=jid,
            business_name=lead.title,
            category=lead.category,
        )


class LeadWebsite(models.Model):
    """
    Model to store scraped website content from leads.
    
    Designed to be API-friendly for future AI agent analysis.
    Stores structured content that can be used to generate
    contextual assistant prompts relevant to the business.
    
    AI Use Cases:
    - Generate personalized outreach messages
    - Create business-specific chatbot prompts
    - Analyze services/products offered
    - Extract business tone and style
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('scraping', 'Scraping'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('no_content', 'No Content'),
    ]
    
    # Link to original lead
    lead = models.OneToOneField(GmapsLead, on_delete=models.CASCADE, related_name='website_data')
    
    # Original URL
    url = models.URLField(max_length=2000, help_text="Website URL scraped")
    final_url = models.URLField(max_length=2000, blank=True, null=True, help_text="Final URL after redirects")
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True, help_text="Error message if scraping failed")
    http_status_code = models.IntegerField(blank=True, null=True, help_text="HTTP response status code")
    
    # ===== EXTRACTED EMAILS =====
    emails = models.JSONField(default=list, help_text="List of extracted email addresses")
    emails_count = models.IntegerField(default=0, help_text="Number of emails found")
    
    # ===== STRUCTURED CONTENT (for AI analysis) =====
    
    # Page metadata
    page_title = models.CharField(max_length=500, blank=True, null=True, help_text="<title> tag content")
    meta_description = models.TextField(blank=True, null=True, help_text="Meta description")
    meta_keywords = models.TextField(blank=True, null=True, help_text="Meta keywords")
    
    # Structured text content
    headings = models.JSONField(default=dict, help_text="Headings by level: {h1: [...], h2: [...], ...}")
    paragraphs = models.JSONField(default=list, help_text="Main paragraph content (cleaned)")
    
    # Navigation & structure
    navigation_links = models.JSONField(default=list, help_text="Main navigation menu items")
    footer_content = models.TextField(blank=True, null=True, help_text="Footer text content")
    
    # Contact info found on page
    phone_numbers = models.JSONField(default=list, help_text="Phone numbers found on page")
    addresses = models.JSONField(default=list, help_text="Addresses found on page")
    social_links = models.JSONField(default=dict, help_text="Social media links: {facebook: url, ...}")
    
    # Full text for analysis
    full_text = models.TextField(blank=True, null=True, help_text="Full page text content (cleaned)")
    full_text_length = models.IntegerField(default=0, help_text="Character count of full text")
    
    # Raw HTML (optional, for re-processing)
    raw_html = models.TextField(blank=True, null=True, help_text="Raw HTML content (compressed)")
    
    # ===== AI-READY SUMMARY =====
    # This will be populated by AI in the future
    ai_summary = models.TextField(blank=True, null=True, help_text="AI-generated business summary")
    ai_services = models.JSONField(default=list, help_text="AI-extracted services/products")
    ai_keywords = models.JSONField(default=list, help_text="AI-extracted business keywords")
    ai_tone = models.CharField(max_length=50, blank=True, null=True, help_text="AI-detected business tone (formal, casual, etc.)")
    ai_processed_at = models.DateTimeField(blank=True, null=True, help_text="When AI analysis was done")
    
    # Timestamps
    scraped_at = models.DateTimeField(blank=True, null=True, help_text="When the website was scraped")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lead Website"
        verbose_name_plural = "Lead Websites"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['emails_count']),
            models.Index(fields=['scraped_at']),
        ]

    def __str__(self):
        return f"{self.lead.title} - {self.url}"
    
    @property
    def has_emails(self):
        return self.emails_count > 0
    
    @property
    def has_content(self):
        return bool(self.full_text and len(self.full_text) > 100)
    
    @property
    def is_ai_processed(self):
        return self.ai_processed_at is not None
    
    def to_ai_context(self) -> dict:
        """
        Return structured data ready for AI analysis.
        This format is designed for LLM prompt injection.
        """
        return {
            'business_name': self.lead.title,
            'category': self.lead.category,
            'website_url': self.url,
            'page_title': self.page_title,
            'meta_description': self.meta_description,
            'headings': self.headings,
            'main_content': self.paragraphs[:10] if self.paragraphs else [],  # First 10 paragraphs
            'services': self.ai_services,
            'contact': {
                'emails': self.emails,
                'phones': self.phone_numbers,
                'addresses': self.addresses,
                'social': self.social_links,
            },
            'full_text_preview': self.full_text[:2000] if self.full_text else None,
        }


class EmailTemplate(models.Model):
    """
    Model to store customized email templates for each lead.
    
    Designed for AI-driven email generation workflow:
    1. AI fetches lead context via GET /api/leads/{id}/context/
    2. AI generates personalized email content
    3. AI posts to POST /api/leads/{id}/email-template/
    4. Status changes to 'ready' - signal emitted
    5. Human reviews and sends (or automated sending later)
    
    Supports rich text (HTML) for professional email formatting.
    """
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('generating', 'AI Generating'),
        ('ready', 'Ready to Send'),
        ('approved', 'Approved'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('rejected', 'Rejected'),
    ]
    
    TEMPLATE_TYPE_CHOICES = [
        ('outreach', 'Cold Outreach'),
        ('followup', 'Follow-up'),
        ('introduction', 'Introduction'),
        ('proposal', 'Business Proposal'),
        ('custom', 'Custom'),
    ]
    
    # Link to lead
    lead = models.ForeignKey(GmapsLead, on_delete=models.CASCADE, related_name='email_templates')
    
    # Template metadata
    name = models.CharField(max_length=255, blank=True, null=True, help_text="Template name/identifier")
    template_type = models.CharField(max_length=20, choices=TEMPLATE_TYPE_CHOICES, default='outreach')
    
    # Email content (rich text HTML supported)
    subject = models.CharField(max_length=500, help_text="Email subject line")
    body_html = models.TextField(help_text="Email body in HTML format (rich text)")
    body_plain = models.TextField(blank=True, null=True, help_text="Plain text version of email body")
    
    # Recipient info (can override lead's email)
    recipient_email = models.EmailField(blank=True, null=True, help_text="Target email (defaults to lead's email)")
    recipient_name = models.CharField(max_length=255, blank=True, null=True, help_text="Recipient name for personalization")
    
    # Sender info
    sender_name = models.CharField(max_length=255, blank=True, null=True, help_text="From name")
    sender_email = models.EmailField(blank=True, null=True, help_text="From email")
    reply_to = models.EmailField(blank=True, null=True, help_text="Reply-to email")
    
    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    status_message = models.TextField(blank=True, null=True, help_text="Status details/error message")
    
    # AI generation metadata
    ai_model = models.CharField(max_length=100, blank=True, null=True, help_text="AI model used for generation")
    ai_prompt_used = models.TextField(blank=True, null=True, help_text="Prompt used to generate this email")
    ai_generation_time = models.FloatField(blank=True, null=True, help_text="Time taken to generate (seconds)")
    ai_tokens_used = models.IntegerField(blank=True, null=True, help_text="Tokens used in generation")
    
    # Personalization variables (for future template engine)
    variables = models.JSONField(default=dict, help_text="Variables used in template: {var_name: value}")
    
    # Tracking
    is_personalized = models.BooleanField(default=False, help_text="Whether AI personalized this for the specific lead")
    personalization_score = models.FloatField(blank=True, null=True, help_text="AI confidence score 0-1")
    
    # Send tracking
    sent_at = models.DateTimeField(blank=True, null=True, help_text="When email was sent")
    opened_at = models.DateTimeField(blank=True, null=True, help_text="When email was opened (if tracked)")
    clicked_at = models.DateTimeField(blank=True, null=True, help_text="When link was clicked (if tracked)")
    
    # Ownership
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='email_templates')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Email Template"
        verbose_name_plural = "Email Templates"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['template_type']),
            models.Index(fields=['lead', 'status']),
        ]

    def __str__(self):
        return f"{self.lead.title} - {self.subject[:50]}"
    
    @property
    def is_ready_to_send(self):
        """Check if template is ready for sending."""
        return self.status in ['ready', 'approved']
    
    @property
    def target_email(self):
        """Get the email address to send to."""
        if self.recipient_email:
            return self.recipient_email
        # Try to get from lead's website data
        if hasattr(self.lead, 'website_data') and self.lead.website_data and self.lead.website_data.emails:
            return self.lead.website_data.emails[0]
        # Fall back to lead's emails field
        if self.lead.emails:
            try:
                import json
                emails = json.loads(self.lead.emails) if isinstance(self.lead.emails, str) else self.lead.emails
                if emails:
                    return emails[0] if isinstance(emails, list) else emails
            except:
                pass
        return None
    
    def mark_ready(self):
        """Mark template as ready to send and trigger signal."""
        self.status = 'ready'
        self.save()
    
    def mark_sent(self):
        """Mark template as sent."""
        self.status = 'sent'
        self.sent_at = timezone.now()
        self.save()
    
    def to_api_response(self) -> dict:
        """Return data formatted for API response."""
        return {
            'id': self.id,
            'lead_id': self.lead_id,
            'business_name': self.lead.title,
            'template_type': self.template_type,
            'subject': self.subject,
            'body_html': self.body_html,
            'body_plain': self.body_plain,
            'recipient_email': self.target_email,
            'recipient_name': self.recipient_name,
            'status': self.status,
            'is_personalized': self.is_personalized,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
