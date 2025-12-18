from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class CoreDashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core_dashboard"
    verbose_name = "Admin Dashboard"

    def ready(self) -> None:
        # Patch the admin index with KPI + chart context on startup.
        try:
            from .admin_dashboard import patch_admin_dashboard

            patch_admin_dashboard()
            logger.info("Admin dashboard patch is active.")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Admin dashboard patch failed to initialize: %s", exc)

