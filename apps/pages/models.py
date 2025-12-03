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
