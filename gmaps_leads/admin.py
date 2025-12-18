from django.contrib import admin
from django.utils.html import format_html
from django.utils.text import slugify
from django.utils import timezone
from django.urls import reverse, path
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponseRedirect, JsonResponse
from django.db import models
from django.db.models import Q
from django import forms
from django.contrib.admin.helpers import ActionForm
from ckeditor.widgets import CKEditorWidget
from import_export import fields, resources
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget
from .models import (
    ScrapeJob,
    GmapsLead,
    WhatsAppContact,
    LeadWebsite,
    CustomizedContact,
    ChatwootContactSync,
    ChatwootContact,
    WhatsAppCampaign,
    WhatsAppCampaignRecipient,
    WhatsAppTemplatePool,
    WhatsAppTemplate,
)
from .services import create_scrape_job, refresh_job_status, import_job_results, GmapsScraperService
from .whatsapp_campaigns import prepare_campaign_recipients
from apps.emailing.models import (
    EmailCampaign,
    EmailTemplate,
    Recipient,
    EmailAddress,
    CampaignRecipient,
)
from django.conf import settings

from .waha_test_messages import run_test_message
from .serializers import WahaTestMessageSerializer


# Custom Filters
class PhoneTypeFilter(admin.SimpleListFilter):
    """Filter leads by phone number type."""
    title = 'Phone Type'
    parameter_name = 'phone_type'

    def lookups(self, request, model_admin):
        return (
            ('whatsapp', '📱 WhatsApp (905XX)'),
            ('local', '☎️ Local Landline (902XX)'),
            ('other', '📞 Other Numbers'),
            ('none', '❌ No Phone'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'whatsapp':
            # Turkish mobile: 905XX (WhatsApp eligible)
            return queryset.filter(
                Q(phone__regex=r'^\+?905\d') |
                Q(phone__regex=r'^905\d')
            )
        elif self.value() == 'local':
            # Turkish landlines: 902XX, 903XX, 904XX
            return queryset.filter(
                Q(phone__regex=r'^\+?90[234]\d') |
                Q(phone__regex=r'^90[234]\d')
            )
        elif self.value() == 'other':
            # Has phone but not Turkish mobile or landline
            return queryset.exclude(
                phone__isnull=True
            ).exclude(
                phone=''
            ).exclude(
                Q(phone__regex=r'^\+?905\d') |
                Q(phone__regex=r'^905\d')
            ).exclude(
                Q(phone__regex=r'^\+?90[234]\d') |
                Q(phone__regex=r'^90[234]\d')
            )
        elif self.value() == 'none':
            return queryset.filter(Q(phone__isnull=True) | Q(phone=''))
        return queryset


class WebsiteFilter(admin.SimpleListFilter):
    """Filter leads by website presence."""
    title = 'Website'
    parameter_name = 'has_website'

    def lookups(self, request, model_admin):
        return (
            ('yes', '🌐 Has Website'),
            ('no', '❌ No Website'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.exclude(website__isnull=True).exclude(website='')
        elif self.value() == 'no':
            return queryset.filter(Q(website__isnull=True) | Q(website=''))
        return queryset


class HasWhatsAppContactFilter(admin.SimpleListFilter):
    """Filter leads by whether they have a WhatsApp contact extracted."""
    title = 'WhatsApp Extracted'
    parameter_name = 'has_whatsapp_contact'

    def lookups(self, request, model_admin):
        return (
            ('yes', '✅ Extracted'),
            ('no', '⏳ Not Extracted'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(whatsapp_contact__isnull=False)
        elif self.value() == 'no':
            return queryset.filter(whatsapp_contact__isnull=True)
        return queryset


class GmapsLeadInline(admin.TabularInline):
    """Inline display of leads in job admin."""
    model = GmapsLead
    extra = 0
    readonly_fields = ['title', 'category', 'phone', 'website', 'review_rating', 'review_count']
    fields = ['title', 'category', 'phone', 'website', 'review_rating', 'review_count']
    can_delete = False
    max_num = 0
    show_change_link = True
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ScrapeJob)
class ScrapeJobAdmin(admin.ModelAdmin):
    list_display = ['name', 'status_badge', 'keywords_display', 'leads_count', 'created_by', 'created_at', 'job_actions']
    list_filter = ['status', 'created_at', 'lang']
    search_fields = ['name', 'external_id']
    readonly_fields = ['external_id', 'status', 'error_message', 'leads_count', 'created_at', 'updated_at', 'completed_at', 'created_by']
    inlines = [GmapsLeadInline]
    
    fieldsets = (
        ('Job Info', {
            'fields': ('name', 'external_id', 'status', 'error_message')
        }),
        ('Search Configuration', {
            'fields': ('keywords', 'lang', 'zoom', 'depth', 'max_time')
        }),
        ('Location (Optional)', {
            'fields': ('lat', 'lon', 'radius'),
            'classes': ('collapse',)
        }),
        ('Options', {
            'fields': ('fast_mode', 'email', 'proxies'),
            'classes': ('collapse',)
        }),
        ('Results', {
            'fields': ('leads_count',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )
    
    def status_badge(self, obj):
        colors = {
            'pending': '#ffc107',
            'running': '#17a2b8',
            'completed': '#28a745',
            'failed': '#dc3545',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color, obj.status.upper()
        )
    status_badge.short_description = 'Status'
    
    def keywords_display(self, obj):
        if obj.keywords:
            return ', '.join(obj.keywords[:3]) + ('...' if len(obj.keywords) > 3 else '')
        return '-'
    keywords_display.short_description = 'Keywords'
    
    def job_actions(self, obj):
        refresh_url = reverse('admin:gmaps_leads_scrapejob_refresh', args=[obj.pk])
        import_url = reverse('admin:gmaps_leads_scrapejob_import', args=[obj.pk])
        
        buttons = f'<a class="button" href="{refresh_url}" style="margin-right: 5px;">Refresh</a>'
        if obj.status == 'completed':
            buttons += f'<a class="button" href="{import_url}">Import</a>'
        return format_html(buttons)
    job_actions.short_description = 'Actions'
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:pk>/refresh/', self.admin_site.admin_view(self.refresh_view), name='gmaps_leads_scrapejob_refresh'),
            path('<int:pk>/import/', self.admin_site.admin_view(self.import_view), name='gmaps_leads_scrapejob_import'),
            path('create-job/', self.admin_site.admin_view(self.create_job_view), name='gmaps_leads_scrapejob_create_job'),
            path('sync-from-api/', self.admin_site.admin_view(self.sync_from_api_view), name='gmaps_leads_scrapejob_sync'),
        ]
        return custom_urls + urls
    
    def sync_from_api_view(self, request):
        """Sync all jobs from the scraper API."""
        from django.utils import timezone
        try:
            from dateutil import parser as date_parser
        except ImportError:
            date_parser = None
        
        service = GmapsScraperService()
        api_jobs = service.get_all_jobs()
        
        if not api_jobs:
            messages.warning(request, 'No jobs found in scraper API (or API unreachable)')
            return HttpResponseRedirect(reverse('admin:gmaps_leads_scrapejob_changelist'))
        
        existing_ids = set(ScrapeJob.objects.values_list('external_id', flat=True))
        new_count = 0
        updated_count = 0
        
        status_map = {
            'pending': 'pending',
            'running': 'running',
            'completed': 'completed',
            'failed': 'failed',
            'done': 'completed',
            'ok': 'completed',  # API uses 'ok' for completed jobs
        }
        
        for api_job in api_jobs:
            # API returns capitalized field names
            job_id = api_job.get('ID') or api_job.get('id')
            job_name = api_job.get('Name') or api_job.get('name', 'Unnamed')
            job_status = api_job.get('Status') or api_job.get('status', 'unknown')
            job_date = api_job.get('Date') or api_job.get('date')
            job_data = api_job.get('Data') or api_job.get('data', {})
            
            if not job_id:
                continue
            
            status = status_map.get(job_status.lower(), 'pending')
            
            if job_id in existing_ids:
                # Update existing
                job = ScrapeJob.objects.get(external_id=job_id)
                if job.status != status:
                    job.status = status
                    if status == 'completed':
                        job.completed_at = timezone.now()
                    job.save()
                    updated_count += 1
            else:
                # Create new
                created_at = None
                if job_date and date_parser:
                    try:
                        created_at = date_parser.parse(job_date)
                    except:
                        pass
                
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
                if created_at:
                    ScrapeJob.objects.filter(pk=job.pk).update(created_at=created_at)
                new_count += 1
        
        messages.success(request, f'Synced from API: {new_count} new jobs, {updated_count} updated (Total in API: {len(api_jobs)})')
        return HttpResponseRedirect(reverse('admin:gmaps_leads_scrapejob_changelist'))
    
    def refresh_view(self, request, pk):
        job = get_object_or_404(ScrapeJob, pk=pk)
        try:
            refresh_job_status(job)
            messages.success(request, f'Job "{job.name}" status refreshed: {job.status}')
        except Exception as e:
            messages.error(request, f'Failed to refresh job: {e}')
        return HttpResponseRedirect(reverse('admin:gmaps_leads_scrapejob_changelist'))
    
    def import_view(self, request, pk):
        job = get_object_or_404(ScrapeJob, pk=pk)
        try:
            count = import_job_results(job)
            messages.success(request, f'Imported {count} leads from job "{job.name}"')
        except Exception as e:
            messages.error(request, f'Failed to import results: {e}')
        return HttpResponseRedirect(reverse('admin:gmaps_leads_scrapejob_change', args=[pk]))
    
    def create_job_view(self, request):
        if request.method == 'POST':
            keywords_raw = request.POST.get('keywords', '')
            keywords = [k.strip() for k in keywords_raw.split('\n') if k.strip()]
            
            if not keywords:
                messages.error(request, 'Please enter at least one keyword.')
                return render(request, 'admin/gmaps_leads/scrapejob/create_job.html')
            
            job_data = {
                'name': request.POST.get('name', 'Untitled Job'),
                'keywords': keywords,
                'lang': request.POST.get('lang', 'en'),
                'zoom': int(request.POST.get('zoom', 15)),
                'depth': int(request.POST.get('depth', 1)),
                'max_time': int(request.POST.get('max_time', 3600)),
                'email': request.POST.get('email') == 'on',
                'fast_mode': request.POST.get('fast_mode') == 'on',
            }
            
            if request.POST.get('lat'):
                job_data['lat'] = request.POST.get('lat')
            if request.POST.get('lon'):
                job_data['lon'] = request.POST.get('lon')
            if request.POST.get('radius'):
                job_data['radius'] = int(request.POST.get('radius'))
            
            try:
                job = create_scrape_job(job_data, user=request.user)
                messages.success(request, f'Job "{job.name}" created and submitted!')
                return HttpResponseRedirect(reverse('admin:gmaps_leads_scrapejob_change', args=[job.pk]))
            except Exception as e:
                messages.error(request, f'Failed to create job: {e}')
        
        return render(request, 'admin/gmaps_leads/scrapejob/create_job.html', {
            'title': 'Create Scrape Job',
            'opts': self.model._meta,
        })
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_sync_button'] = True
        extra_context['sync_url'] = reverse('admin:gmaps_leads_scrapejob_sync')
        extra_context['create_job_url'] = reverse('admin:gmaps_leads_scrapejob_create_job')
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(GmapsLead)
class GmapsLeadAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'phone_display', 'website_link', 'rating_display', 'review_count', 'city', 'job_link', 'created_at']
    list_filter = [PhoneTypeFilter, WebsiteFilter, HasWhatsAppContactFilter, 'category', 'review_rating', 'created_at', 'job']
    search_fields = ['title', 'address', 'phone', 'website', 'category']
    readonly_fields = ['created_at', 'updated_at', 'job', 'phone_type_display']
    list_per_page = 50
    actions = ['extract_whatsapp_contacts']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('job', 'input_id', 'title', 'link', 'category', 'status')
        }),
        ('Contact', {
            'fields': ('address', 'phone', 'phone_type_display', 'website', 'emails', 'plus_code')
        }),
        ('Location', {
            'fields': ('latitude', 'longitude', 'timezone', 'complete_address')
        }),
        ('Hours', {
            'fields': ('open_hours', 'popular_times'),
            'classes': ('collapse',)
        }),
        ('Reviews', {
            'fields': ('review_count', 'review_rating', 'reviews_per_rating', 'reviews_link', 'user_reviews', 'user_reviews_extended')
        }),
        ('Media', {
            'fields': ('thumbnail', 'images'),
            'classes': ('collapse',)
        }),
        ('Business Details', {
            'fields': ('descriptions', 'price_range', 'about'),
            'classes': ('collapse',)
        }),
        ('Links & Services', {
            'fields': ('reservations', 'order_online', 'menu'),
            'classes': ('collapse',)
        }),
        ('Owner & IDs', {
            'fields': ('owner', 'cid', 'data_id'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def city(self, obj):
        if obj.complete_address and isinstance(obj.complete_address, dict):
            return obj.complete_address.get('city', '-')
        return '-'
    city.short_description = 'City'
    
    def website_link(self, obj):
        if obj.website:
            return format_html('<a href="{}" target="_blank">🔗 Visit</a>', obj.website)
        return '-'
    website_link.short_description = 'Website'
    
    def rating_display(self, obj):
        if obj.review_rating:
            stars = '⭐' * int(obj.review_rating)
            return format_html('{} ({})', stars, obj.review_rating)
        return '-'
    rating_display.short_description = 'Rating'
    
    def job_link(self, obj):
        if obj.job:
            url = reverse('admin:gmaps_leads_scrapejob_change', args=[obj.job.pk])
            return format_html('<a href="{}">{}</a>', url, obj.job.name[:20])
        return '-'
    job_link.short_description = 'Job'
    
    def phone_display(self, obj):
        """Display phone with type indicator."""
        if not obj.phone:
            return format_html('<span style="color: #999;">—</span>')
        
        phone_type = obj.phone_type
        icons = {
            'whatsapp': '📱',
            'local': '☎️',
            'other': '📞',
        }
        colors = {
            'whatsapp': '#25D366',  # WhatsApp green
            'local': '#666',
            'other': '#999',
        }
        icon = icons.get(phone_type, '')
        color = colors.get(phone_type, '#000')
        
        # Check if WhatsApp contact exists
        has_wa = hasattr(obj, 'whatsapp_contact') and obj.whatsapp_contact is not None
        wa_badge = ' ✅' if has_wa else ''
        
        return format_html(
            '<span style="color: {};">{} {}{}</span>',
            color, icon, obj.phone, wa_badge
        )
    phone_display.short_description = 'Phone'
    phone_display.admin_order_field = 'phone'
    
    def phone_type_display(self, obj):
        """Display phone type in detail view."""
        phone_type = obj.phone_type
        labels = {
            'whatsapp': '📱 WhatsApp Eligible (Turkish Mobile 905XX)',
            'local': '☎️ Local Landline (Turkish 902XX/903XX/904XX)',
            'other': '📞 Other Number',
            'none': '❌ No Phone Number',
        }
        return labels.get(phone_type, phone_type)
    phone_type_display.short_description = 'Phone Type'
    
    @admin.action(description='📱 Extract WhatsApp contacts for selected leads')
    def extract_whatsapp_contacts(self, request, queryset):
        """Extract WhatsApp contacts from selected leads."""
        created = 0
        skipped = 0
        errors = 0
        
        for lead in queryset:
            if lead.phone_type != 'whatsapp':
                skipped += 1
                continue
            
            # Check if already extracted
            if hasattr(lead, 'whatsapp_contact') and lead.whatsapp_contact:
                skipped += 1
                continue
            
            try:
                WhatsAppContact.create_from_lead(lead)
                created += 1
            except Exception as e:
                errors += 1
        
        if created:
            messages.success(request, f'✅ Created {created} WhatsApp contacts')
        if skipped:
            messages.info(request, f'⏭️ Skipped {skipped} leads (not WhatsApp or already extracted)')
        if errors:
            messages.error(request, f'❌ {errors} errors occurred')


@admin.register(WhatsAppContact)
class WhatsAppContactAdmin(admin.ModelAdmin):
    """Admin for WhatsApp contacts."""
    list_display = ['business_name', 'phone_number', 'chat_id_display', 'jid_display', 'category', 'is_verified', 'lead_link', 'created_at']
    list_filter = ['is_verified', 'is_valid', 'category', 'created_at']
    search_fields = ['business_name', 'phone_number', 'chat_id', 'category']
    readonly_fields = ['lead', 'phone_number', 'chat_id', 'jid', 'business_name', 'category', 'created_at', 'updated_at']
    list_per_page = 50
    actions = ['mark_verified', 'mark_invalid', 'export_chat_ids']
    
    fieldsets = (
        ('Business Info', {
            'fields': ('lead', 'business_name', 'category')
        }),
        ('WhatsApp IDs', {
            'fields': ('phone_number', 'chat_id', 'jid', 'lid')
        }),
        ('Verification', {
            'fields': ('is_verified', 'is_valid', 'last_checked')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def chat_id_display(self, obj):
        """Display chat_id with copy button."""
        return format_html(
            '<code style="background: #e8f5e9; padding: 2px 6px; border-radius: 3px;">{}</code>',
            obj.chat_id
        )
    chat_id_display.short_description = 'Chat ID'
    
    def jid_display(self, obj):
        """Display JID with copy button."""
        return format_html(
            '<code style="background: #e3f2fd; padding: 2px 6px; border-radius: 3px;">{}</code>',
            obj.jid
        )
    jid_display.short_description = 'JID'
    
    def lead_link(self, obj):
        """Link to original lead."""
        if obj.lead:
            url = reverse('admin:gmaps_leads_gmapslead_change', args=[obj.lead.pk])
            return format_html('<a href="{}">View Lead</a>', url)
        return '-'
    lead_link.short_description = 'Lead'
    
    @admin.action(description='✅ Mark as verified')
    def mark_verified(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(is_verified=True, last_checked=timezone.now())
        messages.success(request, f'Marked {updated} contacts as verified')
    
    @admin.action(description='❌ Mark as invalid')
    def mark_invalid(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(is_valid=False, last_checked=timezone.now())
        messages.warning(request, f'Marked {updated} contacts as invalid')
    
    @admin.action(description='📋 Export Chat IDs (copy to clipboard)')
    def export_chat_ids(self, request, queryset):
        chat_ids = list(queryset.values_list('chat_id', flat=True))
        messages.info(request, f'Chat IDs ({len(chat_ids)}): {", ".join(chat_ids[:10])}{"..." if len(chat_ids) > 10 else ""}')


# ===== LEAD WEBSITE ADMIN =====

class HasEmailsFilter(admin.SimpleListFilter):
    """Filter websites by email presence."""
    title = 'Emails Found'
    parameter_name = 'has_emails'

    def lookups(self, request, model_admin):
        return (
            ('yes', '📧 Has Emails'),
            ('no', '❌ No Emails'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(emails_count__gt=0)
        elif self.value() == 'no':
            return queryset.filter(emails_count=0)
        return queryset


class AIProcessedFilter(admin.SimpleListFilter):
    """Filter websites by AI processing status."""
    title = 'AI Processed'
    parameter_name = 'ai_processed'

    def lookups(self, request, model_admin):
        return (
            ('yes', '🤖 AI Processed'),
            ('no', '⏳ Not Processed'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.exclude(ai_processed_at__isnull=True)
        elif self.value() == 'no':
            return queryset.filter(ai_processed_at__isnull=True)
        return queryset

# Action form (with admin action field)
class LeadWebsiteCampaignActionForm(ActionForm):
    campaign_name = forms.CharField(required=False, label="Campaign name")
    template = forms.ModelChoiceField(
        queryset=EmailTemplate.objects.filter(is_active=True),
        required=False,
        label="Email template (optional)"
    )
    provider_alias = forms.ChoiceField(
        required=False,
        label="Provider alias",
        choices=[],
    )
    jobs = forms.MultipleChoiceField(
        required=False,
        label="Filter by jobs",
        choices=[],
        help_text="Select one or more jobs (filters by lead__job).",
    )
    fallback_to_lead_emails = forms.BooleanField(
        required=False,
        initial=True,
        label="Fallback to lead.emails when website has none"
    )
    dry_run = forms.BooleanField(
        required=False,
        initial=False,
        label="Dry run (no records created)"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        providers = getattr(settings, "EMAIL_PROVIDERS", {}) or {}
        choices = [("", "Default from settings")]
        choices += [(alias, alias) for alias in providers.keys()]
        self.fields["provider_alias"].choices = choices
        jobs = ScrapeJob.objects.all().values_list("id", "name")
        self.fields["jobs"].choices = [(j_id, name) for j_id, name in jobs]


# Standalone page form (no admin action field)
class LeadWebsiteCampaignPageForm(forms.Form):
    campaign_name = forms.CharField(required=False, label="Campaign name")
    template = forms.ModelChoiceField(
        queryset=EmailTemplate.objects.filter(is_active=True),
        required=False,
        label="Email template (optional)"
    )
    provider_alias = forms.ChoiceField(
        required=False,
        label="Provider alias",
        choices=[],
    )
    jobs = forms.MultipleChoiceField(
        required=False,
        label="Filter by jobs",
        choices=[],
        help_text="Select one or more jobs (filters by lead__job).",
    )
    fallback_to_lead_emails = forms.BooleanField(
        required=False,
        initial=True,
        label="Fallback to lead.emails when website has none"
    )
    dry_run = forms.BooleanField(
        required=False,
        initial=False,
        label="Dry run (no records created)"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        providers = getattr(settings, "EMAIL_PROVIDERS", {}) or {}
        choices = [("", "Default from settings")]
        choices += [(alias, alias) for alias in providers.keys()]
        self.fields["provider_alias"].choices = choices
        jobs = ScrapeJob.objects.all().values_list("id", "name")
        self.fields["jobs"].choices = [(j_id, name) for j_id, name in jobs]


@admin.register(LeadWebsite)
class LeadWebsiteAdmin(admin.ModelAdmin):
    """Admin for scraped website data."""
    list_display = [
        'business_name', 'status_badge', 'emails_display', 
        'content_preview', 'social_icons', 'scraped_at', 'lead_link'
    ]
    list_filter = ['status', HasEmailsFilter, AIProcessedFilter, 'scraped_at']
    search_fields = ['lead__title', 'url', 'emails', 'page_title', 'full_text']
    readonly_fields = [
        'lead', 'url', 'final_url', 'status', 'error_message', 'http_status_code',
        'emails', 'emails_count', 'page_title', 'meta_description', 'meta_keywords',
        'headings_display', 'paragraphs_display', 'navigation_links', 'footer_content',
        'phone_numbers', 'social_links', 'full_text_preview',
        'ai_summary', 'ai_services', 'ai_keywords', 'ai_tone', 'ai_processed_at',
        'scraped_at', 'created_at', 'updated_at'
    ]
    list_per_page = 50
    actions = ['scrape_selected', 'rescrape_selected', 'export_emails', 'create_email_campaign']
    action_form = LeadWebsiteCampaignActionForm
    change_list_template = "gmaps_leads/admin/leadwebsite_change_list.html"
    
    fieldsets = (
        ('Lead Info', {
            'fields': ('lead', 'url', 'final_url', 'status', 'error_message', 'http_status_code')
        }),
        ('📧 Extracted Emails', {
            'fields': ('emails', 'emails_count'),
        }),
        ('📄 Page Metadata', {
            'fields': ('page_title', 'meta_description', 'meta_keywords'),
        }),
        ('📝 Structured Content (for AI)', {
            'fields': ('headings_display', 'paragraphs_display', 'full_text_preview'),
            'classes': ('collapse',)
        }),
        ('🔗 Navigation & Links', {
            'fields': ('navigation_links', 'footer_content'),
            'classes': ('collapse',)
        }),
        ('📱 Contact Info Found', {
            'fields': ('phone_numbers', 'social_links'),
            'classes': ('collapse',)
        }),
        ('🤖 AI Analysis (Future)', {
            'fields': ('ai_summary', 'ai_services', 'ai_keywords', 'ai_tone', 'ai_processed_at'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('scraped_at', 'created_at', 'updated_at')
        }),
    )
    
    def business_name(self, obj):
        return obj.lead.title[:50]
    business_name.short_description = 'Business'
    business_name.admin_order_field = 'lead__title'
    
    def status_badge(self, obj):
        colors = {
            'pending': '#ffc107',
            'scraping': '#17a2b8',
            'completed': '#28a745',
            'failed': '#dc3545',
            'no_content': '#6c757d',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; border-radius: 3px; font-size: 11px;">{}</span>',
            color, obj.status.upper()
        )
    status_badge.short_description = 'Status'
    
    def emails_display(self, obj):
        if obj.emails_count == 0:
            return format_html('<span style="color: #999;">—</span>')
        
        emails = obj.emails[:3] if isinstance(obj.emails, list) else []
        emails_str = ', '.join(emails)
        if obj.emails_count > 3:
            emails_str += f' (+{obj.emails_count - 3})'
        
        return format_html(
            '<span style="color: #28a745;">📧 {}</span><br><small>{}</small>',
            obj.emails_count, emails_str
        )
    emails_display.short_description = 'Emails'
    
    def content_preview(self, obj):
        if not obj.full_text:
            return format_html('<span style="color: #999;">—</span>')
        
        preview = obj.full_text[:100] + '...' if len(obj.full_text) > 100 else obj.full_text
        return format_html(
            '<span title="{}">{}</span>',
            obj.full_text[:500], preview
        )
    content_preview.short_description = 'Content'
    
    def social_icons(self, obj):
        if not obj.social_links:
            return '-'
        
        icons = {
            'facebook': '📘',
            'twitter': '🐦',
            'instagram': '📷',
            'linkedin': '💼',
            'youtube': '📺',
            'tiktok': '🎵',
            'whatsapp': '💬',
        }
        
        result = []
        for platform, url in obj.social_links.items():
            icon = icons.get(platform, '🔗')
            result.append(format_html('<a href="{}" target="_blank" title="{}">{}</a>', url, platform, icon))
        
        return format_html(' '.join([str(r) for r in result]))
    social_icons.short_description = 'Social'
    
    def lead_link(self, obj):
        if obj.lead:
            url = reverse('admin:gmaps_leads_gmapslead_change', args=[obj.lead.pk])
            return format_html('<a href="{}">View Lead</a>', url)
        return '-'
    lead_link.short_description = 'Lead'
    
    def headings_display(self, obj):
        if not obj.headings:
            return '-'
        
        result = []
        for level, texts in obj.headings.items():
            for text in texts[:5]:
                result.append(f'<{level}> {text}')
        
        return format_html('<pre style="max-height: 200px; overflow: auto;">{}</pre>', '\n'.join(result[:20]))
    headings_display.short_description = 'Headings'
    
    def paragraphs_display(self, obj):
        if not obj.paragraphs:
            return '-'
        
        preview = '\n\n'.join(obj.paragraphs[:5])
        return format_html('<pre style="max-height: 300px; overflow: auto; white-space: pre-wrap;">{}</pre>', preview)
    paragraphs_display.short_description = 'Paragraphs'
    
    def full_text_preview(self, obj):
        if not obj.full_text:
            return '-'
        
        preview = obj.full_text[:3000]
        return format_html(
            '<pre style="max-height: 400px; overflow: auto; white-space: pre-wrap;">{}</pre><br><small>Total: {} chars</small>',
            preview, obj.full_text_length
        )
    full_text_preview.short_description = 'Full Text Preview'
    
    @admin.action(description='🌐 Scrape selected websites')
    def scrape_selected(self, request, queryset):
        from .website_scraper import scrape_lead_website
        
        scraped = 0
        errors = 0
        
        for website in queryset:
            try:
                result = scrape_lead_website(website.lead, force=False)
                if result and result.status == 'completed':
                    scraped += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
        
        messages.success(request, f'Scraped {scraped} websites ({errors} errors)')
    
    @admin.action(description='🔄 Re-scrape selected websites')
    def rescrape_selected(self, request, queryset):
        from .website_scraper import scrape_lead_website
        
        scraped = 0
        errors = 0
        
        for website in queryset:
            try:
                result = scrape_lead_website(website.lead, force=True)
                if result and result.status == 'completed':
                    scraped += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
        
        messages.success(request, f'Re-scraped {scraped} websites ({errors} errors)')
    
    @admin.action(description='📧 Export emails from selected')
    def export_emails(self, request, queryset):
        all_emails = []
        for website in queryset:
            if website.emails:
                all_emails.extend(website.emails)
        
        unique_emails = sorted(set(all_emails))
        
        if unique_emails:
            messages.info(request, f'Emails ({len(unique_emails)}): {", ".join(unique_emails[:20])}{"..." if len(unique_emails) > 20 else ""}')
        else:
            messages.warning(request, 'No emails found in selected websites')

    @admin.action(description='✉️ Create email campaign from selected')
    def create_email_campaign(self, request, queryset):
        """Build an EmailCampaign + CampaignRecipients from LeadWebsite rows with optional dry run."""
        form = LeadWebsiteCampaignActionForm(request.POST or None)
        if not form.is_valid():
            messages.error(request, "Invalid form data for campaign creation.")
            return
        summary = self._build_campaign_from_queryset(request, queryset, form.cleaned_data)
        self._notify_summary(request, summary)
        return

    # Shared helpers
    def _notify_summary(self, request, summary):
        if summary["dry_run"]:
            messages.info(
                request,
                f"[Dry run] Would create campaign '{summary['campaign_name']}' with {summary['unique_count']} unique emails "
                f"({summary['prepared']} raw), skipped_no_email={summary['skipped_no_email']}, "
                f"skipped_invalid={summary['skipped_invalid']}",
            )
        else:
            messages.success(
                request,
                f"Campaign '{summary['campaign_name']}' ready with {summary['unique_count']} unique emails "
                f"(created/prepared={summary['prepared']}, skipped_no_email={summary['skipped_no_email']}, "
                f"skipped_invalid={summary['skipped_invalid']}).",
            )

    def _build_campaign_from_queryset(self, request, queryset, options, *, preview=False, sample_limit=50, force_dry_run=False):
        campaign_name = options.get("campaign_name") or f"Lead Campaign {timezone.now():%Y%m%d%H%M}"
        provider_alias = options.get("provider_alias") or getattr(settings, "EMAIL_PROVIDER", "")
        template = options.get("template")
        jobs_raw = options.get("jobs", [])
        fallback_to_lead_emails = options.get("fallback_to_lead_emails")
        dry_run = force_dry_run or options.get("dry_run")

        # jobs filter
        if jobs_raw:
            try:
                job_ids = [int(j) for j in jobs_raw]
                queryset = queryset.filter(lead__job__in=job_ids)
            except Exception:
                pass

        if queryset.count() == 0:
            return {
                "dry_run": dry_run,
                "campaign_name": campaign_name,
                "unique_count": 0,
                "prepared": 0,
                "skipped_no_email": 0,
                "skipped_invalid": 0,
                "sample": [],
            }

        unique_emails = set()
        skipped_no_email = 0
        skipped_invalid = 0
        prepared = 0
        sample = []

        def iter_emails(website):
            emails = website.emails if isinstance(website.emails, list) else []
            if not emails and fallback_to_lead_emails and website.lead and website.lead.emails:
                # lead.emails stored as CSV/text
                raw = website.lead.emails
                if raw:
                    for piece in str(raw).replace(";", ",").split(","):
                        piece = piece.strip()
                        if piece:
                            emails.append(piece)
            return emails

        # Dry run: only count prospective recipients
        if dry_run:
            for website in queryset:
                emails = iter_emails(website)
                if not emails:
                    skipped_no_email += 1
                    continue
                for email in emails:
                    norm = email.strip().lower()
                    if "@" not in norm:
                        skipped_invalid += 1
                        continue
                    unique_emails.add(norm)
                    prepared += 1
                    if preview and len(sample) < sample_limit:
                        sample.append(
                            {
                                "email": norm,
                                "business_name": website.lead.title if website.lead else "",
                                "category": website.lead.category if website.lead else "",
                                "lead_id": website.lead.id if website.lead else None,
                                "website": website.url,
                            }
                        )
            return {
                "dry_run": True,
                "campaign_name": campaign_name,
                "unique_count": len(unique_emails),
                "prepared": prepared,
                "skipped_no_email": skipped_no_email,
                "skipped_invalid": skipped_invalid,
                "sample": sample,
            }

        slug = slugify(campaign_name)[:200] or f"campaign-{timezone.now():%Y%m%d%H%M%S}"
        campaign, created = EmailCampaign.objects.get_or_create(
            slug=slug,
            defaults={
                "name": campaign_name,
                "template": template,
                "provider_alias": provider_alias,
                "status": "ready",
                "metadata": {"source": "lead_website_admin_action", "jobs": jobs_raw},
            },
        )
        if not created:
            # Update template/provider if existing slug reused
            campaign.template = template
            campaign.provider_alias = provider_alias
            campaign.metadata = {**(campaign.metadata or {}), "updated_from_admin_action": True, "jobs": jobs_raw}
            campaign.save(update_fields=["template", "provider_alias", "metadata", "updated_at"])

        for website in queryset.select_related("lead"):
            emails = iter_emails(website)
            if not emails:
                skipped_no_email += 1
                continue
            lead = website.lead
            for email in emails:
                norm = email.strip().lower()
                if "@" not in norm:
                    skipped_invalid += 1
                    continue
                if norm in unique_emails:
                    continue
                unique_emails.add(norm)
                if preview and len(sample) < sample_limit:
                    sample.append(
                        {
                            "email": norm,
                            "business_name": lead.title if lead else "",
                            "category": lead.category if lead else "",
                            "lead_id": lead.id if lead else None,
                            "website": website.url,
                        }
                    )

                recipient, _ = Recipient.objects.get_or_create(
                    company=lead.title,
                    defaults={
                        "first_name": "",
                        "last_name": "",
                        "metadata": {"lead_id": lead.id},
                    },
                )
                email_obj, _ = EmailAddress.objects.get_or_create(
                    recipient=recipient,
                    email=norm,
                    defaults={
                        "label": "website",
                        "is_primary": False,
                        "is_verified": True,
                        "is_active": True,
                        "metadata": {"lead_id": lead.id, "website_id": website.id},
                    },
                )
                context = {
                    "lead_id": lead.id,
                    "business_name": lead.title,
                    "category": lead.category,
                    "website": website.url,
                    "page_title": website.page_title,
                    "meta_description": website.meta_description,
                    "full_text": (website.full_text or "")[:4000] if website.full_text else "",
                    "location": lead.address,
                }
                CampaignRecipient.objects.get_or_create(
                    campaign=campaign,
                    email_address=email_obj,
                    defaults={
                        "recipient": recipient,
                        "status": CampaignRecipient.STATUS_PENDING,
                        "context": context,
                    },
                )
                prepared += 1

        campaign.expected_recipients = len(unique_emails)
        campaign.refresh_counters(commit=True)
        campaign.save(update_fields=["expected_recipients", "updated_at"])

        return {
            "dry_run": False,
            "campaign_name": campaign.name,
            "unique_count": len(unique_emails),
            "prepared": prepared,
            "skipped_no_email": skipped_no_email,
            "skipped_invalid": skipped_invalid,
            "sample": sample,
        }

    # Custom admin view for cleaner UI
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "create-campaign/",
                self.admin_site.admin_view(self.create_campaign_view),
                name="gmaps_leads_leadwebsite_create_campaign",
            ),
            path(
                "create-campaign/preview/",
                self.admin_site.admin_view(self.create_campaign_preview),
                name="gmaps_leads_leadwebsite_create_campaign_preview",
            ),
        ]
        return custom_urls + urls

    def create_campaign_view(self, request):
        qs = self.get_queryset(request)
        form = LeadWebsiteCampaignPageForm(request.POST or None)
        summary = None
        if request.method == "POST":
            if form.is_valid():
                summary = self._build_campaign_from_queryset(request, qs, form.cleaned_data)
                self._notify_summary(request, summary)
                if not summary["dry_run"]:
                    return redirect("admin:gmaps_leads_leadwebsite_changelist")
            else:
                messages.error(request, "Please correct the errors below.")

        context = dict(
            self.admin_site.each_context(request),
            title="Create email campaign from Lead Websites",
            form=form,
            opts=self.model._meta,
            original_queryset_count=qs.count(),
        )
        return render(request, "gmaps_leads/admin/leadwebsite_create_campaign.html", context)

    def create_campaign_preview(self, request):
        qs = self.get_queryset(request)
        form = LeadWebsiteCampaignPageForm(request.POST or None)
        if not form.is_valid():
            return JsonResponse({"errors": form.errors}, status=400)
        summary = self._build_campaign_from_queryset(
            request,
            qs,
            form.cleaned_data,
            preview=True,
            sample_limit=50,
            force_dry_run=True,
        )
        return JsonResponse(
            {
                "campaign_name": summary["campaign_name"],
                "unique_count": summary["unique_count"],
                "prepared": summary["prepared"],
                "skipped_no_email": summary["skipped_no_email"],
                "skipped_invalid": summary["skipped_invalid"],
                "sample": summary["sample"],
            }
        )

    class Media:
        """Admin-only assets to keep tabs usable on all browsers."""
        js = ('gmaps_leads/js/leadwebsite_admin.js',)
        css = {'all': ('gmaps_leads/css/leadwebsite_admin.css',)}

# Action form for campaign creation on LeadWebsite


# =============================================================================
# Email Template Admin
# =============================================================================


# No status filter for CustomizedContact




class CustomizedContactTypeFilter(admin.SimpleListFilter):
    title = 'Content Type'
    parameter_name = 'template_type'
    def lookups(self, request, model_admin):
        return (
            ('outreach', '📤 Cold Outreach'),
            ('followup', '🔄 Follow-up'),
            ('introduction', '👋 Introduction'),
            ('proposal', '📋 Business Proposal'),
            ('custom', '✏️ Custom'),
        )
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(template_type=self.value())
        return queryset


class HasTargetEmailFilter(admin.SimpleListFilter):
    """Filter by whether template has a target email."""
    title = 'Has Target Email'
    parameter_name = 'has_target_email'

    def lookups(self, request, model_admin):
        return (
            ('yes', '✅ Has Email'),
            ('no', '❌ No Email'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            # Has explicit recipient OR lead has website with emails
            return queryset.filter(
                Q(recipient_email__isnull=False) & ~Q(recipient_email='')
            ) | queryset.filter(
                lead__website_data__emails__len__gt=0
            )
        elif self.value() == 'no':
            return queryset.filter(
                Q(recipient_email__isnull=True) | Q(recipient_email='')
            ).exclude(
                lead__website_data__emails__len__gt=0
            )
        return queryset


from django import forms
from ckeditor.widgets import CKEditorWidget

class CustomizedContactAdminForm(forms.ModelForm):
    class Meta:
        model = CustomizedContact
        fields = '__all__'
        widgets = {
            'body_html': CKEditorWidget(),
        }

@admin.register(CustomizedContact)
class CustomizedContactAdmin(admin.ModelAdmin):
    form = CustomizedContactAdminForm
    raw_id_fields = ['lead']
    readonly_fields = ['body_plain_display', 'created_at', 'updated_at']
    list_display = [
        'lead', 'subject', 'template_type', 'status', 'recipient_email', 'created_at', 'updated_at'
    ]
    list_filter = [CustomizedContactTypeFilter, 'status', 'created_at', 'updated_at']
    search_fields = ['lead__title', 'subject', 'body_html', 'body_plain', 'recipient_email']

    fieldsets = (
        ('Lead & Content Info', {
            'fields': ('lead', 'name', 'template_type', 'status')
        }),
        ('Content', {
            'fields': ('subject', 'body_html', 'body_plain_display')
        }),
        ('Recipient', {
            'fields': ('recipient_email', 'recipient_name')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def body_plain_display(self, obj):
        """Show WhatsApp-friendly message generated from HTML."""
        if not obj or not obj.body_plain:
            return format_html('<span style="color:#999;">No WhatsApp message generated yet.</span>')
        return format_html(
            '<pre style="white-space: pre-wrap; background: #f8f9fa; padding: 8px; border-radius: 4px;">{}</pre>',
            obj.body_plain
        )
    body_plain_display.short_description = 'WhatsApp Message (auto-generated)'

    def created_at_display(self, obj):
        """Show formatted creation date."""
        return obj.created_at.strftime('%Y-%m-%d %H:%M')


@admin.register(ChatwootContactSync)
class ChatwootContactSyncAdmin(admin.ModelAdmin):
    list_display = ('id', 'lead', 'chatwoot_contact_id', 'chatwoot_inbox_id', 'status', 'last_synced_at', 'updated_at')
    search_fields = ('lead__title', 'source_identifier', 'chatwoot_contact_id')
    list_filter = ('status', 'chatwoot_inbox_id', 'last_synced_at')


@admin.register(ChatwootContact)
class ChatwootContactAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'email', 'phone_number', 'account_id', 'created_at', 'updated_at')
    search_fields = ('name', 'email', 'phone_number', 'identifier')
    list_filter = ('account_id',)
    readonly_fields = [f.name for f in ChatwootContact._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields


@admin.register(WhatsAppCampaign)
class WhatsAppCampaignAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "job", "status", "throttle_per_minute", "delay_min_ms", "delay_max_ms", "created_at")
    list_filter = ("status", "job")
    search_fields = ("name", "job__name")
    readonly_fields = ("status", "created_at", "updated_at", "last_error")
    actions = ("prepare_recipients", "prepare_recipients_overwrite")
    change_form_template = "admin/gmaps_leads/whatsappcampaign/change_form.html"

    class RecipientInline(admin.TabularInline):
        model = WhatsAppCampaignRecipient
        extra = 0
        fields = ("lead", "status", "template", "media_url", "message_id", "sent_at", "attempts")
        readonly_fields = fields
        show_change_link = True

    inlines = [RecipientInline]

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:object_id>/test-message/",
                self.admin_site.admin_view(self.test_message_view),
                name="gmaps_leads_whatsappcampaign_test_message",
            ),
        ]
        return custom + urls

    def test_message_view(self, request, object_id, *args, **kwargs):
        campaign = get_object_or_404(WhatsAppCampaign, pk=object_id)
        from .models import WhatsAppTemplatePool, WhatsAppTemplate

        if request.method == "GET":
            eligible_pools = WhatsAppTemplatePool.objects.filter(is_active=True).filter(
                Q(job_id=campaign.job_id) | Q(job__isnull=True)
            )
            templates = WhatsAppTemplate.objects.filter(is_active=True, pool__in=eligible_pools).select_related("pool").order_by("-id")[:200]
            context = {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "original": campaign,
                "title": "Send test WhatsApp message",
                "pools": eligible_pools.order_by("-id")[:200],
                "templates": templates,
                "campaign": campaign,
            }
            return render(request, "admin/gmaps_leads/whatsappcampaign/test_message.html", context)

        # POST: handle preview or send
        source = request.POST.get("source") or "campaign"
        payload = {"campaign_id": campaign.id}

        def _set_if_present(key: str, value):
            if value is None:
                return
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned == "":
                    return
                payload[key] = cleaned
                return
            payload[key] = value

        _set_if_present("phone", request.POST.get("phone"))
        _set_if_present("jid", request.POST.get("jid"))
        _set_if_present("chat_id", request.POST.get("chat_id"))

        lead_id_raw = (request.POST.get("lead_id") or "").strip()
        if lead_id_raw:
            try:
                payload["lead_id"] = int(lead_id_raw)
            except ValueError:
                self.message_user(request, "lead_id must be an integer.", level=messages.ERROR)
                return redirect("admin:gmaps_leads_whatsappcampaign_test_message", object_id)

        _set_if_present("business_name", request.POST.get("business_name"))
        _set_if_present("category", request.POST.get("category"))
        _set_if_present("website", request.POST.get("website"))
        _set_if_present("reply_to", request.POST.get("reply_to"))

        if request.POST.get("link_preview") in ("on", "true", "1"):
            payload["link_preview"] = True
        if request.POST.get("link_preview_high_quality") in ("on", "true", "1"):
            payload["link_preview_high_quality"] = True

        if source == "text":
            payload["text"] = request.POST.get("text") or ""
        elif source == "template":
            template_id = request.POST.get("template_id")
            if template_id:
                payload["template_id"] = int(template_id)
        elif source == "pool":
            pool_id = request.POST.get("pool_id")
            if pool_id:
                payload["pool_id"] = int(pool_id)

        if request.POST.get("submit_action") == "send":
            payload["dry_run"] = False
        else:
            payload["dry_run"] = True

        serializer = WahaTestMessageSerializer(data=payload)
        try:
            serializer.is_valid(raise_exception=True)
            result = run_test_message(serializer.validated_data)
        except Exception as exc:  # noqa: BLE001
            self.message_user(request, f"Test message failed: {exc}", level=messages.ERROR)
            return redirect("admin:gmaps_leads_whatsappcampaign_test_message", object_id)

        if result.get("dry_run"):
            rendered = result.get("rendered_text") or ""
            self.message_user(
                request,
                format_html(
                    "Preview for <code>{}</code>:<br><pre style='white-space:pre-wrap'>{}</pre>",
                    result.get("chat_id"),
                    rendered,
                ),
                level=messages.INFO,
            )
        else:
            waha = result.get("waha") or {}
            if waha.get("success"):
                msg_id = (waha.get("response") or {}).get("id") or "OK"
                self.message_user(request, f"Sent test message successfully (id: {msg_id}).", level=messages.SUCCESS)
            else:
                self.message_user(request, f"WAHA send failed: {waha}", level=messages.ERROR)

        return redirect("admin:gmaps_leads_whatsappcampaign_test_message", object_id)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Auto-generate recipients on create (keeps campaigns job-scoped and previewable).
        if not change:
            prepare_campaign_recipients(obj)

    @admin.action(description="Prepare recipients (no send)")
    def prepare_recipients(self, request, queryset):
        total_errors = 0
        for campaign in queryset:
            res = prepare_campaign_recipients(campaign, overwrite=False)
            total_errors += len(res.get("errors") or [])
        if total_errors:
            self.message_user(request, f"Prepared recipients with {total_errors} errors. Check campaign recipients for details.", level=messages.WARNING)
        else:
            self.message_user(request, "Prepared recipients successfully.")

    @admin.action(description="Prepare recipients (overwrite existing)")
    def prepare_recipients_overwrite(self, request, queryset):
        total_errors = 0
        for campaign in queryset:
            res = prepare_campaign_recipients(campaign, overwrite=True)
            total_errors += len(res.get("errors") or [])
        if total_errors:
            self.message_user(request, f"Prepared recipients (overwrite) with {total_errors} errors.", level=messages.WARNING)
        else:
            self.message_user(request, "Prepared recipients (overwrite) successfully.")


@admin.register(WhatsAppCampaignRecipient)
class WhatsAppCampaignRecipientAdmin(admin.ModelAdmin):
    list_display = ("id", "campaign", "lead", "status", "template", "media_url", "message_id", "sent_at", "attempts")
    list_filter = ("status", "campaign")
    search_fields = ("campaign__name", "lead__title", "lead__phone")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WhatsAppTemplatePool)
class WhatsAppTemplatePoolAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "job", "is_active", "created_at")
    list_filter = ("is_active", "job")
    search_fields = ("name", "job__name")
    readonly_fields = ("created_at", "updated_at")


class WhatsAppTemplateResource(resources.ModelResource):
    pool_id = fields.Field(
        column_name="pool_id",
        attribute="pool",
        widget=ForeignKeyWidget(WhatsAppTemplatePool, "id"),
    )
    pool_name = fields.Field(column_name="pool_name")

    class Meta:
        model = WhatsAppTemplate
        import_id_fields = ("id",)
        skip_unchanged = True
        report_skipped = True
        fields = ("id", "pool_id", "pool_name", "text", "media_url", "weight", "is_active")
        export_order = ("id", "pool_id", "pool_name", "text", "media_url", "weight", "is_active")

    def dehydrate_pool_name(self, obj):
        return obj.pool.name if getattr(obj, "pool", None) else ""

    def before_import_row(self, row, **kwargs):
        # Allow importing by pool_name if pool_id is not provided.
        pool_id = row.get("pool_id")
        pool_name = row.get("pool_name")
        pool_id = pool_id.strip() if isinstance(pool_id, str) else pool_id
        pool_name = pool_name.strip() if isinstance(pool_name, str) else pool_name
        if (not pool_id) and pool_name:
            pool = WhatsAppTemplatePool.objects.filter(name=pool_name).order_by("-id").first()
            if pool:
                row["pool_id"] = str(pool.id)


@admin.register(WhatsAppTemplate)
class WhatsAppTemplateAdmin(ImportExportModelAdmin):
    resource_class = WhatsAppTemplateResource
    list_display = ("id", "pool", "weight", "is_active", "created_at")
    list_filter = ("is_active", "pool")
    search_fields = ("pool__name", "text")
    readonly_fields = ("created_at", "updated_at")
