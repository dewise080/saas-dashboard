from django.conf import settings
from django.db import models
from django.utils import timezone


class EmailTemplate(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    subject_template = models.CharField(max_length=500)
    html_template = models.TextField(help_text="HTML template; can use Django template syntax for context rendering.")
    text_template = models.TextField(blank=True, help_text="Optional text version; auto-generated when empty.")
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Email Template"
        verbose_name_plural = "Email Templates"

    def __str__(self) -> str:
        return self.name


class EmailCampaign(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("ready", "Ready"),
        ("running", "Running"),
        ("paused", "Paused"),
        ("completed", "Completed"),
        ("stopped", "Stopped"),
    ]

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    template = models.ForeignKey(EmailTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="campaigns")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    default_from_email = models.EmailField(blank=True)
    default_from_name = models.CharField(max_length=255, blank=True)
    provider_alias = models.CharField(max_length=100, blank=True, help_text="Matches a key from EMAIL_PROVIDERS.")
    default_context = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    expected_recipients = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    last_dispatched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Email Campaign"
        verbose_name_plural = "Email Campaigns"

    def __str__(self) -> str:
        return self.name

    @property
    def total_recipients(self) -> int:
        base = self.expected_recipients or self.recipients.count()
        return base

    @property
    def progress_percent(self) -> float:
        total = self.total_recipients
        if not total:
            return 0.0
        completed = self.sent_count + self.failed_count + self.skipped_count
        return round((completed / total) * 100, 2)

    def refresh_counters(self, commit: bool = True) -> None:
        qs = self.recipients.all()
        totals = qs.values("status").annotate(count=models.Count("id"))
        sent = failed = skipped = 0
        for row in totals:
            if row["status"] == CampaignRecipient.STATUS_SENT:
                sent = row["count"]
            elif row["status"] == CampaignRecipient.STATUS_FAILED:
                failed = row["count"]
            elif row["status"] == CampaignRecipient.STATUS_SKIPPED:
                skipped = row["count"]
        self.sent_count = sent
        self.failed_count = failed
        self.skipped_count = skipped
        if commit:
            self.save(update_fields=["sent_count", "failed_count", "skipped_count", "updated_at"])


class Recipient(models.Model):
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    company = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Recipient"
        verbose_name_plural = "Recipients"

    def __str__(self) -> str:
        full = self.full_name
        return full or self.company or f"Recipient {self.pk}"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class EmailAddress(models.Model):
    recipient = models.ForeignKey(Recipient, on_delete=models.CASCADE, related_name="email_addresses")
    email = models.EmailField()
    label = models.CharField(max_length=50, blank=True, help_text="work, personal, billing, etc.")
    is_primary = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("recipient", "email")
        ordering = ["-is_primary", "email"]
        verbose_name = "Email Address"
        verbose_name_plural = "Email Addresses"
        indexes = [models.Index(fields=["email"])]

    def __str__(self) -> str:
        return self.email


class CampaignRecipient(models.Model):
    STATUS_PENDING = "pending"
    STATUS_READY = "ready"
    STATUS_RENDERED = "rendered"
    STATUS_SENDING = "sending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_READY, "Ready"),
        (STATUS_RENDERED, "Rendered"),
        (STATUS_SENDING, "Sending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SKIPPED, "Skipped"),
    ]

    campaign = models.ForeignKey(EmailCampaign, on_delete=models.CASCADE, related_name="recipients")
    recipient = models.ForeignKey(Recipient, on_delete=models.SET_NULL, null=True, blank=True, related_name="campaign_links")
    email_address = models.ForeignKey(EmailAddress, on_delete=models.SET_NULL, null=True, blank=True, related_name="campaign_links")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    subject = models.CharField(max_length=500, blank=True)
    body_html = models.TextField(blank=True)
    body_text = models.TextField(blank=True)
    context = models.JSONField(default=dict, blank=True)
    provider_alias = models.CharField(max_length=100, blank=True)
    message_id = models.CharField(max_length=255, blank=True)
    last_error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    attempted_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("campaign", "email_address")
        ordering = ["-created_at"]
        verbose_name = "Campaign Recipient"
        verbose_name_plural = "Campaign Recipients"

    def __str__(self) -> str:
        return f"{self.campaign.name} → {self.email_address or self.recipient}"


class EmailSend(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SKIPPED, "Skipped"),
    ]

    to_email = models.EmailField()
    subject = models.CharField(max_length=500)
    html_body = models.TextField()
    text_body = models.TextField(blank=True)
    context = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    provider_alias = models.CharField(max_length=100, blank=True)
    backend_path = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    message_id = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    campaign = models.ForeignKey(EmailCampaign, on_delete=models.SET_NULL, null=True, blank=True, related_name="sends")
    campaign_recipient = models.ForeignKey(CampaignRecipient, on_delete=models.SET_NULL, null=True, blank=True, related_name="sends")
    recipient = models.ForeignKey(Recipient, on_delete=models.SET_NULL, null=True, blank=True, related_name="sends")
    email_address = models.ForeignKey(EmailAddress, on_delete=models.SET_NULL, null=True, blank=True, related_name="sends")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Email Send"
        verbose_name_plural = "Email Sends"
        indexes = [models.Index(fields=["status", "to_email"])]

    def __str__(self) -> str:
        return f"Send to {self.to_email} ({self.status})"

    def mark_failed(self, error: str) -> None:
        self.status = self.STATUS_FAILED
        self.error_message = error
        self.save(update_fields=["status", "error_message", "updated_at"])
