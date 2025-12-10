from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
import csv
import logging

from .models import ScrapeJob, GmapsLead, EmailTemplate
from .serializers import (
    ScrapeJobSerializer, ScrapeJobCreateSerializer,
    GmapsLeadSerializer, GmapsLeadListSerializer,
    LeadContextSerializer, 
    EmailTemplateSerializer, EmailTemplateListSerializer,
    EmailTemplateCreateSerializer, EmailTemplateStatusUpdateSerializer
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

class ScrapeJobViewSet(viewsets.ModelViewSet):
    """API ViewSet for ScrapeJob."""
    queryset = ScrapeJob.objects.all()
    serializer_class = ScrapeJobSerializer
    permission_classes = [IsAuthenticated]
    
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
    
    @action(detail=True, methods=['post'])
    def refresh(self, request, pk=None):
        """Refresh job status from API."""
        job = self.get_object()
        job = refresh_job_status(job)
        return Response(ScrapeJobSerializer(job).data)
    
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
    
    @action(detail=True, methods=['get'])
    def leads(self, request, pk=None):
        """Get leads for this job."""
        job = self.get_object()
        leads = job.leads.all()
        serializer = GmapsLeadListSerializer(leads, many=True)
        return Response(serializer.data)


class GmapsLeadViewSet(viewsets.ReadOnlyModelViewSet):
    """API ViewSet for GmapsLead (read-only)."""
    queryset = GmapsLead.objects.all()
    serializer_class = GmapsLeadSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter leads by user's jobs."""
        qs = GmapsLead.objects.filter(job__created_by=self.request.user)
        
        # Filter by job
        job_id = self.request.query_params.get('job')
        if job_id:
            qs = qs.filter(job_id=job_id)
        
        # Filter by category
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category__icontains=category)
        
        # Filter by min rating
        min_rating = self.request.query_params.get('min_rating')
        if min_rating:
            qs = qs.filter(review_rating__gte=float(min_rating))
        
        return qs
    
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

class LeadContextAPIView(APIView):
    """
    API endpoint for AI to fetch comprehensive lead context.
    
    GET /api/gmaps-leads/{lead_id}/context/
    
    Returns all available business information for personalized email generation:
    - Basic business info (name, category, address, phone)
    - Website scraped data (emails, services, descriptions)
    - WhatsApp contacts if available
    - Reviews and ratings
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        operation_id='getLeadContext',
        summary='Get comprehensive lead context for AI email generation',
        description='''
        Retrieves all available business information for a lead, designed for AI consumption.
        
        This endpoint aggregates:
        - Basic business info from Google Maps
        - Scraped website content and extracted emails
        - WhatsApp contact information
        - Reviews and ratings
        
        Use this data to generate personalized outreach emails.
        ''',
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
        lead = get_object_or_404(
            GmapsLead.objects.select_related('website_data').prefetch_related('whatsapp_contacts'),
            pk=lead_id,
            job__created_by=request.user
        )
        serializer = LeadContextSerializer(lead)
        return Response(serializer.data)


class LeadEmailTemplateAPIView(APIView):
    """
    API endpoint for AI to create/update email templates for a lead.
    
    POST /api/gmaps-leads/{lead_id}/email-template/
    GET /api/gmaps-leads/{lead_id}/email-templates/
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        operation_id='getLeadEmailTemplates',
        summary='List email templates for a lead',
        description='Returns all email templates created for this lead.',
        parameters=[
            OpenApiParameter(
                name='lead_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description='The ID of the lead'
            )
        ],
        responses={200: EmailTemplateListSerializer(many=True)},
        tags=['AI Email Generation']
    )
    def get(self, request, lead_id):
        """List email templates for a lead."""
        lead = get_object_or_404(GmapsLead, pk=lead_id, job__created_by=request.user)
        templates = lead.email_templates.all()
        serializer = EmailTemplateListSerializer(templates, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        operation_id='createLeadEmailTemplate',
        summary='Create email template for a lead (AI endpoint)',
        description='''
        Creates a new email template for the specified lead.
        
        This endpoint is designed for AI agents to submit generated email content.
        
        **Workflow:**
        1. AI fetches lead context via GET /api/gmaps-leads/{id}/context/
        2. AI generates personalized email
        3. AI posts to this endpoint with mark_ready=true
        4. Signal emitted when template is ready for human review
        
        **mark_ready parameter:**
        - If true, template status is set to 'ready' and a signal is emitted
        - If false (default), template is saved as 'draft'
        ''',
        parameters=[
            OpenApiParameter(
                name='lead_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description='The ID of the lead to create template for'
            )
        ],
        request=EmailTemplateCreateSerializer,
        responses={
            201: EmailTemplateSerializer,
            400: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                'AI Generated Email',
                value={
                    'subject': 'Partnership opportunity for {{business_name}}',
                    'body_html': '<h1>Hello {{recipient_name}},</h1><p>I noticed your business...</p>',
                    'body_plain': 'Hello {{recipient_name}},\n\nI noticed your business...',
                    'template_type': 'outreach',
                    'mark_ready': True,
                    'is_personalized': True,
                    'ai_model': 'gpt-4',
                    'ai_generation_time': 2.5,
                },
                request_only=True,
            )
        ],
        tags=['AI Email Generation']
    )
    def post(self, request, lead_id):
        """Create email template for a lead."""
        lead = get_object_or_404(GmapsLead, pk=lead_id, job__created_by=request.user)
        
        serializer = EmailTemplateCreateSerializer(
            data=request.data,
            context={'lead': lead, 'request': request}
        )
        
        if serializer.is_valid():
            template = serializer.save(created_by=request.user)
            return Response(
                EmailTemplateSerializer(template).data,
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
    permission_classes = [IsAuthenticated]
    
    def get_template(self, request, template_id):
        """Get template with permission check."""
        return get_object_or_404(
            EmailTemplate,
            pk=template_id,
            lead__job__created_by=request.user
        )
    
    @extend_schema(
        operation_id='getEmailTemplate',
        summary='Get email template details',
        responses={200: EmailTemplateSerializer},
        tags=['Email Templates']
    )
    def get(self, request, template_id):
        """Get email template."""
        template = self.get_template(request, template_id)
        serializer = EmailTemplateSerializer(template)
        return Response(serializer.data)
    
    @extend_schema(
        operation_id='updateEmailTemplate',
        summary='Update email template',
        request=EmailTemplateCreateSerializer,
        responses={200: EmailTemplateSerializer},
        tags=['Email Templates']
    )
    def put(self, request, template_id):
        """Update email template."""
        template = self.get_template(request, template_id)
        serializer = EmailTemplateCreateSerializer(
            template,
            data=request.data,
            partial=True,
            context={'lead': template.lead, 'request': request}
        )
        
        if serializer.is_valid():
            template = serializer.save()
            return Response(EmailTemplateSerializer(template).data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        operation_id='deleteEmailTemplate',
        summary='Delete email template',
        responses={204: None},
        tags=['Email Templates']
    )
    def delete(self, request, template_id):
        """Delete email template."""
        template = self.get_template(request, template_id)
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EmailTemplateStatusAPIView(APIView):
    """
    API endpoint for updating email template status.
    
    PATCH /api/email-templates/{id}/status/
    
    Allows changing status and emits signals for workflow automation.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        operation_id='updateEmailTemplateStatus',
        summary='Update email template status',
        description='''
        Updates the status of an email template.
        
        **Status values:**
        - draft: Template is being edited
        - ready: Template is ready for human review (emits signal)
        - approved: Human has approved for sending (emits signal)
        - rejected: Human has rejected the template
        
        **Signals emitted:**
        - When status changes to 'ready': email_template_ready signal
        - When status changes to 'approved': email_template_approved signal
        ''',
        request=EmailTemplateStatusUpdateSerializer,
        responses={200: EmailTemplateSerializer},
        tags=['Email Templates']
    )
    def patch(self, request, template_id):
        """Update email template status."""
        template = get_object_or_404(
            EmailTemplate,
            pk=template_id,
            lead__job__created_by=request.user
        )
        
        serializer = EmailTemplateStatusUpdateSerializer(data=request.data)
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
            
            return Response(EmailTemplateSerializer(template).data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class EmailTemplateListAPIView(APIView):
    """
    API endpoint for listing all email templates.
    
    GET /api/email-templates/
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        operation_id='listEmailTemplates',
        summary='List all email templates',
        description='Returns all email templates for the current user.',
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
        responses={200: EmailTemplateListSerializer(many=True)},
        tags=['Email Templates']
    )
    def get(self, request):
        """List all email templates."""
        templates = EmailTemplate.objects.filter(
            lead__job__created_by=request.user
        ).select_related('lead')
        
        # Filters
        status_filter = request.query_params.get('status')
        if status_filter:
            templates = templates.filter(status=status_filter)
        
        lead_id = request.query_params.get('lead_id')
        if lead_id:
            templates = templates.filter(lead_id=lead_id)
        
        serializer = EmailTemplateListSerializer(templates, many=True)
        return Response(serializer.data)


class LeadsWithEmailsAPIView(APIView):
    """
    API endpoint to list leads that have available emails.
    
    GET /api/gmaps-leads/with-emails/
    
    Useful for AI to find leads that can receive outreach emails.
    """
    permission_classes = [IsAuthenticated]
    
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
        from django.db.models import Q, Exists, OuterRef
        
        # Start with leads that have website data with emails
        leads = GmapsLead.objects.filter(
            job__created_by=request.user
        ).filter(
            Q(website_data__emails__len__gt=0) |  # Has emails from website scraping
            Q(emails__isnull=False)  # Or has emails field
        ).select_related('website_data').distinct()
        
        # Filter to leads without templates
        without_template = request.query_params.get('without_template')
        if without_template and without_template.lower() == 'true':
            leads = leads.exclude(
                Exists(EmailTemplate.objects.filter(lead=OuterRef('pk')))
            )
        
        # Filter by category
        category = request.query_params.get('category')
        if category:
            leads = leads.filter(category__icontains=category)
        
        # Limit
        limit = int(request.query_params.get('limit', 50))
        leads = leads[:limit]
        
        serializer = GmapsLeadListSerializer(leads, many=True)
        return Response(serializer.data)

