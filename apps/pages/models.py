from django.db import models
from django.contrib.auth.models import User

# Create your models here.

class Product(models.Model):
    
    id    = models.AutoField(primary_key=True)
    name  = models.CharField(max_length = 100) 
    info  = models.CharField(max_length = 100, default = '')
    price = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return self.name


class UserTelegramCredential(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="telegram_credentials")
    n8n_credential_id = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    token = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.name} ({self.n8n_credential_id})"


class UserWhatsAppInstance(models.Model):
    STATUS_CHOICES = [
        ("connecting", "Connecting"),
        ("connected", "Connected"),
        ("disconnected", "Disconnected"),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="whatsapp_instances")
    instance_name = models.CharField(max_length=255, unique=True)
    instance_id = models.CharField(max_length=64, blank=True, null=True)
    whatsapp_number = models.CharField(max_length=20)
    hash_key = models.CharField(max_length=64, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="connecting")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.instance_name} ({self.whatsapp_number})"


class N8NExecutionSnapshot(models.Model):
    """
    Stores parsed execution metadata from the n8n mirror so we can display
    token/cost history without repeatedly parsing large payloads.
    """
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="n8n_execution_snapshots")
    workflow_id = models.CharField(max_length=64, db_index=True)
    execution_id = models.BigIntegerField(unique=True)
    status = models.CharField(max_length=64, blank=True, default="")
    mode = models.CharField(max_length=64, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True, db_index=True)
    stopped_at = models.DateTimeField(null=True, blank=True)

    tokens_total = models.IntegerField(null=True, blank=True)
    tokens_prompt = models.IntegerField(null=True, blank=True)
    tokens_completion = models.IntegerField(null=True, blank=True)
    usage_raw = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-started_at", "-execution_id")
        indexes = [
            models.Index(fields=["workflow_id", "started_at"]),
            models.Index(fields=["user", "started_at"]),
        ]

    def __str__(self):
        return f"Exec {self.execution_id} ({self.workflow_id})"
