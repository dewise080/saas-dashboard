import logging
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from django.apps import apps
from django.contrib import admin
from django.core.cache import cache
from django.db import models
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from core_dashboard.models import DashboardWidget

logger = logging.getLogger(__name__)

DATE_FIELD_CANDIDATES = [
    "created_at",
    "created",
    "created_on",
    "date_created",
    "timestamp",
    "inserted_at",
    "createdAt",
    "startedAt",
]

APP_DEFINITIONS = [
    {
        "key": "gmaps",
        "label": "Google Maps Leads",
        "models": [
            ("GmapsLead", "gmaps_leads"),
            ("ScrapeJob", "gmaps_leads"),
            ("WhatsAppContact", "gmaps_leads"),
        ],
    },
    {
        "key": "emailing",
        "label": "Email Infrastructure",
        "models": [
            ("EmailSend", "emailing"),
            ("EmailCampaign", "emailing"),
            ("EmailTemplate", "emailing"),
            ("Recipient", "emailing"),
        ],
    },
    {
        "key": "notifier",
        "label": "Notifier",
        "models": [
            ("NotificationEvent", "magic_notifier"),
        ],
    },
    {
        "key": "n8n",
        "label": "n8n Mirror",
        "models": [
            ("ExecutionEntity", "n8n_mirror"),
            ("WorkflowEntity", "n8n_mirror"),
            ("CredentialsEntity", "n8n_mirror"),
        ],
    },
    {
        "key": "explorer",
        "label": "SQL Explorer",
        "models": [
            ("Query", "explorer"),
            ("QueryLog", "explorer"),
        ],
    },
]


def _get_model(app_label: str, model_name: str) -> Optional[models.Model]:
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        logger.warning("Dashboard: model %s.%s not found", app_label, model_name)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Dashboard: error loading model %s.%s: %s", app_label, model_name, exc)
    return None


def _safe_count(model: models.Model) -> Optional[int]:
    try:
        return model._meta.default_manager.count()
    except Exception as exc:
        logger.warning("Dashboard: unable to count %s.%s: %s", model._meta.app_label, model.__name__, exc)
        return None


def _find_date_field(model: models.Model) -> Tuple[Optional[str], bool]:
    for field_name in DATE_FIELD_CANDIDATES:
        try:
            field = model._meta.get_field(field_name)
        except Exception:
            continue
        if isinstance(field, (models.DateField, models.DateTimeField)):
            return field_name, isinstance(field, models.DateTimeField)
    logger.warning("Dashboard: no timestamp field found for %s", model.__name__)
    return None, False


def _series_for_model(model: models.Model, label: str) -> List[Dict[str, object]]:
    field_name, is_datetime = _find_date_field(model)
    if not field_name:
        return []

    start_date = timezone.now().date() - timedelta(days=29)
    trunc_kwargs = {"tzinfo": timezone.get_current_timezone()} if is_datetime else {}
    filter_field = f"{field_name}__date__gte" if is_datetime else f"{field_name}__gte"

    try:
        rows = (
            model._meta.default_manager.filter(**{filter_field: start_date})
            .annotate(day=TruncDate(field_name, **trunc_kwargs))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )
        counts = {row["day"]: row["count"] for row in rows if row["day"] is not None}
    except Exception as exc:
        logger.warning("Dashboard: unable to build chart for %s (%s): %s", model.__name__, label, exc)
        return []

    series = []
    for offset in range(30):
        day = start_date + timedelta(days=offset)
        series.append({"date": day.isoformat(), "count": int(counts.get(day, 0) or 0)})
    return series


def build_dashboard_data() -> Dict[str, dict]:
    cache_key = "admin_dashboard_payload_v2"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    data: Dict[str, dict] = {"kpis": {}, "charts": {}, "apps": []}
    model_cache: Dict[str, Optional[models.Model]] = {}

    def get_model(app_label: str, model_name: str) -> Optional[models.Model]:
        key = f"{app_label}.{model_name}"
        if key not in model_cache:
            model_cache[key] = _get_model(app_label, model_name)
        return model_cache[key]

    metrics = [
        ("leads", "gmaps_leads", "GmapsLead"),
        ("scrape_jobs", "gmaps_leads", "ScrapeJob"),
        ("email_sends", "emailing", "EmailSend"),
        ("executions", "n8n_mirror", "ExecutionEntity"),
    ]

    for key, app_label, model_name in metrics:
        model = get_model(app_label, model_name)
        if not model:
            data["kpis"][key] = None
            continue
        data["kpis"][key] = _safe_count(model)

    # Notifier stats (sent vs failed)
    notifier_model = get_model("magic_notifier", "NotificationEvent")
    if notifier_model:
        try:
            data["kpis"]["notifier_sent"] = notifier_model.objects.filter(status="sent").count()
            data["kpis"]["notifier_failed"] = notifier_model.objects.filter(status="failed").count()
        except Exception as exc:
            logger.warning("Dashboard: unable to count notifier events: %s", exc)
            data["kpis"]["notifier_sent"] = None
            data["kpis"]["notifier_failed"] = None
    else:
        data["kpis"]["notifier_sent"] = None
        data["kpis"]["notifier_failed"] = None

    # Lead breakdown pies
    lead_model = get_model("gmaps_leads", "GmapsLead")
    if lead_model:
        try:
            total_leads = lead_model.objects.count()
            with_website = lead_model.objects.exclude(website__isnull=True).exclude(website="").count()
            with_emails = lead_model.objects.exclude(emails__isnull=True).exclude(emails="").count()

            wa = 0
            local = 0
            other = 0
            none = 0
            for lead in lead_model.objects.all().only("phone"):
                phone_type = getattr(lead, "phone_type", "none")
                if phone_type == "whatsapp":
                    wa += 1
                elif phone_type == "local":
                    local += 1
                elif phone_type == "other":
                    other += 1
                else:
                    none += 1

            data["charts"]["lead_phone_breakdown"] = {
                "total": total_leads,
                "whatsapp": wa,
                "local": local,
                "other": other,
                "none": none,
            }
            data["charts"]["lead_website_breakdown"] = {
                "total": total_leads,
                "with": with_website,
                "without": max(total_leads - with_website, 0),
            }
            data["charts"]["lead_email_breakdown"] = {
                "total": total_leads,
                "with": with_emails,
                "without": max(total_leads - with_emails, 0),
            }
        except Exception as exc:
            logger.warning("Dashboard: unable to build lead breakdown: %s", exc)
            data["charts"]["lead_phone_breakdown"] = {}
            data["charts"]["lead_website_breakdown"] = {}
            data["charts"]["lead_email_breakdown"] = {}
    else:
        data["charts"]["lead_phone_breakdown"] = {}
        data["charts"]["lead_website_breakdown"] = {}
        data["charts"]["lead_email_breakdown"] = {}

    # Custom widgets
    custom_widgets = []
    widgets = DashboardWidget.objects.filter(enabled=True).order_by("order", "id")
    for widget in widgets:
        model = None
        if widget.app_label and widget.model_name:
            model = get_model(widget.app_label, widget.model_name)
        widget_payload = {"id": widget.id, "title": widget.title, "type": widget.widget_type, "data": None}
        try:
            if widget.widget_type == "text":
                widget_payload["data"] = {"text": widget.text_content or ""}
            elif model:
                qs = model._meta.default_manager.all()
                if widget.filters:
                    try:
                        qs = qs.filter(**widget.filters)
                    except Exception as exc:  # defensive
                        logger.warning("Dashboard widget filter error %s: %s", widget.title, exc)
                if widget.widget_type == "kpi":
                    widget_payload["data"] = {"value": qs.count()}
                elif widget.widget_type == "pie":
                    if widget.group_field:
                        rows = qs.values(widget.group_field).annotate(count=Count("id")).order_by("-count")[:12]
                        widget_payload["data"] = {
                            "labels": [row[widget.group_field] or "—" for row in rows],
                            "values": [row["count"] for row in rows],
                        }
                elif widget.widget_type == "line":
                    field_name, is_datetime = _find_date_field(model)
                    if field_name:
                        start_date = timezone.now().date() - timedelta(days=29)
                        trunc_kwargs = {"tzinfo": timezone.get_current_timezone()} if is_datetime else {}
                        filter_field = f"{field_name}__date__gte" if is_datetime else f"{field_name}__gte"
                        rows = (
                            qs.filter(**{filter_field: start_date})
                            .annotate(day=TruncDate(field_name, **trunc_kwargs))
                            .values("day")
                            .annotate(count=Count("id"))
                            .order_by("day")
                        )
                        counts = {row["day"]: row["count"] for row in rows if row["day"] is not None}
                        series = []
                        for offset in range(30):
                            day = start_date + timedelta(days=offset)
                            series.append({"date": day.isoformat(), "count": int(counts.get(day, 0) or 0)})
                        widget_payload["data"] = series
                elif widget.widget_type == "table":
                    fields = widget.fields or ["id"]
                    rows = qs.values(*fields)[: widget.limit or 5]
                    widget_payload["data"] = {"fields": fields, "rows": list(rows)}
            custom_widgets.append(widget_payload)
        except Exception as exc:  # defensive
            logger.warning("Dashboard: custom widget %s failed: %s", widget.title, exc)
            continue
    data["custom_widgets"] = custom_widgets

    chart_targets = [
        ("leads_30d", "gmaps_leads", "GmapsLead"),
        ("jobs_30d", "gmaps_leads", "ScrapeJob"),
        ("email_sends_30d", "emailing", "EmailSend"),
        ("executions_30d", "n8n_mirror", "ExecutionEntity"),
        ("notifier_30d", "magic_notifier", "NotificationEvent"),
    ]

    for key, app_label, model_name in chart_targets:
        model = get_model(app_label, model_name)
        if not model:
            data["charts"][key] = []
            continue
        data["charts"][key] = _series_for_model(model, key)

    app_cards: List[dict] = []
    for app_def in APP_DEFINITIONS:
        models_info = []
        for model_name, app_label in app_def["models"]:
            model = get_model(app_label, model_name)
            if not model:
                continue
            count = _safe_count(model)
            admin_url = None
            try:
                admin_url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
            except Exception:
                admin_url = None
            models_info.append(
                {
                    "label": model._meta.verbose_name_plural.title(),
                    "count": count,
                    "admin_url": admin_url,
                }
            )
        if models_info:
            app_cards.append(
                {
                    "key": app_def["key"],
                    "label": app_def["label"],
                    "models": models_info,
                }
            )
    data["apps"] = app_cards

    cache.set(cache_key, data, timeout=60)
    return data


def patch_admin_dashboard() -> None:
    if getattr(admin.site, "_custom_dashboard_patched", False):
        return

    original_each_context = admin.site.each_context
    admin.site.index_template = "admin/custom_index.html"

    def wrapped_each_context(request):
        context = original_each_context(request)
        is_admin_index = False
        try:
            index_path = reverse("admin:index")
            current_path = (request.path or "").rstrip("/") if request else ""
            is_admin_index = current_path == index_path.rstrip("/")
        except Exception:
            is_admin_index = False

        if is_admin_index:
            try:
                context["dashboard"] = build_dashboard_data()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Dashboard: failed to build dashboard context: %s", exc)
                context.setdefault("dashboard", {"kpis": {}, "charts": {}})
        return context

    admin.site.each_context = wrapped_each_context
    admin.site._custom_dashboard_patched = True
