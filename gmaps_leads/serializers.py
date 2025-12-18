from rest_framework import serializers
from .models import (
    ScrapeJob,
    GmapsLead,
    WhatsAppContact,
    LeadWebsite,
    CustomizedContact,
    AIMemory,
    WhatsAppCampaign,
    WhatsAppCampaignRecipient,
    WhatsAppTemplatePool,
    WhatsAppTemplate,
)
from apps.emailing.models import EmailCampaign, CampaignRecipient


# Serializer for the simple AI memory model

class AIMemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AIMemory
        fields = ["id", "memory_type", "content", "created_at"]
        read_only_fields = ["id", "created_at"]


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
    
    def get_city(self, obj) -> str | None:
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
    
    def get_city(self, obj) -> str | None:
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
    
    def get_website_data(self, obj) -> dict | None:
        """Get scraped website data if available."""
        try:
            if hasattr(obj, 'website_data') and obj.website_data:
                return obj.website_data.to_ai_context()
        except Exception:
            pass
        return None

    def get_whatsapp_contacts(self, obj) -> list:
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

    def get_available_emails(self, obj) -> list[str]:
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

class CustomizedContactCreateSerializer(serializers.ModelSerializer):
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
        model = CustomizedContact
        fields = [
            'subject', 'body_html',
            'name', 'template_type',
            'recipient_email', 'recipient_name',
            'mark_ready',
            'status',
        ]
        read_only_fields = ['status']
    
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


class CustomizedContactSerializer(serializers.ModelSerializer):
    """
    Full serializer for customized contact responses.
    """
    lead_title = serializers.CharField(source='lead.title', read_only=True)
    class Meta:
        model = CustomizedContact
        fields = [
            'id', 'lead', 'lead_title',
            'name', 'template_type',
            'subject', 'body_html',
            'recipient_email', 'recipient_name',
            'status',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'status']


class CustomizedContactListSerializer(serializers.ModelSerializer):
    """Compact serializer for listing customized contacts."""
    lead_title = serializers.CharField(source='lead.title', read_only=True)
    class Meta:
        model = CustomizedContact
        fields = [
            'id', 'lead', 'lead_title', 'subject', 'template_type', 'status', 'created_at'
        ]

# ============================================================================
# AI Campaign/Recipient Serializers
# ============================================================================


class AICampaignSerializer(serializers.ModelSerializer):
    progress_percent = serializers.FloatField(read_only=True)

    class Meta:
        model = EmailCampaign
        fields = [
            "id",
            "name",
            "status",
            "provider_alias",
            "expected_recipients",
            "sent_count",
            "failed_count",
            "skipped_count",
            "progress_percent",
            "last_dispatched_at",
        ]


class AICampaignRecipientStatusSerializer(serializers.Serializer):
    pending = serializers.IntegerField()
    ready = serializers.IntegerField()
    rendered = serializers.IntegerField()
    sending = serializers.IntegerField()
    sent = serializers.IntegerField()
    failed = serializers.IntegerField()
    skipped = serializers.IntegerField()


class AICampaignRecipientContextSerializer(serializers.ModelSerializer):
    campaign_id = serializers.IntegerField(source="campaign.id", read_only=True)
    email = serializers.EmailField(source="email_address.email", read_only=True)
    business_name = serializers.CharField(source="context.business_name", read_only=True)
    website = serializers.CharField(source="context.website", read_only=True)
    category = serializers.CharField(source="context.category", read_only=True, allow_null=True)
    full_text = serializers.CharField(source="context.full_text", read_only=True, allow_blank=True)

    class Meta:
        model = CampaignRecipient
        fields = [
            "id",
            "campaign_id",
            "status",
            "email",
            "business_name",
            "category",
            "website",
            "full_text",
            "context",
            "subject",
            "body_html",
            "body_text",
        ]


class AICampaignRecipientContentSerializer(serializers.Serializer):
    subject = serializers.CharField()
    body_html = serializers.CharField()
    body_text = serializers.CharField(required=False, allow_blank=True)
    mark_ready = serializers.BooleanField(default=True)


class AICampaignRecipientListSerializer(serializers.ModelSerializer):
    campaign_id = serializers.IntegerField(source="campaign.id", read_only=True)
    email = serializers.EmailField(source="email_address.email", read_only=True)
    business_name = serializers.CharField(source="context.business_name", read_only=True)
    category = serializers.CharField(source="context.category", read_only=True, allow_null=True)

    class Meta:
        model = CampaignRecipient
        fields = [
            "id",
            "campaign_id",
            "status",
            "email",
            "business_name",
            "category",
        ]

    # Status update serializer removed as status field is no longer present in model


class WahaContactSyncSerializer(serializers.Serializer):
    """Request payload for syncing WhatsApp leads into WAHA."""

    job_id = serializers.IntegerField(required=False, help_text="Limit sync to a specific scrape job.")
    limit = serializers.IntegerField(
        required=False, min_value=1, max_value=500, default=100, help_text="Max number of leads to push."
    )
    dry_run = serializers.BooleanField(default=True, help_text="When true, do not call WAHA; just preview payload.")
    force_refresh = serializers.BooleanField(
        default=False, help_text="Rebuild WhatsAppContact records even if they already exist."
    )


class WahaSendMessageSerializer(serializers.Serializer):
    """Request payload for sending a WhatsApp message via WAHA."""

    chat_id = serializers.CharField(
        required=False,
        help_text="WhatsApp chatId (e.g., 905XXXXXXXX@c.us). Optional if phone or lead_id is provided.",
    )
    phone = serializers.CharField(
        required=False,
        help_text="Digits-only phone number; formatted to chatId automatically if chat_id not provided.",
    )
    lead_id = serializers.IntegerField(
        required=False,
        help_text="Resolve the chatId from this lead's WhatsAppContact (creates one if possible).",
    )
    text = serializers.CharField(help_text="Message text to send.")
    quoted_message_id = serializers.CharField(
        required=False, allow_blank=True, help_text="Optional WAHA message id to quote/reply to."
    )

    def validate(self, attrs):
        if not (attrs.get("chat_id") or attrs.get("phone") or attrs.get("lead_id")):
            raise serializers.ValidationError("Provide chat_id, phone, or lead_id.")
        return attrs


class WahaTestMessageSerializer(serializers.Serializer):
    """
    Preview or send a single WhatsApp message using a template/pool/campaign context.
    Designed for testing message shape (text/media) without running a whole campaign.
    """

    # Recipient
    chat_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, help_text="e.g., 905XXXXXXXX@c.us")
    jid = serializers.CharField(required=False, allow_blank=True, allow_null=True, help_text="e.g., 905XXXXXXXX@s.whatsapp.net (will be normalized)")
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True, help_text="Digits-only or +E164; converted to chatId")

    # Content source
    text = serializers.CharField(required=False, allow_blank=True, allow_null=True, help_text="Raw text (optional if template_id/pool_id/campaign_id provided)")
    template_id = serializers.IntegerField(required=False, help_text="Use a specific WhatsAppTemplate")
    pool_id = serializers.IntegerField(required=False, help_text="Pick a random template from this pool")
    campaign_id = serializers.IntegerField(required=False, help_text="Use this campaign's pool/fallback settings")

    # Render context
    lead_id = serializers.IntegerField(required=False, allow_null=True, help_text="Use lead fields for {{business_name}}, etc.")
    business_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    category = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    website = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # Options
    dry_run = serializers.BooleanField(default=True, help_text="When true, do not send; only preview payload")
    link_preview = serializers.BooleanField(required=False, allow_null=True)
    link_preview_high_quality = serializers.BooleanField(required=False, allow_null=True)
    reply_to = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        if not (attrs.get("chat_id") or attrs.get("jid") or attrs.get("phone")):
            raise serializers.ValidationError("Provide chat_id, jid, or phone.")
        if not (attrs.get("text") is not None or attrs.get("template_id") or attrs.get("pool_id") or attrs.get("campaign_id")):
            raise serializers.ValidationError("Provide text, template_id, pool_id, or campaign_id.")
        return attrs


class WhatsAppCampaignSerializer(serializers.ModelSerializer):
    job_id = serializers.IntegerField(write_only=True)
    template_pool_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    template_pool = serializers.IntegerField(source="template_pool.id", read_only=True)

    class Meta:
        model = WhatsAppCampaign
        fields = [
            "id",
            "name",
            "job_id",
            "template_pool_id",
            "template_pool",
            "text_template",
            "media_url",
            "throttle_per_minute",
            "delay_min_ms",
            "delay_max_ms",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "created_at", "updated_at"]

    def validate(self, attrs):
        pool_id = attrs.get("template_pool_id")
        text_template = (attrs.get("text_template") or "").strip()
        if not pool_id and not text_template:
            raise serializers.ValidationError("Provide template_pool_id or a non-empty text_template.")
        if pool_id:
            pool = WhatsAppTemplatePool.objects.get(pk=pool_id)
            job_id = attrs.get("job_id")
            if pool.job_id and job_id and pool.job_id != job_id:
                raise serializers.ValidationError("Template pool job must match campaign job.")
        return attrs

    def create(self, validated_data):
        job_id = validated_data.pop("job_id")
        pool_id = validated_data.pop("template_pool_id", None)
        job = ScrapeJob.objects.get(pk=job_id)
        pool = None
        if pool_id:
            pool = WhatsAppTemplatePool.objects.get(pk=pool_id)
        campaign = WhatsAppCampaign(job=job, template_pool=pool, **validated_data)
        campaign.full_clean()
        campaign.save()
        return campaign

    def update(self, instance, validated_data):
        pool_id = validated_data.pop("template_pool_id", None)
        if pool_id is not None:
            instance.template_pool = WhatsAppTemplatePool.objects.get(pk=pool_id)
        return super().update(instance, validated_data)


class WhatsAppCampaignRecipientSerializer(serializers.ModelSerializer):
    lead_id = serializers.IntegerField(source="lead.id", read_only=True)
    template_id = serializers.IntegerField(source="template.id", read_only=True)

    class Meta:
        model = WhatsAppCampaignRecipient
        fields = [
            "id",
            "lead_id",
            "rendered_text",
            "template_id",
            "media_url",
            "status",
            "message_id",
            "error",
            "sent_at",
        ]
        read_only_fields = fields


class WhatsAppTemplatePoolSerializer(serializers.ModelSerializer):
    job_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = WhatsAppTemplatePool
        fields = ["id", "name", "job", "job_id", "is_active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at", "job"]

    def create(self, validated_data):
        job_id = validated_data.pop("job_id", None)
        job = None
        if job_id:
            job = ScrapeJob.objects.get(pk=job_id)
        return WhatsAppTemplatePool.objects.create(job=job, **validated_data)


class WhatsAppTemplateSerializer(serializers.ModelSerializer):
    pool_id = serializers.IntegerField(write_only=True)
    pool = WhatsAppTemplatePoolSerializer(read_only=True)

    class Meta:
        model = WhatsAppTemplate
        fields = ["id", "pool", "pool_id", "text", "media_url", "weight", "is_active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at", "pool"]

    def create(self, validated_data):
        pool_id = validated_data.pop("pool_id")
        pool = WhatsAppTemplatePool.objects.get(pk=pool_id)
        return WhatsAppTemplate.objects.create(pool=pool, **validated_data)


class ChatwootContactSyncSerializer(serializers.Serializer):
    """Request payload for syncing leads into Chatwoot."""

    job_id = serializers.IntegerField(required=False, help_text="Limit sync to a specific scrape job.")
    limit = serializers.IntegerField(required=False, min_value=1, max_value=500, default=100)
    dry_run = serializers.BooleanField(default=True)
    skip_synced = serializers.BooleanField(default=True, help_text="Skip leads already marked as synced in the ledger.")
