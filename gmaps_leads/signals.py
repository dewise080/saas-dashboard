"""
Django signals for gmaps_leads app.

These signals allow external apps to react to email template events.
"""
from django.dispatch import Signal

# Signal emitted when an email template is marked as ready to send
# Sender: the serializer or model method that triggered the change
# Instance: the EmailTemplate object
email_template_ready = Signal()

# Signal emitted when an email template is actually sent
email_template_sent = Signal()

# Signal emitted when an email template is approved for sending
email_template_approved = Signal()
