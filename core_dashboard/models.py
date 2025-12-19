from django.db import models


class DashboardWidget(models.Model):
    WIDGET_TYPES = [
        ("kpi", "KPI"),
        ("pie", "Pie"),
        ("line", "Line"),
        ("table", "Table"),
        ("text", "Text"),
    ]

    title = models.CharField(max_length=255)
    widget_type = models.CharField(max_length=20, choices=WIDGET_TYPES)
    app_label = models.CharField(max_length=100, blank=True, null=True)
    model_name = models.CharField(max_length=100, blank=True, null=True)
    group_field = models.CharField(max_length=100, blank=True, null=True)
    fields = models.JSONField(default=list, blank=True)
    filters = models.JSONField(default=dict, blank=True)
    limit = models.PositiveIntegerField(default=5)
    text_content = models.TextField(blank=True, null=True)
    order = models.IntegerField(default=0)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.title} ({self.widget_type})"
