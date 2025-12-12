from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
import csv
import logging

from .models import ScrapeJob, GmapsLead, CustomizedContact
from .serializers import (
    ScrapeJobSerializer, ScrapeJobCreateSerializer,
    GmapsLeadSerializer, GmapsLeadListSerializer,
    LeadContextSerializer, 
    CustomizedContactSerializer, CustomizedContactListSerializer,
    CustomizedContactCreateSerializer
)
from .services import (
    create_scrape_job, refresh_job_status, import_job_results,
    GmapsScraperService
)
from .signals import email_template_ready, email_template_approved

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
