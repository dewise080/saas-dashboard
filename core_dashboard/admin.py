import json

from django.contrib import admin
from django.http import JsonResponse
from django.urls import path

from .models import DashboardWidget


@admin.register(DashboardWidget)
class DashboardWidgetAdmin(admin.ModelAdmin):
    list_display = ["title", "widget_type", "app_label", "model_name", "enabled", "order", "updated_at"]
    list_filter = ["widget_type", "enabled"]
    search_fields = ["title", "app_label", "model_name", "group_field"]
    ordering = ["order", "id"]

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "reorder/",
                self.admin_site.admin_view(self.reorder_view),
                name="core_dashboard_dashboardwidget_reorder",
            ),
            path(
                "delete_ajax/<int:pk>/",
                self.admin_site.admin_view(self.delete_ajax_view),
                name="core_dashboard_dashboardwidget_delete_ajax",
            ),
        ]
        return custom + urls

    def reorder_view(self, request):
        if request.method != "POST":
            return JsonResponse({"error": "POST required"}, status=405)
        try:
            payload = json.loads(request.body.decode("utf-8"))
            order = payload.get("order", [])
        except Exception as exc:  # noqa: BLE001
            return JsonResponse({"error": str(exc)}, status=400)
        for idx, pk in enumerate(order):
            DashboardWidget.objects.filter(pk=pk).update(order=idx)
        return JsonResponse({"ok": True})

    def delete_ajax_view(self, request, pk):
        if request.method != "POST":
            return JsonResponse({"error": "POST required"}, status=405)
        try:
            DashboardWidget.objects.filter(pk=pk).delete()
            return JsonResponse({"ok": True})
        except Exception as exc:  # noqa: BLE001
            return JsonResponse({"error": str(exc)}, status=400)
