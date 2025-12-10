from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
import json

from . import models


class ReadOnlyAdminMixin:
    """Mixin that disables create/update/delete operations in the admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def get_list_display(self, request):
        """Show every DB column to make the mirror fully explorable."""
        return [field.name for field in self.model._meta.fields]

    def get_list_display_links(self, request, list_display):
        return list_display[:1] or super().get_list_display_links(request, list_display)

    actions = None


class JsonPreviewMixin:
    json_preview_length = 80

    def _short_json(self, value, length=None):
        length = length or self.json_preview_length
        try:
            text = json.dumps(value, ensure_ascii=False)
        except Exception:
            text = str(value)
        if len(text) > length:
            return f"{text[:length]}…"
        return text

    def _pretty_json_text(self, value):
        try:
            return json.dumps(value, indent=2, ensure_ascii=False)
        except Exception:
            return str(value)

    def _pretty_json(self, value):
        if value in (None, ""):
            return mark_safe("<pre class='json-block'><em>None</em></pre>")
        formatted = self._pretty_json_text(value)
        return format_html("<pre class='json-block'>{}</pre>", formatted)

    def _json_preview(self, value, length=None):
        short = self._short_json(value, length)
        formatted = self._pretty_json_text(value)
        return format_html(
            "<span class='json-preview' data-json='{0}' title='Click to view JSON'>{1}</span>",
            formatted,
            short,
        )


@admin.register(models.WorkflowEntity)
class WorkflowAdmin(ReadOnlyAdminMixin, JsonPreviewMixin, admin.ModelAdmin):
    search_fields = ("id", "name", "description")
    list_filter = ("active", "isArchived")
    ordering = ("-updatedAt",)
    list_display = (
        "id",
        "name",
        "active",
        "isArchived",
        "triggerCount",
        "parentFolderId",
        "versionCounter",
        "createdAt",
        "updatedAt",
        "nodes_preview",
        "connections_preview",
    )
    readonly_json_fields = (
        "pretty_nodes",
        "pretty_connections",
        "pretty_settings",
        "pretty_staticData",
        "pretty_pinData",
        "pretty_meta",
    )
    change_list_template = "admin/n8n_mirror/workflowentity/change_list.html"

    def get_readonly_fields(self, request, obj=None):
        base = super().get_readonly_fields(request, obj)
        return list(base) + list(self.readonly_json_fields)

    def nodes_preview(self, obj):
        return self._json_preview(obj.nodes)

    nodes_preview.short_description = "nodes"

    def connections_preview(self, obj):
        return self._json_preview(obj.connections)

    connections_preview.short_description = "connections"

    def pretty_nodes(self, obj):
        return self._pretty_json(obj.nodes)

    def pretty_connections(self, obj):
        return self._pretty_json(obj.connections)

    def pretty_settings(self, obj):
        return self._pretty_json(obj.settings)

    def pretty_staticData(self, obj):
        return self._pretty_json(obj.staticData)

    def pretty_pinData(self, obj):
        return self._pretty_json(obj.pinData)

    def pretty_meta(self, obj):
        return self._pretty_json(obj.meta)

    def get_list_display(self, request):
        # Use the curated list_display above (ignore global all-field fallback)
        return self.list_display


@admin.register(models.ExecutionEntity)
class ExecutionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    search_fields = ("id", "workflowId", "status", "mode")
    list_filter = ("status", "finished", "mode")
    ordering = ("-createdAt",)


@admin.register(models.ExecutionData)
class ExecutionDataAdmin(ReadOnlyAdminMixin, JsonPreviewMixin, admin.ModelAdmin):
    search_fields = ("executionId__id",)
    ordering = ("-executionId",)
    list_display = ("executionId", "workflowData_preview", "data_preview")
    readonly_json_fields = ("pretty_workflowData", "pretty_data")
    change_list_template = "admin/n8n_mirror/executiondata/change_list.html"

    def get_readonly_fields(self, request, obj=None):
        base = super().get_readonly_fields(request, obj)
        return list(base) + list(self.readonly_json_fields)

    def workflowData_preview(self, obj):
        return self._json_preview(obj.workflowData)

    workflowData_preview.short_description = "workflowData"

    def data_preview(self, obj):
        return self._json_preview(obj.data)

    data_preview.short_description = "data"

    def pretty_workflowData(self, obj):
        return self._pretty_json(obj.workflowData)

    def pretty_data(self, obj):
        return self._pretty_json(obj.data)

    def get_list_display(self, request):
        return self.list_display


@admin.register(models.ExecutionAnnotations)
class ExecutionAnnotationsAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    search_fields = ("executionId__id", "note")
    ordering = ("-updatedAt",)


@admin.register(models.ExecutionMetadata)
class ExecutionMetadataAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    search_fields = ("executionId__id", "key", "value")
    ordering = ("executionId", "key")


@admin.register(models.CredentialsEntity)
class CredentialsAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    search_fields = ("id", "name", "type")
    list_filter = ("type", "isManaged")
    ordering = ("-updatedAt",)


@admin.register(models.UserEntity)
class UserAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    search_fields = ("id", "email", "firstName", "lastName")
    list_filter = ("roleSlug", "disabled", "mfaEnabled")
    ordering = ("-createdAt",)


@admin.register(models.TagEntity)
class TagAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    search_fields = ("id", "name")
    ordering = ("-updatedAt",)


@admin.register(models.SharedWorkflow)
class SharedWorkflowAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    search_fields = ("workflowId", "projectId", "role")
    ordering = ("-updatedAt",)


@admin.register(models.WebhookEntity)
class WebhookAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    search_fields = ("webhookPath", "method", "workflowId", "node")
    list_filter = ("method",)
    ordering = ("webhookPath",)


@admin.register(models.UserApiKeys)
class UserApiKeysAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    search_fields = ("id", "label", "apiKey", "userId__id")
    ordering = ("-updatedAt",)
