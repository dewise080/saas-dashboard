from django.contrib.auth.models import User
from django.db import models, transaction


class OpenAIKeyPool(models.Model):
    """
    Pool of pre-loaded OpenAI API keys.
    Keys are assigned to users on signup and stick with them forever.
    """
    api_key = models.CharField(max_length=255, unique=True)
    assigned_to = models.OneToOneField(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='assigned_openai_key'
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True, help_text="Disable key if it's revoked or invalid")
    notes = models.TextField(blank=True, default="", help_text="Admin notes about this key")

    class Meta:
        verbose_name = "OpenAI API Key"
        verbose_name_plural = "OpenAI API Keys Pool"
        ordering = ['created_at']

    def __str__(self):
        key_preview = f"{self.api_key[:8]}...{self.api_key[-4:]}" if len(self.api_key) > 12 else "***"
        if self.assigned_to:
            return f"{key_preview} -> {self.assigned_to.username}"
        return f"{key_preview} (unassigned)"

    @property
    def is_assigned(self):
        return self.assigned_to is not None

    @classmethod
    def get_next_available_key(cls):
        """Get the next unassigned, active key from the pool."""
        return cls.objects.filter(
            assigned_to__isnull=True,
            is_active=True
        ).first()

    @classmethod
    def assign_to_user(cls, user):
        """
        Assign the next available key to a user.
        Returns the OpenAIKeyPool instance or None if no keys available.
        Thread-safe with select_for_update.
        """
        from django.utils import timezone
        
        with transaction.atomic():
            # Lock the row to prevent race conditions
            key = cls.objects.select_for_update().filter(
                assigned_to__isnull=True,
                is_active=True
            ).first()
            
            if key:
                key.assigned_to = user
                key.assigned_at = timezone.now()
                key.save(update_fields=['assigned_to', 'assigned_at'])
                
                # Also update user's profile if it exists
                if hasattr(user, 'usern8nprofile'):
                    user.usern8nprofile.openai_api_key = key.api_key
                    user.usern8nprofile.save(update_fields=['openai_api_key'])
                
                return key
            return None

    @classmethod
    def get_user_key(cls, user):
        """Get the key assigned to a specific user."""
        try:
            return cls.objects.get(assigned_to=user)
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_pool_stats(cls):
        """Get stats about the key pool."""
        total = cls.objects.count()
        assigned = cls.objects.filter(assigned_to__isnull=False).count()
        available = cls.objects.filter(assigned_to__isnull=True, is_active=True).count()
        inactive = cls.objects.filter(is_active=False).count()
        return {
            'total': total,
            'assigned': assigned,
            'available': available,
            'inactive': inactive,
        }


class UserN8NProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    n8n_user_id = models.CharField(max_length=64)
    api_key = models.CharField(max_length=255, blank=True, default="")
    openai_api_key = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} -> {self.n8n_user_id}"
