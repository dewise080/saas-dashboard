from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import models
from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
import csv
import json
import logging
import random
import time

from .models import (
    ScrapeJob,
    GmapsLead,
    CustomizedContact,
    WhatsAppContact,
    ChatwootContactSync,
    WhatsAppCampaign,
    WhatsAppCampaignRecipient,
    WhatsAppTemplatePool,
    WhatsAppTemplate,
)
from .whatsapp_campaigns import prepare_campaign_recipients
from .whatsapp_campaigns import compose_whatsapp_text
from apps.emailing.models import EmailCampaign, CampaignRecipient
from .serializers import (
    ScrapeJobSerializer, ScrapeJobCreateSerializer,
    GmapsLeadSerializer, GmapsLeadListSerializer,
    LeadContextSerializer, 
    CustomizedContactSerializer, CustomizedContactListSerializer,
    CustomizedContactCreateSerializer,
    AICampaignSerializer,
    AICampaignRecipientStatusSerializer,
    AICampaignRecipientContextSerializer,
    AICampaignRecipientContentSerializer,
    AICampaignRecipientListSerializer,
    WahaContactSyncSerializer,
    ChatwootContactSyncSerializer,
    WahaSendMessageSerializer,
    WahaTestMessageSerializer,
    WhatsAppCampaignSerializer,
    WhatsAppCampaignRecipientSerializer,
    WhatsAppTemplatePoolSerializer,
    WhatsAppTemplateSerializer,
)
from .services import (
    create_scrape_job, refresh_job_status, import_job_results,
    GmapsScraperService
)
from .signals import email_template_ready, email_template_approved
from .waha_client import WahaClient, WahaClientError
from .waha_test_messages import run_test_message
from .models import AIMemory
from .serializers import AIMemorySerializer
from magic_notifier.services import create_notification
from magic_notifier.recipients import get_email, get_phone
from magic_notifier.emailer import Emailer
from magic_notifier.whatsapper import Whatsapper
from apps.emailing.models import EmailCampaign, CampaignRecipient
from django.template.loader import render_to_string
import re


# Simple API for AI Assistant Memory
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

class AIMemoryListCreateAPIView(APIView):
    """GET: List all memories. POST: Create a new memory (note or progress)."""
    permission_classes = [AllowAny]
    serializer_class = AIMemorySerializer

    @extend_schema(
        operation_id="ai_memory_list",
        summary="List AI memories",
        responses=AIMemorySerializer(many=True),
        tags=["AI Assistant Memory"],
    )
    def get(self, request):
        memories = AIMemory.objects.all().order_by('-created_at')
        serializer = AIMemorySerializer(memories, many=True)
        return Response(serializer.data)

    @extend_schema(
        operation_id="ai_memory_create",
        summary="Create AI memory",
        request=AIMemorySerializer,
        responses=AIMemorySerializer,
        tags=["AI Assistant Memory"],
    )
    def post(self, request):
        data = request.data
        # Accept both top-level and nested 'params' dict
        if 'params' in data and isinstance(data['params'], dict):
            data = data['params']
        serializer = AIMemorySerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
from apps.emailing.chatwoot import ChatwootClient

logger = logging.getLogger(__name__)


# =============================================================================
# API ViewSets (DRF)
# =============================================================================

@extend_schema_view(
    list=extend_schema(operation_id="jobs_list", summary="List jobs"),
    create=extend_schema(operation_id="jobs_create", summary="Create job"),
    retrieve=extend_schema(operation_id="jobs_retrieve", summary="Retrieve job"),
    destroy=extend_schema(operation_id="jobs_destroy", summary="Delete job"),
)
class ScrapeJobViewSet(viewsets.ModelViewSet):
    """API ViewSet for ScrapeJob."""
    queryset = ScrapeJob.objects.all()
    serializer_class = ScrapeJobSerializer
    permission_classes = [AllowAny]
    lookup_field = "pk"
    lookup_url_kwarg = "pk"
    
    def get_queryset(self):
        """Filter jobs by current user."""
        return ScrapeJob.objects.filter(created_by=self.request.user)
    
    def create(self, request):
        """Create a new scrape job."""
        serializer = ScrapeJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            job = create_scrape_job(serializer.validated_data, user=request.user)
            return Response(
                ScrapeJobSerializer(job).data,
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            logger.error(f"Failed to create scrape job: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(exclude=True)
    @action(detail=True, methods=['post'])
    def refresh(self, request, pk=None):
        """Refresh job status from API."""
        job = self.get_object()
        job = refresh_job_status(job)
        return Response(ScrapeJobSerializer(job).data)
    
    @extend_schema(exclude=True)
    @action(detail=True, methods=['post'])
    def import_results(self, request, pk=None):
        """Import job results from API."""
        job = self.get_object()
        
        try:
            count = import_job_results(job)
            return Response({
                'message': f'Imported {count} leads',
                'leads_count': count
            })
        except Exception as e:
            logger.error(f"Failed to import results: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @extend_schema(operation_id="jobs_leads_retrieve", summary="List leads for a job")
    @action(detail=True, methods=['get'])
    def leads(self, request, pk=None):
        """Get leads for this job."""
        job = self.get_object()
        leads = job.leads.all()
        serializer = GmapsLeadListSerializer(leads, many=True)
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(
        operation_id='leads_list',
        summary='List leads (limited)',
        parameters=[
            OpenApiParameter(name='limit', type=OpenApiTypes.INT, description='Max results (default 50, max 200)'),
            OpenApiParameter(name='job', type=OpenApiTypes.INT, description='Filter by job ID'),
            OpenApiParameter(name='category', type=OpenApiTypes.STR, description='Filter by category'),
            OpenApiParameter(name='min_rating', type=OpenApiTypes.NUMBER, description='Filter by minimum rating'),
        ],
    ),
    retrieve=extend_schema(operation_id='leads_retrieve', summary='Retrieve lead'),
)
class GmapsLeadViewSet(viewsets.ReadOnlyModelViewSet):
    """API ViewSet for GmapsLead (read-only)."""
    queryset = GmapsLead.objects.all()
    serializer_class = GmapsLeadSerializer
    permission_classes = [AllowAny]
    
    def get_queryset(self):
        """Filter leads by user's jobs and admin-style filters."""
        qs = GmapsLead.objects.all()
        req = self.request
        if req.user.is_authenticated:
            qs = qs.filter(job__created_by=req.user)

        # Filter by job
        job_id = req.query_params.get('job')
        if job_id:
            qs = qs.filter(job_id=job_id)

        # Filter by category
        category = req.query_params.get('category')
        if category:
            qs = qs.filter(category__icontains=category)

        # Filter by min rating
        min_rating = req.query_params.get('min_rating')
        if min_rating:
            qs = qs.filter(review_rating__gte=float(min_rating))

        # Filter by phone type
        phone_type = req.query_params.get('phone_type')
        if phone_type in {'whatsapp', 'local', 'other', 'none'}:
            qs = [lead for lead in qs if getattr(lead, 'phone_type', None) == phone_type]

        # Filter by website presence
        has_website = req.query_params.get('has_website')
        if has_website == 'yes':
            qs = qs.exclude(website__isnull=True).exclude(website='')
        elif has_website == 'no':
            qs = qs.filter(Q(website__isnull=True) | Q(website=''))

        # Filter by WhatsApp contact extraction
        has_wa = req.query_params.get('has_whatsapp_contact')
        if has_wa == 'yes':
            qs = qs.filter(whatsapp_contact__isnull=False)
        elif has_wa == 'no':
            qs = qs.filter(whatsapp_contact__isnull=True)

        # Search (title, address, phone, website, category)
        search = req.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(address__icontains=search) |
                Q(phone__icontains=search) |
                Q(website__icontains=search) |
                Q(category__icontains=search)
            )

        limit = req.query_params.get('limit')
        try:
            limit_val = min(int(limit), 200) if limit else 50
        except Exception:
            limit_val = 50
        # If qs is a list (from phone_type filter), slice directly
        if isinstance(qs, list):
            return qs[:limit_val]
        return qs[:limit_val]
    
    def get_serializer_class(self):
        if self.action == 'list':
            return GmapsLeadListSerializer
        return GmapsLeadSerializer


# =============================================================================
# Template Views (Admin UI)
# =============================================================================

@login_required
def job_list(request):
    """List all scrape jobs."""
    jobs = ScrapeJob.objects.filter(created_by=request.user).order_by('-created_at')
    return render(request, 'gmaps_leads/job_list.html', {'jobs': jobs})


@login_required
def job_detail(request, pk):
    """View job details and leads."""
    job = get_object_or_404(ScrapeJob, pk=pk, created_by=request.user)
    leads = job.leads.all()[:100]  # Limit for performance
    return render(request, 'gmaps_leads/job_detail.html', {
        'job': job,
        'leads': leads,
        'total_leads': job.leads.count()
    })


@login_required
def job_create(request):
    """Create a new scrape job."""
    if request.method == 'POST':
        # Parse form data
        keywords_raw = request.POST.get('keywords', '')
        keywords = [k.strip() for k in keywords_raw.split('\n') if k.strip()]
        
        if not keywords:
            messages.error(request, 'Please enter at least one keyword.')
            return render(request, 'gmaps_leads/job_create.html')
        
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
        
        # Optional location
        if request.POST.get('lat'):
            job_data['lat'] = request.POST.get('lat')
        if request.POST.get('lon'):
            job_data['lon'] = request.POST.get('lon')
        if request.POST.get('radius'):
            job_data['radius'] = int(request.POST.get('radius'))
        
        try:
            job = create_scrape_job(job_data, user=request.user)
            messages.success(request, f'Job "{job.name}" created successfully!')
            return redirect('gmaps_leads:job_detail', pk=job.pk)
        except Exception as e:
            logger.error(f"Failed to create job: {e}")
            messages.error(request, f'Failed to create job: {e}')
    
    return render(request, 'gmaps_leads/job_create.html')


@login_required
@require_http_methods(['POST'])
def job_refresh(request, pk):
    """Refresh job status."""
    job = get_object_or_404(ScrapeJob, pk=pk, created_by=request.user)
    job = refresh_job_status(job)
    messages.info(request, f'Job status updated: {job.status}')
    return redirect('gmaps_leads:job_detail', pk=pk)


@login_required
@require_http_methods(['POST'])
def job_import(request, pk):
    """Import job results."""
    job = get_object_or_404(ScrapeJob, pk=pk, created_by=request.user)
    
    try:
        count = import_job_results(job)
        messages.success(request, f'Imported {count} leads!')
    except Exception as e:
        logger.error(f"Failed to import results: {e}")
        messages.error(request, f'Failed to import results: {e}')
    
    return redirect('gmaps_leads:job_detail', pk=pk)


@login_required
def leads_list(request):
    """List all leads."""
    leads = GmapsLead.objects.filter(job__created_by=request.user).order_by('-created_at')
    
    # Filters
    category = request.GET.get('category')
    if category:
        leads = leads.filter(category__icontains=category)
    
    min_rating = request.GET.get('min_rating')
    if min_rating:
        leads = leads.filter(review_rating__gte=float(min_rating))
    
    job_id = request.GET.get('job')
    if job_id:
        leads = leads.filter(job_id=job_id)
    
    # Get categories for filter dropdown
    categories = GmapsLead.objects.filter(
        job__created_by=request.user
    ).values_list('category', flat=True).distinct()
    
    return render(request, 'gmaps_leads/leads_list.html', {
        'leads': leads[:500],
        'total_count': leads.count(),
        'categories': [c for c in categories if c],
    })


@login_required
def lead_detail(request, pk):
    """View lead details."""
    lead = get_object_or_404(GmapsLead, pk=pk, job__created_by=request.user)
    return render(request, 'gmaps_leads/lead_detail.html', {'lead': lead})


@login_required
def export_leads_csv(request):
    """Export leads to CSV."""
    leads = GmapsLead.objects.filter(job__created_by=request.user)
    
    # Apply same filters as list view
    job_id = request.GET.get('job')
    if job_id:
        leads = leads.filter(job_id=job_id)
    
    category = request.GET.get('category')
    if category:
        leads = leads.filter(category__icontains=category)
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="gmaps_leads.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Title', 'Category', 'Address', 'Phone', 'Website', 'Email',
        'Rating', 'Reviews', 'City', 'Country', 'Latitude', 'Longitude'
    ])
    
    for lead in leads:
        city = lead.complete_address.get('city', '') if lead.complete_address else ''
        country = lead.complete_address.get('country', '') if lead.complete_address else ''
        
        writer.writerow([
            lead.title,
            lead.category or '',
            lead.address or '',
            lead.phone or '',
            lead.website or '',
            lead.emails or '',
            lead.review_rating or '',
            lead.review_count,
            city,
            country,
            lead.latitude or '',
            lead.longitude or '',
        ])
    
    return response


@login_required
def notify_email_dashboard(request):
    """Email campaign recipient review/send."""
    limit = min(int(request.GET.get("limit", 200) or 200), 500)
    email_campaign_id = request.GET.get("email_campaign")
    email_theme = request.GET.get("email_theme", "dark")

    email_campaigns = EmailCampaign.objects.all().only("id", "name", "status").order_by("-created_at")[:20]
    if not email_campaign_id and email_campaigns:
        email_campaign_id = email_campaigns[0].id

    email_recipients = []
    if email_campaign_id:
        email_recipients = (
            CampaignRecipient.objects.select_related("campaign", "email_address", "recipient")
            .filter(
                campaign_id=email_campaign_id,
                status__in=[
                    CampaignRecipient.STATUS_READY,
                    CampaignRecipient.STATUS_RENDERED,
                    CampaignRecipient.STATUS_PENDING,
                ],
            )
            .order_by("id")[:limit]
        )

    return render(
        request,
        "gmaps_leads/notify_email_dashboard.html",
        {
            "email_campaigns": email_campaigns,
            "email_recipients": email_recipients,
            "selected_email_campaign": int(email_campaign_id) if email_campaign_id else None,
            "limit": limit,
            "email_theme": email_theme,
        },
    )


@login_required
def notify_email_preview(request, recipient_id: int):
    """Render the styled email for a single campaign recipient."""
    recipient = get_object_or_404(
        CampaignRecipient.objects.select_related("campaign", "email_address", "recipient"),
        pk=recipient_id,
    )
    def extract_whatsapp_links(text: str):
        """Return unique wa.me links in order, ignoring regex errors."""
        if not text:
            return []
        try:
            pattern = re.compile(r"https?://wa\\.me/[\\w/?=&%+\\.\\-]+", re.IGNORECASE)
            seen = set()
            links = []
            for match in pattern.findall(text):
                if match not in seen:
                    seen.add(match)
                    links.append(match)
            return links
        except re.error:
            return []

    theme = request.GET.get("theme", "dark")
    email_base_template = "base_notifier/email_dark.html" if theme == "dark" else "base_notifier/email.html"
    whatsapp_links = extract_whatsapp_links(recipient.body_html or recipient.body_text or "")
    context = {
        "recipient_obj": recipient.recipient,
        "email_address": recipient.email_address.email if recipient.email_address else "",
        "subject": recipient.subject or (recipient.campaign.name if recipient.campaign else ""),
        "body_html": recipient.body_html or "",
        "body_text": recipient.body_text or "",
        "product_name": getattr(recipient.campaign, "name", ""),
        "email_base_template": email_base_template,
        "email_theme": theme,
        "whatsapp_links": whatsapp_links,
    }
    html = render_to_string("notifier/campaign/email.html", context)
    return HttpResponse(html)


@login_required
def notify_whatsapp_dashboard(request):
    """WhatsApp campaign recipient review/send."""
    limit = min(int(request.GET.get("limit", 200) or 200), 500)
    wa_campaign_id = request.GET.get("wa_campaign")

    wa_campaigns = WhatsAppCampaign.objects.all().only("id", "name", "status").order_by("-created_at")[:20]
    if not wa_campaign_id and wa_campaigns:
        wa_campaign_id = wa_campaigns[0].id

    wa_recipients = []
    if wa_campaign_id:
        wa_recipients = (
            WhatsAppCampaignRecipient.objects.select_related("campaign", "lead", "whatsapp_contact")
            .filter(campaign_id=wa_campaign_id, status="pending")
            .order_by("id")[:limit]
        )

    return render(
        request,
        "gmaps_leads/notify_whatsapp_dashboard.html",
        {
            "wa_campaigns": wa_campaigns,
            "wa_recipients": wa_recipients,
            "selected_wa_campaign": int(wa_campaign_id) if wa_campaign_id else None,
            "limit": limit,
        },
    )


# =============================================================================
# AI Integration API Views (OpenAPI 3.1)
# =============================================================================

# =============================================================================
# Lead Category Stats APIView (for GPT onboarding)
# =============================================================================

from django.db.models import Count, Q

class LeadCategoryStatsAPIView(APIView):
    """
    API endpoint to provide available categories and lead stats for GPT onboarding.
    Returns a list of categories, number of leads per category, number with WhatsApp, and number with website.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id='getLeadCategoryStats',
        summary='Get lead category stats (GPT onboarding)',
        description='Returns available categories, number of leads per category, number with WhatsApp, and number with website. This endpoint is intended as the first call for AI agents (GPT) to understand the available data.',
        responses={
            200: OpenApiTypes.OBJECT,
        },
        tags=['AI Email Generation', 'Stats']
    )
    def get(self, request):
        """Get stats for all categories and lead counts."""
        # Use Python-side aggregation so we can rely on the model's phone_type
        # property (not a DB column) without complex SQL annotations.
        stats = {}
        for lead in GmapsLead.objects.all():
            category = lead.category or 'Uncategorized'
            bucket = stats.setdefault(category, {
                'category': category,
                'total_leads': 0,
                'leads_with_whatsapp': 0,
                'leads_with_website': 0,
                'leads_with_ready_customized_contact': 0,
            })
            bucket['total_leads'] += 1
            if lead.phone_type == 'whatsapp':
                bucket['leads_with_whatsapp'] += 1
            if lead.website:
                bucket['leads_with_website'] += 1
            # Count ready customized contacts for this lead
            ready_count = 0
            for contact in getattr(lead, 'customized_contacts', []).all():
                if getattr(contact, 'is_ready', False):
                    ready_count += 1
            bucket['leads_with_ready_customized_contact'] += ready_count

        data = sorted(stats.values(), key=lambda r: r['total_leads'], reverse=True)
        return Response({'categories': data})

class LeadContextAPIView(APIView):
    """
    API endpoint for AI to fetch concise lead context for personalization.
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        operation_id='getLeadContext',
        summary='Get lead context for AI email generation',
        description='Returns key business info, scraped website data, WhatsApp contacts, and reviews for the specified lead.',
        parameters=[
            OpenApiParameter(
                name='lead_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description='The ID of the lead to fetch context for'
            )
        ],
        responses={
            200: LeadContextSerializer,
            404: OpenApiTypes.OBJECT,
        },
        tags=['AI Email Generation']
    )
    def get(self, request, lead_id):
        """Get lead context for AI email generation."""
        qs = GmapsLead.objects.select_related('website_data')
        if request.user.is_authenticated:
            qs = qs.filter(job__created_by=request.user)
        lead = get_object_or_404(qs, pk=lead_id)
        serializer = LeadContextSerializer(lead)
        return Response(serializer.data)


class LeadEmailTemplateAPIView(APIView):
    """
    Per-lead endpoint for listing and creating customized contacts.
    Use this endpoint to manage contacts for a specific lead (nested resource).
    Example: /api/leads/{lead_id}/customized-contact/
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        operation_id='getLeadCustomizedContacts',
        summary='List customized contacts for a lead',
        description='Returns all customized contacts created for this lead. Use this endpoint for per-lead (nested) access. For a global list, use /api/customized-contacts/.',
        parameters=[
            OpenApiParameter(
                name='lead_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description='The ID of the lead'
            )
        ],
        responses={200: CustomizedContactListSerializer(many=True)},
        tags=['AI Email Generation']
    )
    def get(self, request, lead_id):
        """List email templates for a lead."""
        qs = GmapsLead.objects.all()
        if request.user.is_authenticated:
            qs = qs.filter(job__created_by=request.user)
        lead = get_object_or_404(qs, pk=lead_id)
        templates = lead.customizedcontact_set.all()
        serializer = CustomizedContactListSerializer(templates, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        operation_id='createLeadCustomizedContact',
        summary='Create customized contact for a lead (AI endpoint)',
        description='Creates a new customized contact for the specified lead. Use this endpoint for per-lead (nested) creation. For global creation, use /api/customized-contacts/. Intended for AI agents to submit generated content; set mark_ready=true to flag for human review.',
        parameters=[
            OpenApiParameter(
                name='lead_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description='The ID of the lead to create template for'
            )
        ],
        request=CustomizedContactCreateSerializer,
        responses={
            201: CustomizedContactSerializer,
            400: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                'AI Generated Email',
                value={
                    'subject': 'Partnership opportunity for {{business_name}}',
                    'body_html': '<h1>Hello {{recipient_name}},</h1><p>I noticed your business...</p>',
                    'template_type': 'outreach',
                    'mark_ready': True,
                },
                request_only=True,
            )
        ],
        tags=['AI Email Generation']
    )
    def post(self, request, lead_id):
        """Create email template for a lead."""
        qs = GmapsLead.objects.all()
        if request.user.is_authenticated:
            qs = qs.filter(job__created_by=request.user)
        lead = get_object_or_404(qs, pk=lead_id)
        
        serializer = CustomizedContactCreateSerializer(
            data=request.data,
            context={'lead': lead, 'request': request}
        )
        
        if serializer.is_valid():
            extra = {}
            if request.user.is_authenticated:
                extra["created_by"] = request.user
            template = serializer.save(**extra)
            return Response(
                CustomizedContactSerializer(template).data,
                status=status.HTTP_201_CREATED
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class EmailTemplateAPIView(APIView):
    """
    API endpoint for managing individual email templates.
    
    GET /api/email-templates/{id}/
    PUT /api/email-templates/{id}/
    DELETE /api/email-templates/{id}/
    """
    permission_classes = [AllowAny]
    
    def get_template(self, request, template_id):
        """Get template with permission check."""
        qs = CustomizedContact.objects.all()
        if request.user.is_authenticated:
            qs = qs.filter(lead__job__created_by=request.user)
        return get_object_or_404(qs, pk=template_id)
    
    @extend_schema(
        operation_id='getCustomizedContact',
        summary='Get customized contact details',
        responses={200: CustomizedContactSerializer},
        tags=['Customized Contacts']
    )
    def get(self, request, template_id):
        """Get email template."""
        template = self.get_template(request, template_id)
        serializer = CustomizedContactSerializer(template)
        return Response(serializer.data)
    
    @extend_schema(
        operation_id='updateCustomizedContact',
        summary='Update customized contact',
        request=CustomizedContactCreateSerializer,
        responses={200: CustomizedContactSerializer},
        tags=['Customized Contacts']
    )
    def put(self, request, template_id):
        """Update email template."""
        template = self.get_template(request, template_id)
        serializer = CustomizedContactCreateSerializer(
            template,
            data=request.data,
            partial=True,
            context={'lead': template.lead, 'request': request}
        )
        
        if serializer.is_valid():
            template = serializer.save()
            return Response(CustomizedContactSerializer(template).data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        operation_id='deleteCustomizedContact',
        summary='Delete customized contact',
        responses={204: None},
        tags=['Customized Contacts']
    )
    def delete(self, request, template_id):
        """Delete email template."""
        template = self.get_template(request, template_id)
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


from rest_framework.generics import GenericAPIView
from .serializers import CustomizedContactSerializer
from .status_update_serializer import EmailTemplateStatusUpdateSerializer

class EmailTemplateStatusAPIView(GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = EmailTemplateStatusUpdateSerializer

    @extend_schema(
        operation_id='updateCustomizedContactStatus',
        summary='Update customized contact status',
        description='Updates a customized contact status (draft, ready, approved, rejected) and emits signals for ready/approved states.',
        request=EmailTemplateStatusUpdateSerializer,
        responses={200: CustomizedContactSerializer},
        tags=['Customized Contacts']
    )
    def patch(self, request, template_id):
        """Update email template status."""
        qs = CustomizedContact.objects.all()
        if request.user.is_authenticated:
            qs = qs.filter(lead__job__created_by=request.user)
        template = get_object_or_404(qs, pk=template_id)

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            old_status = template.status
            new_status = serializer.validated_data['status']

            template.status = new_status
            if 'status_message' in serializer.validated_data:
                template.status_message = serializer.validated_data['status_message']
            template.save()

            # Emit signals based on status change
            if new_status == 'ready' and old_status != 'ready':
                email_template_ready.send(sender=self.__class__, instance=template)
                logger.info(f"Email template {template.id} marked as ready - signal emitted")

            elif new_status == 'approved' and old_status != 'approved':
                email_template_approved.send(sender=self.__class__, instance=template)
                logger.info(f"Email template {template.id} approved - signal emitted")

            return Response(CustomizedContactSerializer(template).data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class EmailTemplateListAPIView(APIView):
    """
    Global endpoint for listing and creating all customized contacts.
    Use this endpoint to access all contacts across all leads (flat resource).
    Example: /api/customized-contacts/
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        operation_id='listCustomizedContacts',
        summary='List all customized contacts (global)',
        description='Returns all customized contacts for the current user, across all leads. Use this endpoint for a flat/global list. For per-lead access, use /api/leads/{lead_id}/customized-contact/.',
        parameters=[
            OpenApiParameter(
                name='status',
                type=OpenApiTypes.STR,
                description='Filter by status (draft, ready, approved, sent)'
            ),
            OpenApiParameter(
                name='lead_id',
                type=OpenApiTypes.INT,
                description='Filter by lead ID'
            ),
        ],
        responses={200: CustomizedContactListSerializer(many=True)},
        tags=['Customized Contacts']
    )
    def get(self, request):
        """List all email templates."""
        templates = CustomizedContact.objects.all().select_related('lead')
        if request.user.is_authenticated:
            templates = templates.filter(lead__job__created_by=request.user)
        
        # Filters
        status_filter = request.query_params.get('status')
        if status_filter:
            templates = templates.filter(status=status_filter)
        
        lead_id = request.query_params.get('lead_id')
        if lead_id:
            templates = templates.filter(lead_id=lead_id)
        
        serializer = CustomizedContactListSerializer(templates, many=True)
        return Response(serializer.data)


class LeadsWithEmailsAPIView(APIView):
    """
    API endpoint to list leads that have available emails.
    
    GET /api/gmaps-leads/with-emails/
    
    Useful for AI to find leads that can receive outreach emails.
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        operation_id='listLeadsWithEmails',
        summary='List leads with available emails',
        description='''
        Returns leads that have email addresses available (from scraping or website).
        
        Use this endpoint to find leads that are ready for email outreach.
        ''',
        parameters=[
            OpenApiParameter(
                name='without_template',
                type=OpenApiTypes.BOOL,
                description='Only return leads without an email template'
            ),
            OpenApiParameter(
                name='category',
                type=OpenApiTypes.STR,
                description='Filter by business category'
            ),
            OpenApiParameter(
                name='limit',
                type=OpenApiTypes.INT,
                description='Maximum number of results (default 50)'
            ),
        ],
        responses={200: GmapsLeadListSerializer(many=True)},
        tags=['AI Email Generation']
    )
    def get(self, request):
        """List leads with available emails."""
        from django.db.models import Exists, OuterRef
        
        # Start with leads that have website data with emails
        leads = GmapsLead.objects.filter(
            Q(website_data__emails__len__gt=0) |
            Q(emails__isnull=False)
        ).select_related('website_data').distinct()
        if request.user.is_authenticated:
            leads = leads.filter(job__created_by=request.user)
        
        # Filter to leads without templates
        without_template = request.query_params.get('without_template')
        if without_template and without_template.lower() == 'true':
            leads = leads.exclude(
                Exists(CustomizedContact.objects.filter(lead=OuterRef('pk')))
            )
        
        # Filter by category
        category = request.query_params.get('category')
        if category:
            leads = leads.filter(category__icontains=category)
        
        # Limit
        try:
            limit = int(request.query_params.get('limit', 50))
        except Exception:
            limit = 50
        leads = leads[: min(limit, 200)]
        
        serializer = GmapsLeadListSerializer(leads, many=True)
        return Response(serializer.data)


# =============================================================================
# AI Campaign Endpoints (CampaignRecipient-centric)
# =============================================================================


class AICampaignListAPIView(APIView):
    """
    List ongoing campaigns for AI.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="aiListCampaigns",
        summary="AI: List ongoing campaigns",
        description="Returns campaigns in ready/running status (use status query param to override).",
        parameters=[
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                description="Optional status filter (comma-separated). Default: ready,running"
            ),
        ],
        responses={200: AICampaignSerializer(many=True)},
        tags=["AI Campaigns"],
    )
    def get(self, request):
        status_param = request.query_params.get("status")
        statuses = ["ready", "running"]
        if status_param:
            statuses = [s.strip() for s in status_param.split(",") if s.strip()]
        qs = EmailCampaign.objects.filter(status__in=statuses).order_by("-updated_at")
        serializer = AICampaignSerializer(qs, many=True)
        return Response(serializer.data)


class AICampaignRecipientStatusAPIView(APIView):
    """
    Return recipient counts and IDs by status for a campaign.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="aiCampaignRecipientStatus",
        summary="AI: Recipient status counts",
        description="Returns counts and recipient IDs grouped by status. Filter with status param (comma-separated).",
        parameters=[
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                description="Optional status filter (comma-separated). Default: pending"
            ),
        ],
        responses={200: AICampaignRecipientStatusSerializer},
        tags=["AI Campaigns"],
    )
    def get(self, request, campaign_id):
        campaign = get_object_or_404(EmailCampaign, pk=campaign_id)
        status_param = request.query_params.get("status")
        statuses = ["pending"]
        if status_param:
            statuses = [s.strip() for s in status_param.split(",") if s.strip()]

        response = {"campaign_id": campaign.id, "statuses": {}}
        for st in statuses:
            ids = list(
                campaign.recipients.filter(status=st)
                .order_by("id")
                .values_list("id", flat=True)
            )
            response["statuses"][st] = {"count": len(ids), "ids": ids}

        return Response(response)


class AICampaignRecipientContextAPIView(APIView):
    """
    Fetch campaign recipient context for AI rendering.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="aiGetCampaignRecipientContext",
        summary="AI: Get campaign recipient context",
        description="Returns recipient context (lead/company/site text) for AI to render personalized email.",
        responses={200: AICampaignRecipientContextSerializer},
        tags=["AI Campaigns"],
    )
    def get(self, request, campaign_id, recipient_id):
        recipient = get_object_or_404(
            CampaignRecipient.objects.select_related("campaign", "email_address", "recipient"),
            pk=recipient_id,
            campaign_id=campaign_id,
        )
        serializer = AICampaignRecipientContextSerializer(recipient)
        return Response(serializer.data)

class AICampaignRecipientListAPIView(APIView):
    """
    List campaign recipients (filterable by status).
    """
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="aiListCampaignRecipients",
        summary="AI: List campaign recipients",
        description="Returns recipients for a campaign. Filter by status and limit for batching.",
        parameters=[
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                description="Optional status filter (comma-separated). Default: pending"
            ),
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                description="Max results (default 50)"
            ),
        ],
        responses={200: AICampaignRecipientListSerializer(many=True)},
        tags=["AI Campaigns"],
    )
    def get(self, request, campaign_id):
        campaign = get_object_or_404(EmailCampaign, pk=campaign_id)
        status_param = request.query_params.get("status")
        statuses = ["pending"]
        if status_param:
            statuses = [s.strip() for s in status_param.split(",") if s.strip()]
        limit = request.query_params.get("limit")
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 50
        qs = campaign.recipients.select_related("email_address", "recipient").filter(status__in=statuses).order_by("id")[:limit]
        serializer = AICampaignRecipientListSerializer(qs, many=True)
        return Response(serializer.data)


class AICampaignRecipientContentAPIView(APIView):
    """
    Submit rendered content for a campaign recipient.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="aiSubmitCampaignRecipientContent",
        summary="AI: Submit rendered email content",
        description="Attach subject/body to a campaign recipient. Sets status to ready when mark_ready=true (default).",
        request=AICampaignRecipientContentSerializer,
        responses={200: AICampaignRecipientContextSerializer},
        tags=["AI Campaigns"],
    )
    def post(self, request, campaign_id, recipient_id):
        recipient = get_object_or_404(
            CampaignRecipient.objects.select_related("campaign"),
            pk=recipient_id,
            campaign_id=campaign_id,
        )
        serializer = AICampaignRecipientContentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        recipient.subject = data["subject"]
        recipient.body_html = data["body_html"]
        recipient.body_text = data.get("body_text") or ""
        if data.get("mark_ready", True):
            recipient.status = CampaignRecipient.STATUS_READY
        recipient.save(update_fields=["subject", "body_html", "body_text", "status", "updated_at"])

        out = AICampaignRecipientContextSerializer(recipient)
        return Response(out.data)


class ContactableLeadsAPIView(APIView):
    """
    Return leads that have at least one contact method (phone or email).
    Accepts optional category filter and limit (default 10, max 200).
    """
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id='leads_contactable',
        summary='List contactable leads',
        description='Returns leads that have a phone number or email. Optional filters: category, limit (default 10, max 200).',
        parameters=[
            OpenApiParameter(name='category', type=OpenApiTypes.STR, description='Filter by business category'),
            OpenApiParameter(name='limit', type=OpenApiTypes.INT, description='Max results (default 10, max 200)'),
        ],
        responses={200: GmapsLeadListSerializer(many=True)},
        tags=['Leads'],
    )
    def get(self, request):
        category = request.query_params.get('category')
        try:
            limit = int(request.query_params.get('limit', 10))
        except Exception:
            limit = 10
        limit = min(max(limit, 1), 200)

        leads = GmapsLead.objects.filter(
            Q(phone__isnull=False) & ~Q(phone__exact='') |
            Q(emails__isnull=False) & ~Q(emails__exact='') |
            Q(website_data__emails__len__gt=0)
        )
        if category:
            leads = leads.filter(category__icontains=category)
        if request.user.is_authenticated:
            leads = leads.filter(job__created_by=request.user)

        leads = leads.order_by('-id')[:limit]
        serializer = GmapsLeadListSerializer(leads, many=True)
        return Response(serializer.data)


# =============================================================================
# WAHA Integration
# =============================================================================


class WahaHealthAPIView(APIView):
    """Lightweight health probe against the configured WAHA instance."""

    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def get(self, request):
        try:
            client = WahaClient()
        except WahaClientError as exc:
            return Response(
                {"ok": False, "configured": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            return Response(
                {"ok": False, "configured": False, "error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        result = client.health()
        result["configured"] = True
        http_status = status.HTTP_200_OK if result.get("ok") else status.HTTP_502_BAD_GATEWAY
        return Response(result, status=http_status)


class WahaContactSyncAPIView(APIView):
    """
    Create/refresh WhatsAppContact records from WhatsApp-eligible leads and push them to WAHA.
    Supports dry-run to inspect the outgoing payload without calling WAHA.
    """

    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def post(self, request):
        serializer = WahaContactSyncSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        limit = data.get("limit") or 100
        job_id = data.get("job_id")
        dry_run = data.get("dry_run", True)
        skip_synced = data.get("skip_synced", True)
        force_refresh = data.get("force_refresh", False)

        leads_qs = GmapsLead.objects.filter(phone__isnull=False).exclude(phone="").select_related("job")
        if job_id:
            leads_qs = leads_qs.filter(job_id=job_id)
        if skip_synced and not force_refresh:
            leads_qs = leads_qs.filter(
                Q(whatsapp_contact__isnull=True) | Q(whatsapp_contact__synced_to_waha=False)
            )

        prepared_entries = []
        created_contacts = 0
        reused_contacts = 0
        errors = []
        scanned = 0

        for lead in leads_qs.order_by("-id"):
            if lead.phone_type != "whatsapp":
                continue
            scanned += 1
            if len(prepared_entries) >= limit:
                break

            try:
                contact = getattr(lead, "whatsapp_contact", None)
                if contact and force_refresh:
                    phone = lead.cleaned_phone
                    contact.phone_number = phone
                    contact.chat_id = f"{phone}@c.us"
                    contact.jid = f"{phone}@s.whatsapp.net"
                    contact.business_name = lead.title
                    contact.category = lead.category
                    contact.save()
                elif not contact:
                    contact = WhatsAppContact.create_from_lead(lead)
                    created_contacts += 1
                else:
                    reused_contacts += 1

                payload = {
                    "name": contact.business_name or lead.title,
                    "phone": contact.phone_number,
                    "chatId": contact.chat_id,
                    "jid": contact.jid,
                    "category": contact.category or lead.category,
                    "lead_id": lead.id,
                }
                prepared_entries.append({"contact": contact, "payload": payload})
            except Exception as exc:
                errors.append({"lead_id": lead.id, "error": str(exc)})
                continue

        summary = {
            "dry_run": dry_run,
            "job_id": job_id,
            "limit": limit,
            "scanned": scanned,
            "prepared": len(prepared_entries),
            "created_contacts": created_contacts,
            "reused_contacts": reused_contacts,
            "errors": errors,
            "payload_preview": [entry["payload"] for entry in prepared_entries[: min(5, len(prepared_entries))]],
        }

        if dry_run or not prepared_entries:
            status_code = status.HTTP_200_OK if not errors else status.HTTP_206_PARTIAL_CONTENT
            summary["message"] = "Dry run - no call made to WAHA." if dry_run else "No contacts prepared."
            return Response(summary, status=status_code)

        try:
            client = WahaClient()
        except WahaClientError as exc:
            summary["waha"] = {"success": False, "configured": False, "error": str(exc)}
            return Response(summary, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            summary["waha"] = {"success": False, "configured": True, "error": str(exc)}
            return Response(summary, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        payloads = [entry["payload"] for entry in prepared_entries]
        waha_result = client.sync_contacts(payloads)
        summary["waha"] = waha_result
        failure_chat_ids = {f.get("chatId") for f in waha_result.get("failures", []) if f.get("chatId")}
        attempts_map = waha_result.get("attempts") or {}
        conflict_synced = 0

        def _contains_conflict(value):
            if value is None:
                return False
            try:
                if isinstance(value, (dict, list)):
                    text = json.dumps(value)
                else:
                    text = str(value)
            except Exception:
                text = str(value)
            return "conflict" in text.lower()

        now = timezone.now()
        for entry in prepared_entries:
            contact = entry["contact"]
            chat_id = entry["payload"].get("chatId")
            if not contact or not chat_id:
                continue
            contact.waha_sync_attempts = (contact.waha_sync_attempts or 0) + 1
            attempts = attempts_map.get(chat_id, [])
            conflict_error = any(
                _contains_conflict(attempt.get("payload")) or _contains_conflict(attempt.get("error"))
                for attempt in attempts
            )
            if chat_id in failure_chat_ids and conflict_error:
                failure_chat_ids.discard(chat_id)
                conflict_synced += 1

            if chat_id in failure_chat_ids:
                contact.synced_to_waha = False
                contact.save(update_fields=["synced_to_waha", "waha_sync_attempts", "updated_at"])
            else:
                contact.synced_to_waha = True
                contact.waha_synced_at = now
                contact.save(update_fields=["synced_to_waha", "waha_synced_at", "waha_sync_attempts", "updated_at"])
        summary["conflict_marked_synced"] = conflict_synced
        http_status = status.HTTP_200_OK if waha_result.get("success") else status.HTTP_502_BAD_GATEWAY
        return Response(summary, status=http_status)


class WahaSendMessageAPIView(APIView):
    """Send a WhatsApp text message via WAHA."""

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Send WhatsApp text via WAHA",
        request=WahaSendMessageSerializer,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        serializer = WahaSendMessageSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        chat_id = data.get("chat_id")
        phone = data.get("phone")
        lead_id = data.get("lead_id")
        text = data["text"]
        quoted_message_id = data.get("quoted_message_id") or None
        resolved_lead_id = None

        # Resolve chatId from lead if provided
        if lead_id and not chat_id:
            lead = get_object_or_404(GmapsLead, pk=lead_id)
            resolved_lead_id = lead.id
            contact = getattr(lead, "whatsapp_contact", None)
            if not contact:
                if lead.phone_type != "whatsapp":
                    return Response(
                        {"error": "Lead phone is not WhatsApp eligible."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                contact = WhatsAppContact.create_from_lead(lead)
            chat_id = contact.chat_id
            phone = contact.phone_number

        # If only phone provided, format to chatId
        if not chat_id and phone:
            digits = "".join(c for c in str(phone) if c.isdigit())
            if not digits:
                return Response({"error": "Phone is invalid; digits are required."}, status=status.HTTP_400_BAD_REQUEST)
            chat_id = f"{digits}@c.us"
            phone = digits

        if not chat_id:
            return Response({"error": "Unable to resolve chat_id."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            client = WahaClient()
        except WahaClientError as exc:
            return Response(
                {"error": "WAHA is not configured", "details": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            return Response(
                {"error": "Failed to initialize WAHA client", "details": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        result = client.send_text(chat_id=chat_id, text=text, quoted_message_id=quoted_message_id, phone=phone)
        status_code = status.HTTP_200_OK if result.get("success") else status.HTTP_502_BAD_GATEWAY
        return Response(
            {
                "chat_id": chat_id,
                "phone": phone,
                "lead_id": resolved_lead_id or lead_id,
                "quoted_message_id": quoted_message_id,
                "text_preview": text[:120],
                "waha": result,
            },
            status=status_code,
        )


class WahaTestMessageAPIView(APIView):
    """
    Test helper: preview (dry_run) or send a single message using template pools/templates/campaigns.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Preview or send a test WhatsApp message via WAHA",
        request=WahaTestMessageSerializer,
        responses={200: OpenApiTypes.OBJECT, 206: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        serializer = WahaTestMessageSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = run_test_message(data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        status_code = status.HTTP_200_OK
        if not result.get("dry_run") and not (result.get("waha") or {}).get("success"):
            status_code = status.HTTP_502_BAD_GATEWAY
        return Response(result, status=status_code)


# =============================================================================
# WhatsApp Campaigns (WAHA)
# =============================================================================


class WhatsAppCampaignAPIView(APIView):
    """Create/list WhatsApp campaigns scoped by scrape job."""

    permission_classes = [AllowAny]

    @extend_schema(
        summary="List WhatsApp campaigns",
        responses=WhatsAppCampaignSerializer(many=True),
        parameters=[
            OpenApiParameter("job_id", OpenApiTypes.INT, OpenApiParameter.QUERY, description="Filter by scrape job id"),
        ],
    )
    def get(self, request):
        job_id = request.query_params.get("job_id")
        qs = WhatsAppCampaign.objects.all().select_related("job")
        if job_id:
            qs = qs.filter(job_id=job_id)
        return Response(WhatsAppCampaignSerializer(qs, many=True).data)

    @extend_schema(
        summary="Create WhatsApp campaign",
        request=WhatsAppCampaignSerializer,
        responses=WhatsAppCampaignSerializer,
    )
    def post(self, request):
        serializer = WhatsAppCampaignSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        campaign = serializer.save(created_by=getattr(request, "user", None) if getattr(request, "user", None).is_authenticated else None)
        return Response(WhatsAppCampaignSerializer(campaign).data, status=status.HTTP_201_CREATED)


class WhatsAppTemplatePoolAPIView(APIView):
    """List/create WhatsApp template pools."""

    permission_classes = [AllowAny]

    @extend_schema(
        summary="List WhatsApp template pools",
        responses=WhatsAppTemplatePoolSerializer(many=True),
        parameters=[OpenApiParameter("job_id", OpenApiTypes.INT, OpenApiParameter.QUERY, description="Filter by job id")],
    )
    def get(self, request):
        job_id = request.query_params.get("job_id")
        qs = WhatsAppTemplatePool.objects.all()
        if job_id:
            qs = qs.filter(job_id=job_id)
        return Response(WhatsAppTemplatePoolSerializer(qs, many=True).data)

    @extend_schema(
        summary="Create WhatsApp template pool",
        request=WhatsAppTemplatePoolSerializer,
        responses=WhatsAppTemplatePoolSerializer,
    )
    def post(self, request):
        serializer = WhatsAppTemplatePoolSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        pool = serializer.save()
        return Response(WhatsAppTemplatePoolSerializer(pool).data, status=status.HTTP_201_CREATED)


class WhatsAppTemplateAPIView(APIView):
    """List/create WhatsApp templates."""

    permission_classes = [AllowAny]

    @extend_schema(
        summary="List WhatsApp templates",
        responses=WhatsAppTemplateSerializer(many=True),
        parameters=[OpenApiParameter("pool_id", OpenApiTypes.INT, OpenApiParameter.QUERY, description="Filter by pool id")],
    )
    def get(self, request):
        pool_id = request.query_params.get("pool_id")
        qs = WhatsAppTemplate.objects.select_related("pool")
        if pool_id:
            qs = qs.filter(pool_id=pool_id)
        return Response(WhatsAppTemplateSerializer(qs, many=True).data)

    @extend_schema(
        summary="Create WhatsApp template",
        request=WhatsAppTemplateSerializer,
        responses=WhatsAppTemplateSerializer,
    )
    def post(self, request):
        serializer = WhatsAppTemplateSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        template = serializer.save()
        return Response(WhatsAppTemplateSerializer(template).data, status=status.HTTP_201_CREATED)


class WhatsAppCampaignRunAPIView(APIView):
    """Run a WhatsApp campaign: build recipients from job leads, then send with jitter and throttle."""

    permission_classes = [AllowAny]
    serializer_class = WhatsAppCampaignSerializer
    @extend_schema(deprecated=True)

    @extend_schema(
        summary="Run WhatsApp campaign",
        responses={200: OpenApiTypes.OBJECT, 206: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request, campaign_id: int):
        campaign = get_object_or_404(WhatsAppCampaign.objects.select_related("job"), pk=campaign_id)
        if campaign.status == "running":
            return Response({"error": "Campaign already running."}, status=status.HTTP_400_BAD_REQUEST)
        if campaign.status == "done":
            return Response({"error": "Campaign already completed."}, status=status.HTTP_400_BAD_REQUEST)

        # Ensure recipients exist before sending (no overwrite by default)
        prep = prepare_campaign_recipients(campaign)
        errors: list[dict] = prep.get("errors", [])
        pending_qs = campaign.recipients.select_related("whatsapp_contact").filter(status="pending").order_by("id")
        total = pending_qs.count()
        if total == 0:
            return Response(
                {"error": "No pending recipients to send.", "prepare": prep},
                status=status.HTTP_400_BAD_REQUEST,
            )

        campaign.status = "running"
        campaign.last_error = None
        campaign.save(update_fields=["status", "last_error", "updated_at"])

        throttle = max(campaign.throttle_per_minute or 1, 1)
        min_interval = 60.0 / float(throttle)
        delay_min = max(campaign.delay_min_ms or 0, 0) / 1000.0
        delay_max = max(campaign.delay_max_ms or delay_min, delay_min) / 1000.0

        sent = 0
        failed = 0

        try:
            client = WahaClient()
        except Exception as exc:  # noqa: BLE001
            campaign.status = "failed"
            campaign.last_error = str(exc)
            campaign.save(update_fields=["status", "last_error", "updated_at"])
            return Response({"error": "Failed to init WAHA client", "details": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        for recipient in pending_qs.iterator():
            # Respect random delay and throttle
            jitter = random.uniform(delay_min, delay_max)
            sleep_time = max(jitter, min_interval)
            time.sleep(sleep_time)

            contact = recipient.whatsapp_contact
            chat_id = getattr(contact, "chat_id", None)
            if not chat_id:
                recipient.status = "failed"
                recipient.error = "Missing chat_id"
                recipient.attempts += 1
                recipient.save(update_fields=["status", "error", "attempts", "updated_at"])
                failed += 1
                continue

            try:
                text_to_send = compose_whatsapp_text(recipient.rendered_text or "", recipient.media_url)
                result = client.send_text(chat_id=chat_id, text=text_to_send)
                recipient.attempts += 1
                if result.get("success"):
                    recipient.status = "sent"
                    recipient.message_id = result.get("response", {}).get("id")
                    recipient.error = None
                    recipient.sent_at = timezone.now()
                    sent += 1
                else:
                    recipient.status = "failed"
                    recipient.error = str(result)
                    failed += 1
                recipient.save(update_fields=["status", "message_id", "error", "sent_at", "attempts", "updated_at"])
            except Exception as exc:  # noqa: BLE001
                recipient.status = "failed"
                recipient.error = str(exc)
                recipient.attempts += 1
                recipient.save(update_fields=["status", "error", "attempts", "updated_at"])
                failed += 1

        campaign.status = "done" if failed == 0 else "failed"
        campaign.last_error = None if failed == 0 else f"{failed} failed out of {total}"
        campaign.save(update_fields=["status", "last_error", "updated_at"])

        return Response(
            {
                "campaign_id": campaign.id,
                "job_id": campaign.job_id,
                "total": total,
                "sent": sent,
                "failed": failed,
                "prepare": {k: prep.get(k) for k in ("created_contacts", "created_recipients", "updated_recipients", "skipped_non_whatsapp", "total_recipients")},
                "errors": errors[:10],
            },
            status=status.HTTP_200_OK if failed == 0 else status.HTTP_206_PARTIAL_CONTENT,
        )


class WhatsAppCampaignPrepareAPIView(APIView):
    """Generate recipients for a campaign without sending."""

    permission_classes = [AllowAny]
    @extend_schema(deprecated=True)

    @extend_schema(
        summary="Prepare WhatsApp campaign recipients",
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request, campaign_id: int):
        campaign = get_object_or_404(WhatsAppCampaign.objects.select_related("job"), pk=campaign_id)
        data = request.data or {}
        limit = data.get("limit")
        overwrite = bool(data.get("overwrite", False))
        try:
            limit_int = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            return Response({"error": "limit must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        prep = prepare_campaign_recipients(campaign, limit=limit_int, overwrite=overwrite)
        return Response(prep, status=status.HTTP_200_OK if not prep.get("errors") else status.HTTP_206_PARTIAL_CONTENT)


class WhatsAppCampaignRecipientsAPIView(APIView):
    """List recipients for a campaign."""

    permission_classes = [AllowAny]
    @extend_schema(deprecated=True)

    @extend_schema(
        summary="List WhatsApp campaign recipients",
        responses=WhatsAppCampaignRecipientSerializer(many=True),
    )
    def get(self, request, campaign_id: int):
        campaign = get_object_or_404(WhatsAppCampaign, pk=campaign_id)
        recips = campaign.recipients.select_related("lead").order_by("-id")
        return Response(WhatsAppCampaignRecipientSerializer(recips, many=True).data)


# =============================================================================
# Chatwoot Sync
# =============================================================================


def _first_email_from_lead(lead: GmapsLead) -> str | None:
    if not lead.emails:
        return None
    try:
        import json
        parsed = json.loads(lead.emails) if isinstance(lead.emails, str) else lead.emails
        if isinstance(parsed, list):
            return parsed[0] if parsed else None
        if isinstance(parsed, str):
            return parsed
    except Exception:
        pass
    return None


def _emails_from_lead(lead: GmapsLead) -> list[str]:
    emails = []
    try:
        import json
        if lead.emails:
            parsed = json.loads(lead.emails) if isinstance(lead.emails, str) else lead.emails
            if isinstance(parsed, list):
                emails.extend([e for e in parsed if e])
            elif isinstance(parsed, str):
                emails.append(parsed)
    except Exception:
        pass
    try:
        if hasattr(lead, "website_data") and lead.website_data and lead.website_data.emails:
            emails.extend([e for e in lead.website_data.emails if e])
    except Exception:
        pass
    # Deduplicate while preserving order
    seen = set()
    uniq = []
    for e in emails:
        if e not in seen:
            uniq.append(e)
            seen.add(e)
    return uniq


def _first_phone_from_lead(lead: GmapsLead) -> str | None:
    # Try explicit phone fields
    for attr in ["phone", "phone_number", "whatsapp_number", "whatsapp"]:
        val = getattr(lead, attr, None)
        if val:
            return val
    # Try serialized phones on lead
    try:
        if getattr(lead, "phones", None):
            parsed = json.loads(lead.phones) if isinstance(lead.phones, str) else lead.phones
            if isinstance(parsed, list) and parsed:
                return parsed[0]
    except Exception:
        pass
    return None


class ChatwootContactSyncAPIView(APIView):
    """
    Sync leads into Chatwoot and record ledger entries for tracking.
    """

    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def post(self, request):
        serializer = ChatwootContactSyncSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        limit = data.get("limit") or 100
        job_id = data.get("job_id")
        dry_run = data.get("dry_run", True)
        skip_synced = data.get("skip_synced", True)

        client = ChatwootClient()
        if not client.configured:
            return Response(
                {"error": "Chatwoot is not configured. Check CHATWOOT_* env vars.", "configured": False},
                status=status.HTTP_400_BAD_REQUEST,
            )

        leads_qs = GmapsLead.objects.all().select_related("job")
        if job_id:
            leads_qs = leads_qs.filter(job_id=job_id)
        if skip_synced:
            from django.db.models import Exists, OuterRef
            leads_qs = leads_qs.annotate(
                _has_sync=Exists(ChatwootContactSync.objects.filter(lead_id=OuterRef("id"), status="synced"))
            ).filter(_has_sync=False)

        prepared = []
        errors = []
        scanned = 0

        for lead in leads_qs.order_by("-id"):
            if len(prepared) >= limit:
                break
            scanned += 1
            phone = lead.cleaned_phone
            emails = _emails_from_lead(lead)
            email = emails[0] if emails else None
            if not phone and not email:
                continue

            # Enrich with WhatsApp identifiers if available
            wa_attrs = {}
            try:
                wa = getattr(lead, "whatsapp_contact", None)
                if wa:
                    if getattr(wa, "chat_id", None):
                        wa_attrs["whatsapp_chat_id"] = wa.chat_id
                        wa_attrs["waha_whatsapp_chat_id"] = wa.chat_id
                    if getattr(wa, "jid", None):
                        wa_attrs["whatsapp_jid"] = wa.jid
                        wa_attrs["waha_whatsapp_jid"] = wa.jid
                    if getattr(wa, "lid", None):
                        wa_attrs["whatsapp_lid"] = wa.lid
                        wa_attrs["waha_whatsapp_lid"] = wa.lid
            except Exception:
                wa_attrs = {}

            payload = {
                "name": lead.title or (email or phone),
                "phone": f"+{phone}" if phone and not phone.startswith("+") else phone,
                "email": email,
                "custom_attributes": {
                    "gmaps_lead_id": lead.id,
                    "category": lead.category,
                    "website": lead.website,
                    "emails": emails,
                    "social_links": getattr(getattr(lead, "website_data", None), "social_links", None) or {},
                    **wa_attrs,
                },
                "lead_id": lead.id,
            }
            prepared.append(payload)

        summary = {
            "dry_run": dry_run,
            "job_id": job_id,
            "limit": limit,
            "scanned": scanned,
            "prepared": len(prepared),
            "synced": 0,
            "failed": 0,
            "errors": errors,
            "preview": prepared[: min(5, len(prepared))],
        }

        if dry_run or not prepared:
            return Response(summary)

        for payload in prepared:
            lead_id = payload["lead_id"]
            phone = payload.get("phone")
            email = payload.get("email")
            try:
                contact = client.ensure_contact_any(
                    phone=phone,
                    email=email,
                    name=payload.get("name"),
                    custom_attributes=payload.get("custom_attributes"),
                )
                contact_id = contact.get("id") if isinstance(contact, dict) else None
                if not contact_id:
                    raise ValueError(f"Chatwoot contact id missing for lead {lead_id}")
                inbox_res = client.ensure_contact_inbox(
                    contact_id=contact_id,
                    inbox_id=getattr(client, "inbox_id", None),
                    source_id=phone or email,
                )
                ledger, _ = ChatwootContactSync.objects.get_or_create(lead_id=lead_id)
                ledger.chatwoot_contact_id = contact_id
                ledger.chatwoot_inbox_id = getattr(client, "inbox_id", None)
                ledger.source_identifier = phone or email
                ledger.payload = payload
                ledger.status = "synced"
                ledger.last_error = None
                ledger.last_synced_at = timezone.now()
                ledger.save()
                summary["synced"] += 1
            except Exception as exc:  # noqa: BLE001
                ledger, _ = ChatwootContactSync.objects.get_or_create(lead_id=lead_id)
                ledger.status = "failed"
                ledger.last_error = str(exc)
                ledger.payload = payload
                ledger.last_synced_at = timezone.now()
                ledger.save()
                errors.append({"lead_id": lead_id, "error": str(exc)})
                summary["failed"] += 1

        return Response(summary, status=status.HTTP_200_OK if summary["failed"] == 0 else status.HTTP_206_PARTIAL_CONTENT)


# =============================================================================
# Magic Notifier bulk sends (email + WhatsApp) - preferred paths
# =============================================================================


class EmailBlastAPIView(APIView):
    """Send simple emails to selected leads via magic_notifier."""

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Send emails to leads (magic_notifier)",
        description="Simple bulk sender: provide lead_ids, subject/body, optional throttle and jitter.",
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        data = request.data or {}
        lead_ids = data.get("lead_ids") or []
        subject = data.get("subject")
        body = data.get("body")
        throttle = max(int(data.get("throttle_per_minute", 60) or 60), 1)
        delay_min = max(int(data.get("delay_min_ms", 0) or 0), 0) / 1000.0
        delay_max = max(int(data.get("delay_max_ms", delay_min * 1000) or delay_min * 1000), int(delay_min * 1000)) / 1000.0

        if not subject or not body:
            return Response({"error": "subject and body are required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            lead_ids = [int(i) for i in lead_ids]
        except Exception:
            return Response({"error": "lead_ids must be a list of ints"}, status=status.HTTP_400_BAD_REQUEST)

        leads = list(GmapsLead.objects.filter(id__in=lead_ids))
        prepared: list[tuple[GmapsLead, str]] = []
        for lead in leads:
            email = _emails_from_lead(lead)
            if email:
                prepared.append((lead, email[0]))

        if not prepared:
            return Response({"error": "No leads with email found."}, status=status.HTTP_400_BAD_REQUEST)

        base_interval = 60.0 / float(throttle)
        sent = 0
        errors: list[dict] = []

        for lead, email in prepared:
            try:
                em = Emailer(subject, [email], template=None, context={"lead": lead}, final_message=body)
                em.send()
                create_notification(
                    recipient=lead,
                    text=body,
                    type="email",
                    subject=subject,
                    data={"email": email, "lead_id": lead.id},
                )
                sent += 1
            except Exception as exc:  # noqa: BLE001
                errors.append({"lead_id": lead.id, "email": email, "error": str(exc)})
            sleep_time = max(base_interval, random.uniform(delay_min, delay_max))
            if sleep_time > 0:
                time.sleep(sleep_time)

        return Response(
            {
                "requested": len(lead_ids),
                "with_email": len(prepared),
                "sent": sent,
                "errors": errors[:10],
                "throttle_per_minute": throttle,
                "delay_ms": {"min": int(delay_min * 1000), "max": int(delay_max * 1000)},
            },
            status=status.HTTP_200_OK if not errors else status.HTTP_206_PARTIAL_CONTENT,
        )


class WhatsAppBlastAPIView(APIView):
    """Send WhatsApp messages to leads via magic_notifier / WAHA client wrappers."""

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Send WhatsApp messages to leads (magic_notifier)",
        description="Provide lead_ids, text/media, optional throttle/jitter. Uses WAHA client via magic_notifier.",
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        data = request.data or {}
        lead_ids = data.get("lead_ids") or []
        text = data.get("text")
        media_url = data.get("media_url")
        throttle = max(int(data.get("throttle_per_minute", 30) or 30), 1)
        delay_min = max(int(data.get("delay_min_ms", 0) or 0), 0) / 1000.0
        delay_max = max(int(data.get("delay_max_ms", delay_min * 1000) or delay_min * 1000), int(delay_min * 1000)) / 1000.0

        if not text:
            return Response({"error": "text is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            lead_ids = [int(i) for i in lead_ids]
        except Exception:
            return Response({"error": "lead_ids must be a list of ints"}, status=status.HTTP_400_BAD_REQUEST)

        leads = list(GmapsLead.objects.filter(id__in=lead_ids).select_related("whatsapp_contact"))
        prepared: list[tuple[GmapsLead, str | None]] = []
        for lead in leads:
            chat_id = None
            wa_contact = getattr(lead, "whatsapp_contact", None)
            if wa_contact and getattr(wa_contact, "chat_id", None):
                chat_id = wa_contact.chat_id
            if not chat_id:
                chat_id = _first_phone_from_lead(lead)
            if chat_id:
                prepared.append((lead, chat_id))

        if not prepared:
            return Response({"error": "No leads with WhatsApp/chat_id found."}, status=status.HTTP_400_BAD_REQUEST)

        base_interval = 60.0 / float(throttle)
        sent = 0
        errors: list[dict] = []

        try:
            client = WahaClient()
        except Exception as exc:  # noqa: BLE001
            return Response({"error": "Failed to init WAHA client", "details": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        for lead, chat_id in prepared:
            try:
                payload_text = compose_whatsapp_text(text, media_url)
                result = client.send_text(chat_id=chat_id, text=payload_text)
                if result.get("success"):
                    sent += 1
                    create_notification(
                        recipient=lead,
                        text=text,
                        type="whatsapp",
                        data={"chat_id": chat_id, "lead_id": lead.id, "media_url": media_url},
                    )
                else:
                    errors.append({"lead_id": lead.id, "chat_id": chat_id, "error": str(result)})
            except Exception as exc:  # noqa: BLE001
                errors.append({"lead_id": lead.id, "chat_id": chat_id, "error": str(exc)})
            sleep_time = max(base_interval, random.uniform(delay_min, delay_max))
            if sleep_time > 0:
                time.sleep(sleep_time)

        return Response(
            {
                "requested": len(lead_ids),
                "with_chat": len(prepared),
                "sent": sent,
                "errors": errors[:10],
                "throttle_per_minute": throttle,
                "delay_ms": {"min": int(delay_min * 1000), "max": int(delay_max * 1000)},
            },
            status=status.HTTP_200_OK if not errors else status.HTTP_206_PARTIAL_CONTENT,
        )


class EmailRecipientSendAPIView(APIView):
    """Send a single campaign recipient after manual review."""

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Send single email campaign recipient (manual approve)",
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request, recipient_id: int):
        def extract_whatsapp_links(text: str):
            """Return unique wa.me links in order."""
            if not text:
                return []
            try:
                pattern = re.compile(r"https?://wa\\.me/[\\w/?=&%+\\.\\-]+", re.IGNORECASE)
                seen = set()
                links = []
                for match in pattern.findall(text):
                    if match not in seen:
                        seen.add(match)
                        links.append(match)
                return links
            except re.error:
                return []

        recipient = get_object_or_404(
            CampaignRecipient.objects.select_related("campaign", "email_address", "recipient"),
            pk=recipient_id,
        )
        email_address = getattr(recipient, "email_address", None)
        if not email_address or not email_address.email:
            return Response({"error": "No email address for recipient"}, status=status.HTTP_400_BAD_REQUEST)

        subject = recipient.subject or (recipient.campaign.name if recipient.campaign else "")
        tpl_html = tpl_text = ""
        tpl = recipient.campaign.template if recipient.campaign else None
        if tpl:
            tpl_html = tpl.html_template or ""
            tpl_text = tpl.text_template or ""

        body_html = recipient.body_html or tpl_html
        body_text = recipient.body_text or tpl_text
        body = body_html or body_text
        if not body:
            return Response({"error": "No body content to send"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            email_theme = request.data.get("email_theme") or request.GET.get("email_theme") or "dark"
            email_base_template = "base_notifier/email_dark.html" if email_theme == "dark" else "base_notifier/email.html"
            whatsapp_links = extract_whatsapp_links(body)
            context = {
                "recipient_obj": recipient.recipient,
                "email_address": email_address.email,
                "subject": subject,
                "body_html": body_html,
                "body_text": body_text,
                "email_base_template": email_base_template,
                "email_theme": email_theme,
                "whatsapp_links": whatsapp_links,
            }
            rendered_html = render_to_string("notifier/campaign/email.html", context)
            # Use inline-rendered HTML to avoid MJML/template resolution issues at send time.
            em = Emailer(subject, [email_address.email], template=None, context={}, final_message=rendered_html)
            em.send()
            recipient.status = CampaignRecipient.STATUS_SENT
            recipient.attempted_at = timezone.now()
            recipient.sent_at = timezone.now()
            recipient.last_error = ""
            recipient.save(update_fields=["status", "attempted_at", "sent_at", "last_error", "updated_at"])
            create_notification(
                recipient=email_address.recipient or recipient,
                text=body,
                type="email",
                subject=subject,
                data={"campaign_id": recipient.campaign_id, "email": email_address.email, "recipient_id": recipient.id},
            )
            return Response({"sent": True, "recipient_id": recipient.id, "email": email_address.email})
        except Exception as exc:  # noqa: BLE001
            recipient.status = CampaignRecipient.STATUS_FAILED
            recipient.attempted_at = timezone.now()
            recipient.last_error = str(exc)
            recipient.save(update_fields=["status", "attempted_at", "last_error", "updated_at"])
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class EmailRecipientUpdateAPIView(APIView):
    """Update subject/body for a single campaign recipient (manual edit)."""

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Update email campaign recipient content",
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request, recipient_id: int):
        recipient = get_object_or_404(
            CampaignRecipient.objects.select_related("campaign", "email_address", "recipient"),
            pk=recipient_id,
        )
        data = request.data or {}
        subject = data.get("subject", recipient.subject)
        body_html = data.get("body_html", recipient.body_html)
        body_text = data.get("body_text", recipient.body_text)

        recipient.subject = subject or ""
        recipient.body_html = body_html or ""
        recipient.body_text = body_text or ""
        # Keep status as-is unless explicitly provided; default to ready
        status_override = data.get("status")
        if status_override in dict(CampaignRecipient.STATUS_CHOICES):
            recipient.status = status_override
        elif recipient.status in [CampaignRecipient.STATUS_PENDING, CampaignRecipient.STATUS_RENDERED]:
            recipient.status = CampaignRecipient.STATUS_READY
        recipient.save(update_fields=["subject", "body_html", "body_text", "status", "updated_at"])
        return Response(
            {
                "id": recipient.id,
                "subject": recipient.subject,
                "body_html": recipient.body_html,
                "body_text": recipient.body_text,
                "status": recipient.status,
            }
        )


class WhatsAppRecipientSendAPIView(APIView):
    """Send a single WhatsApp campaign recipient after manual review."""

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Send single WhatsApp campaign recipient (manual approve)",
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request, recipient_id: int):
        recipient = get_object_or_404(
            WhatsAppCampaignRecipient.objects.select_related("campaign", "lead", "whatsapp_contact"),
            pk=recipient_id,
        )
        wa_contact = getattr(recipient, "whatsapp_contact", None)
        chat_id = getattr(wa_contact, "chat_id", None) or _first_phone_from_lead(recipient.lead)
        if not chat_id:
            return Response({"error": "No chat_id/phone for recipient"}, status=status.HTTP_400_BAD_REQUEST)

        text = recipient.rendered_text
        media_url = recipient.media_url
        if not text:
            return Response({"error": "No message content to send"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            client = WahaClient()
        except Exception as exc:  # noqa: BLE001
            return Response({"error": "Failed to init WAHA client", "details": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payload_text = compose_whatsapp_text(text, media_url)
            result = client.send_text(chat_id=chat_id, text=payload_text)
            recipient.attempts += 1
            if result.get("success"):
                recipient.status = "sent"
                recipient.message_id = result.get("response", {}).get("id")
                recipient.error = None
                recipient.sent_at = timezone.now()
                recipient.save(update_fields=["status", "message_id", "error", "sent_at", "attempts", "updated_at"])
                create_notification(
                    recipient=recipient.lead,
                    text=text,
                    type="whatsapp",
                    data={"campaign_id": recipient.campaign_id, "lead_id": recipient.lead_id, "chat_id": chat_id},
                )
                return Response({"sent": True, "recipient_id": recipient.id, "chat_id": chat_id})
            recipient.status = "failed"
            recipient.error = str(result)
            recipient.save(update_fields=["status", "error", "attempts", "updated_at"])
            return Response({"error": str(result)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            recipient.status = "failed"
            recipient.error = str(exc)
            recipient.attempts += 1
            recipient.save(update_fields=["status", "error", "attempts", "updated_at"])
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
