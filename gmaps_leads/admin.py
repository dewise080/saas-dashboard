from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse, path
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.db import models
from django.db.models import Q
from django import forms
from ckeditor.widgets import CKEditorWidget
from .models import ScrapeJob, GmapsLead, WhatsAppContact, LeadWebsite, EmailTemplate
from .services import create_scrape_job, refresh_job_status, import_job_results, GmapsScraperService


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
    actions = ['scrape_selected', 'rescrape_selected', 'export_emails']
    
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


# =============================================================================
# Email Template Admin
# =============================================================================

class EmailTemplateStatusFilter(admin.SimpleListFilter):
    """Filter email templates by status."""
    title = 'Status'
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return (
            ('draft', '📝 Draft'),
            ('generating', '⏳ AI Generating'),
            ('ready', '✅ Ready to Send'),
            ('approved', '👍 Approved'),
            ('sent', '📧 Sent'),
            ('failed', '❌ Failed'),
            ('rejected', '🚫 Rejected'),
        )

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(status=self.value())
        return queryset


class EmailTemplateTypeFilter(admin.SimpleListFilter):
    """Filter email templates by type."""
    title = 'Template Type'
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


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = [
        'lead_name', 'subject_preview', 'template_type_badge', 'status_badge',
        'target_email_display', 'is_personalized_badge', 'created_at_display'
    ]
    list_filter = [
        EmailTemplateStatusFilter, EmailTemplateTypeFilter, 
        HasTargetEmailFilter, 'is_personalized', 'created_at'
    ]
    search_fields = ['lead__title', 'subject', 'body_html', 'recipient_email']
    raw_id_fields = ['lead', 'created_by']
    readonly_fields = [
        'created_at', 'updated_at', 'sent_at', 'opened_at', 'clicked_at',
        'target_email', 'lead_context_preview'
    ]
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Lead & Template Info', {
            'fields': ('lead', 'name', 'template_type', 'lead_context_preview')
        }),
        ('Email Content', {
            'fields': ('subject', 'body_html', 'body_plain', 'body_html_preview', 'body_plain_preview')
        }),
        ('Recipient', {
            'fields': ('recipient_email', 'recipient_name', 'target_email')
        }),
        ('Sender', {
            'fields': ('sender_name', 'sender_email', 'reply_to'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('status', 'status_message')
        }),
        ('AI Generation Metadata', {
            'fields': ('ai_model', 'ai_prompt_used', 'ai_generation_time', 'ai_tokens_used'),
            'classes': ('collapse',)
        }),
        ('Personalization', {
            'fields': ('is_personalized', 'personalization_score', 'variables'),
            'classes': ('collapse',)
        }),
        ('Tracking', {
            'fields': ('sent_at', 'opened_at', 'clicked_at'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = [
        'mark_as_ready', 'mark_as_approved', 'mark_as_draft', 
        'mark_as_rejected', 'export_for_sending'
    ]

    def target_email_display(self, obj):
        return obj.target_email or obj.recipient_email or "-"
    target_email_display.short_description = "Target Email"

    def body_html_preview(self, obj):
        if obj.body_html:
            return format_html('<div style="max-width:600px;white-space:pre-wrap;">{}</div>', obj.body_html[:400])
        return "-"
    body_html_preview.short_description = "HTML Preview"

    def body_plain_preview(self, obj):
        if obj.body_plain:
            text = (obj.body_plain[:400] + '...') if len(obj.body_plain) > 400 else obj.body_plain
            return format_html('<pre style="max-width:600px;white-space:pre-wrap;">{}</pre>', text)
        return "-"
    body_plain_preview.short_description = "Plain Preview"

    formfield_overrides = {
        models.TextField: {'widget': CKEditorWidget(config_name='default')},
    }
    
    def lead_name(self, obj):
        """Show lead business name with link."""
        url = reverse('admin:gmaps_leads_gmapslead_change', args=[obj.lead.pk])
        return format_html('<a href="{}">{}</a>', url, obj.lead.title[:40])
    lead_name.short_description = 'Business'
    lead_name.admin_order_field = 'lead__title'
    
    def subject_preview(self, obj):
        """Show truncated subject."""
        return obj.subject[:50] + ('...' if len(obj.subject) > 50 else '')
    subject_preview.short_description = 'Subject'
    
    def template_type_badge(self, obj):
        """Show template type as badge."""
        icons = {
            'outreach': '📤',
            'followup': '🔄',
            'introduction': '👋',
            'proposal': '📋',
            'custom': '✏️',
        }
        icon = icons.get(obj.template_type, '📧')
        return format_html('{} {}', icon, obj.get_template_type_display())
    template_type_badge.short_description = 'Type'
    
    def status_badge(self, obj):
        """Show status with colored badge."""
        colors = {
            'draft': '#6c757d',
            'generating': '#ffc107',
            'ready': '#17a2b8',
            'approved': '#28a745',
            'sent': '#007bff',
            'failed': '#dc3545',
            'rejected': '#343a40',
        }
        icons = {
            'draft': '📝',
            'generating': '⏳',
            'ready': '✅',
            'approved': '👍',
            'sent': '📧',
            'failed': '❌',
            'rejected': '🚫',
        }
        color = colors.get(obj.status, '#6c757d')
        icon = icons.get(obj.status, '📋')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; border-radius: 3px;">{} {}</span>',
            color, icon, obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    status_badge.admin_order_field = 'status'
    
    def target_email_display(self, obj):
        """Show target email."""
        email = obj.target_email
        if email:
            return format_html('<a href="mailto:{}">{}</a>', email, email)
        return format_html('<span style="color: #999;">No email</span>')
    target_email_display.short_description = 'Target Email'
    
    def is_personalized_badge(self, obj):
        """Show personalization status."""
        if obj.is_personalized:
            score = f' ({obj.personalization_score:.0%})' if obj.personalization_score else ''
            return format_html('<span style="color: green;">✓ AI{}</span>', score)
        return format_html('<span style="color: #999;">–</span>')
    is_personalized_badge.short_description = 'Personalized'
    
    def created_at_display(self, obj):
        """Show formatted creation date."""
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = 'Created'
    created_at_display.admin_order_field = 'created_at'
    
    def lead_context_preview(self, obj):
        """Show lead context that would be sent to AI."""
        if not obj.lead:
            return '-'
        
        context_parts = [
            f"<strong>Business:</strong> {obj.lead.title}",
            f"<strong>Category:</strong> {obj.lead.category or 'N/A'}",
            f"<strong>Phone:</strong> {obj.lead.phone or 'N/A'}",
            f"<strong>Website:</strong> {obj.lead.website or 'N/A'}",
        ]
        
        # Add website data if available
        try:
            if hasattr(obj.lead, 'website_data') and obj.lead.website_data:
                wd = obj.lead.website_data
                if wd.emails:
                    context_parts.append(f"<strong>Emails:</strong> {', '.join(wd.emails)}")
                if wd.ai_services:
                    context_parts.append(f"<strong>Services:</strong> {', '.join(wd.ai_services[:5])}")
        except:
            pass
        
        return format_html('<br>'.join(context_parts))
    lead_context_preview.short_description = 'Lead Context'
    
    # Actions
    @admin.action(description='✅ Mark as Ready to Send')
    def mark_as_ready(self, request, queryset):
        from .signals import email_template_ready
        updated = 0
        for template in queryset:
            if template.status != 'ready':
                template.status = 'ready'
                template.save()
                email_template_ready.send(sender=self.__class__, instance=template)
                updated += 1
        messages.success(request, f'Marked {updated} templates as ready (signals emitted)')
    
    @admin.action(description='👍 Mark as Approved')
    def mark_as_approved(self, request, queryset):
        from .signals import email_template_approved
        updated = 0
        for template in queryset:
            if template.status != 'approved':
                template.status = 'approved'
                template.save()
                email_template_approved.send(sender=self.__class__, instance=template)
                updated += 1
        messages.success(request, f'Approved {updated} templates (signals emitted)')
    
    @admin.action(description='📝 Mark as Draft')
    def mark_as_draft(self, request, queryset):
        updated = queryset.update(status='draft')
        messages.success(request, f'Marked {updated} templates as draft')
    
    @admin.action(description='🚫 Mark as Rejected')
    def mark_as_rejected(self, request, queryset):
        updated = queryset.update(status='rejected')
        messages.success(request, f'Rejected {updated} templates')
    
    @admin.action(description='📋 Export for Sending (CSV)')
    def export_for_sending(self, request, queryset):
        import csv
        from django.http import HttpResponse
        
        # Only export ready/approved templates with target emails
        templates = queryset.filter(status__in=['ready', 'approved'])
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="email_templates_export.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Lead ID', 'Business Name', 'Target Email', 'Subject', 
            'Body HTML', 'Body Plain', 'Status', 'Template Type'
        ])
        
        exported = 0
        for template in templates:
            target = template.target_email
            if target:
                writer.writerow([
                    template.lead_id,
                    template.lead.title,
                    target,
                    template.subject,
                    template.body_html,
                    template.body_plain or '',
                    template.status,
                    template.template_type,
                ])
                exported += 1
        
        if exported == 0:
            messages.warning(request, 'No templates with target emails to export')
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/admin/'))
        
        return response
