from rest_framework import serializers
from .models import ScrapeJob, GmapsLead, WhatsAppContact, LeadWebsite, EmailTemplate


class ScrapeJobCreateSerializer(serializers.Serializer):
    """Serializer for creating a new scrape job."""
    name = serializers.CharField(max_length=255)
    keywords = serializers.ListField(child=serializers.CharField(), min_length=1)
    lang = serializers.CharField(max_length=10, default='en')
    zoom = serializers.IntegerField(default=15, min_value=1, max_value=21)
    lat = serializers.CharField(max_length=50, required=False, allow_blank=True)
    lon = serializers.CharField(max_length=50, required=False, allow_blank=True)
    fast_mode = serializers.BooleanField(default=False)
    radius = serializers.IntegerField(required=False, allow_null=True)
    depth = serializers.IntegerField(default=1, min_value=1, max_value=10)
    email = serializers.BooleanField(default=False)
    max_time = serializers.IntegerField(default=3600, min_value=60)
    proxies = serializers.ListField(child=serializers.CharField(), required=False)


class ScrapeJobSerializer(serializers.ModelSerializer):
    """Serializer for ScrapeJob model."""
    leads_count = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = ScrapeJob
        fields = [
            'id', 'external_id', 'name', 'keywords', 'lang', 'zoom',
            'lat', 'lon', 'fast_mode', 'radius', 'depth', 'email',
            'max_time', 'proxies', 'status', 'error_message', 'leads_count',
            'created_at', 'updated_at', 'completed_at'
        ]
        read_only_fields = ['id', 'external_id', 'status', 'error_message', 'leads_count', 'created_at', 'updated_at', 'completed_at']


class GmapsLeadSerializer(serializers.ModelSerializer):
    """Serializer for GmapsLead model."""
    city = serializers.SerializerMethodField()
    country = serializers.SerializerMethodField()
    
    class Meta:
        model = GmapsLead
        fields = [
            'id', 'job', 'input_id', 'cid', 'data_id', 'title', 'link',
            'category', 'address', 'phone', 'website', 'plus_code', 'emails',
            'latitude', 'longitude', 'timezone', 'complete_address',
            'open_hours', 'popular_times', 'review_count', 'review_rating',
            'reviews_per_rating', 'reviews_link', 'user_reviews',
            'user_reviews_extended', 'thumbnail', 'images', 'status',
            'descriptions', 'price_range', 'about', 'reservations',
            'order_online', 'menu', 'owner', 'created_at', 'updated_at',
            'city', 'country'
        ]
    
    def get_city(self, obj):
        if obj.complete_address and isinstance(obj.complete_address, dict):
            return obj.complete_address.get('city')
        return None
    
    def get_country(self, obj):
        if obj.complete_address and isinstance(obj.complete_address, dict):
            return obj.complete_address.get('country')
        return None


class GmapsLeadListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing leads."""
    city = serializers.SerializerMethodField()
    
    class Meta:
        model = GmapsLead
        fields = [
            'id', 'title', 'category', 'address', 'phone', 'website',
            'review_count', 'review_rating', 'city', 'created_at'
        ]
    
    def get_city(self, obj):
        if obj.complete_address and isinstance(obj.complete_address, dict):
            return obj.complete_address.get('city')
        return None


# ============================================================================
# Lead Context Serializers (for AI consumption)
# ============================================================================

class LeadWebsiteContextSerializer(serializers.ModelSerializer):
    """Serializer for website data in AI context."""
    
    class Meta:
        model = LeadWebsite
        fields = [
            'url', 'page_title', 'meta_description', 'headings',
            'paragraphs', 'emails', 'phone_numbers', 'addresses',
            'social_links', 'ai_services'
        ]


class LeadContextSerializer(serializers.ModelSerializer):
    """
    Serializer providing comprehensive lead context for AI email generation.
    
    OpenAPI 3.1 Schema:
    GET /api/gmaps-leads/{id}/context/
    
    Returns all relevant business information for personalized email generation.
    """
    website_data = serializers.SerializerMethodField(help_text="Scraped website content and extracted emails")
    whatsapp_contacts = serializers.SerializerMethodField(help_text="WhatsApp contact info if available")
    phone_type = serializers.CharField(read_only=True, help_text="Type: whatsapp, local, other, or none")
    available_emails = serializers.SerializerMethodField(help_text="All available email addresses for this lead")
    
    class Meta:
        model = GmapsLead
        fields = [
            # Core business info
            'id', 'title', 'category', 'address', 'complete_address',
            'phone', 'phone_type', 'website', 'emails',
            
            # Ratings and reviews
            'review_count', 'review_rating', 'reviews_per_rating',
            
            # Location
            'latitude', 'longitude', 'timezone', 'plus_code',
            
            # Business details
            'open_hours', 'about', 'descriptions', 'price_range',
            'menu', 'reservations', 'order_online',
            
            # Related data
            'website_data', 'whatsapp_contacts', 'available_emails',
        ]
    
    def get_website_data(self, obj):
        """Get scraped website data if available."""
        try:
            if hasattr(obj, 'website_data') and obj.website_data:
                return obj.website_data.to_ai_context()
        except Exception:
            pass
        return None
    
    def get_whatsapp_contacts(self, obj):
        """Get WhatsApp contacts for this lead."""
        if not hasattr(obj, "whatsapp_contacts"):
            return []
        try:
            contacts = obj.whatsapp_contacts.all()
            if contacts.exists():
                return [
                    {'chat_id': c.chat_id, 'jid': c.jid, 'phone': getattr(c, 'phone_raw', None)}
                    for c in contacts
                ]
        except Exception:
            return []
        return []
    
    def get_available_emails(self, obj):
        """Get all available emails from all sources."""
        emails = set()
        
        # From lead's emails field
        if obj.emails:
            try:
                import json
                lead_emails = json.loads(obj.emails) if isinstance(obj.emails, str) else obj.emails
                if isinstance(lead_emails, list):
                    emails.update(lead_emails)
                elif lead_emails:
                    emails.add(str(lead_emails))
            except:
                pass
        
        # From website data
        try:
            if hasattr(obj, 'website_data') and obj.website_data and obj.website_data.emails:
                emails.update(obj.website_data.emails)
        except Exception:
            pass
        
        return list(emails)


# ============================================================================
# Email Template Serializers
# ============================================================================

class EmailTemplateCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating/updating email templates via API.
    
    OpenAPI 3.1 Schema:
    POST /api/gmaps-leads/{lead_id}/email-template/
    
    Used by AI to submit generated email content.
    """
    mark_ready = serializers.BooleanField(
        required=False, 
        default=False,
        write_only=True,
        help_text="If true, immediately mark template as 'ready' to send (emits signal)"
    )
    
    class Meta:
        model = EmailTemplate
        fields = [
            # Required fields
            'subject', 'body_html',
            
            # Optional content
            'body_plain', 'name', 'template_type',
            
            # Optional recipient override
            'recipient_email', 'recipient_name',
            
            # Optional sender info
            'sender_name', 'sender_email', 'reply_to',
            
            # (AI metadata fields removed)
            
            # Control
            'mark_ready',
        ]
    
    def create(self, validated_data):
        mark_ready = validated_data.pop('mark_ready', False)
        
        # Get lead from view context
        lead = self.context.get('lead')
        if lead:
            validated_data['lead'] = lead
        
        # Set status based on mark_ready
        if mark_ready:
            validated_data['status'] = 'ready'
        else:
            validated_data['status'] = 'draft'
        
        instance = super().create(validated_data)
        
        # Emit signal if marked ready
        if mark_ready:
            from .signals import email_template_ready
            email_template_ready.send(sender=self.__class__, instance=instance)
        
        return instance
    
    def update(self, instance, validated_data):
        mark_ready = validated_data.pop('mark_ready', False)
        
        instance = super().update(instance, validated_data)
        
        # If marking ready, update status and emit signal
        if mark_ready and instance.status != 'ready':
            instance.status = 'ready'
            instance.save()
            from .signals import email_template_ready
            email_template_ready.send(sender=self.__class__, instance=instance)
        
        return instance


class EmailTemplateSerializer(serializers.ModelSerializer):
    """
    Full serializer for email template responses.
    
    OpenAPI 3.1 Schema:
    GET /api/email-templates/{id}/
    GET /api/gmaps-leads/{lead_id}/email-templates/
    """
    lead_title = serializers.CharField(source='lead.title', read_only=True)
    target_email = serializers.CharField(read_only=True)
    is_ready_to_send = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = EmailTemplate
        fields = [
            'id', 'lead', 'lead_title',
            
            # Template info
            'name', 'template_type',
            
            # Email content
            'subject', 'body_html', 'body_plain',
            
            # Recipient
            'recipient_email', 'recipient_name', 'target_email',
            
            # Sender
            'sender_name', 'sender_email', 'reply_to',
            
            # Status
            'status', 'status_message', 'is_ready_to_send',
            
            # (AI metadata fields removed)
            
            # Tracking
            'sent_at', 'opened_at', 'clicked_at',
            
            # Timestamps
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'sent_at', 'opened_at', 'clicked_at']


class EmailTemplateListSerializer(serializers.ModelSerializer):
    """Compact serializer for listing email templates."""
    lead_title = serializers.CharField(source='lead.title', read_only=True)
    target_email = serializers.CharField(read_only=True)
    
    class Meta:
        model = EmailTemplate
        fields = [
            'id', 'lead', 'lead_title', 'subject', 'template_type',
            'status', 'target_email', 'created_at'
        ]


class EmailTemplateStatusUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating email template status.
    
    OpenAPI 3.1 Schema:
    PATCH /api/email-templates/{id}/status/
    """
    status = serializers.ChoiceField(
        choices=['draft', 'ready', 'approved', 'rejected'],
        help_text="New status for the template"
    )
    status_message = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional message explaining status change"
    )
