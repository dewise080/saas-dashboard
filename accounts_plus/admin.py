from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.contrib import messages
from django.utils.html import format_html

from .models import UserN8NProfile, OpenAIKeyPool


class UserN8NProfileInline(admin.StackedInline):
    """Inline admin for UserN8NProfile to show in User admin."""
    model = UserN8NProfile
    can_delete = False
    verbose_name = "N8N Profile"
    verbose_name_plural = "N8N Profile"
    extra = 0


class UserAdmin(BaseUserAdmin):
    """Extended User admin with N8N profile inline."""
    inlines = [UserN8NProfileInline]
    list_display = (
        'username',
        'email',
        'first_name',
        'last_name',
        'get_n8n_user_id',
        'get_api_key',
        'is_staff',
    )
    list_filter = (
        'is_active',
        'is_staff',
        'is_superuser',
        'date_joined',
    )
    search_fields = ('username', 'email', 'first_name', 'last_name', 'usern8nprofile__n8n_user_id')
    ordering = ('-date_joined',)
    list_select_related = ('usern8nprofile',)  # Optimize DB queries

    @admin.display(description='N8N User ID')
    def get_n8n_user_id(self, obj):
        if hasattr(obj, 'usern8nprofile'):
            return obj.usern8nprofile.n8n_user_id
        return '-'

    @admin.display(description='API Key')
    def get_api_key(self, obj):
        if hasattr(obj, 'usern8nprofile') and obj.usern8nprofile.api_key:
            return f"{obj.usern8nprofile.api_key[:12]}..."
        return '-'


@admin.register(UserN8NProfile)
class UserN8NProfileAdmin(admin.ModelAdmin):
    """Admin for UserN8NProfile model - spreadsheet style."""
    list_display = (
        'id',
        'user',
        'get_user_email',
        'n8n_user_id',
        'api_key_preview',
        'openai_key_preview',
        'created_at',
    )
    list_display_links = ('id', 'user')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'user__email', 'n8n_user_id')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
    list_per_page = 50

    @admin.display(description='Email')
    def get_user_email(self, obj):
        return obj.user.email

    @admin.display(description='API Key')
    def api_key_preview(self, obj):
        """Show first 8 chars of API key for security."""
        if obj.api_key:
            return f"{obj.api_key[:8]}..."
        return '-'

    @admin.display(description='OpenAI Key')
    def openai_key_preview(self, obj):
        """Show first 8 chars of OpenAI API key for security."""
        if obj.openai_api_key:
            return f"{obj.openai_api_key[:8]}..."
        return '-'


# Unregister the default User admin and register our custom one
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(OpenAIKeyPool)
class OpenAIKeyPoolAdmin(admin.ModelAdmin):
    """Admin for OpenAI API Key Pool - manage key inventory and assignments."""
    list_display = (
        'id',
        'key_preview',
        'status_badge',
        'assigned_to',
        'assigned_at',
        'is_active',
        'created_at',
    )
    list_display_links = ('id', 'key_preview')
    list_filter = (
        'is_active',
        ('assigned_to', admin.EmptyFieldListFilter),  # Filter by assigned/unassigned
        'created_at',
        'assigned_at',
    )
    search_fields = ('api_key', 'assigned_to__username', 'assigned_to__email', 'notes')
    readonly_fields = ('created_at', 'assigned_at', 'key_preview_full')
    ordering = ('-created_at',)
    list_per_page = 50
    autocomplete_fields = ['assigned_to']
    
    fieldsets = (
        (None, {
            'fields': ('api_key', 'key_preview_full')
        }),
        ('Assignment', {
            'fields': ('assigned_to', 'assigned_at')
        }),
        ('Status', {
            'fields': ('is_active', 'notes')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_active', 'mark_as_inactive', 'unassign_keys']

    @admin.display(description='API Key')
    def key_preview(self, obj):
        """Show truncated key for security."""
        if obj.api_key and len(obj.api_key) > 12:
            return f"{obj.api_key[:8]}...{obj.api_key[-4:]}"
        return "***"

    @admin.display(description='Full Key Preview')
    def key_preview_full(self, obj):
        """Show full key in detail view (readonly)."""
        if obj.api_key:
            return f"{obj.api_key[:12]}...{obj.api_key[-8:]}"
        return "-"

    @admin.display(description='Status')
    def status_badge(self, obj):
        """Show colored status badge."""
        if not obj.is_active:
            return format_html('<span style="color: red; font-weight: bold;">⛔ Inactive</span>')
        if obj.assigned_to:
            return format_html('<span style="color: green; font-weight: bold;">✓ Assigned</span>')
        return format_html('<span style="color: blue; font-weight: bold;">◉ Available</span>')

    @admin.action(description='Mark selected keys as active')
    def mark_as_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} keys marked as active.', messages.SUCCESS)

    @admin.action(description='Mark selected keys as inactive')
    def mark_as_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} keys marked as inactive.', messages.WARNING)

    @admin.action(description='Unassign selected keys (free them back to pool)')
    def unassign_keys(self, request, queryset):
        # Also clear the user's profile openai_api_key
        for key in queryset.filter(assigned_to__isnull=False):
            if hasattr(key.assigned_to, 'usern8nprofile'):
                key.assigned_to.usern8nprofile.openai_api_key = ''
                key.assigned_to.usern8nprofile.save(update_fields=['openai_api_key'])
        updated = queryset.update(assigned_to=None, assigned_at=None)
        self.message_user(request, f'{updated} keys unassigned and returned to pool.', messages.SUCCESS)

    def changelist_view(self, request, extra_context=None):
        """Add pool stats to the changelist view."""
        extra_context = extra_context or {}
        stats = OpenAIKeyPool.get_pool_stats()
        extra_context['pool_stats'] = stats
        extra_context['title'] = f"OpenAI API Keys Pool ({stats['available']} available / {stats['total']} total)"
        return super().changelist_view(request, extra_context=extra_context)
