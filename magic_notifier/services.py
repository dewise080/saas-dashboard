from django.contrib.contenttypes.models import ContentType

from magic_notifier.models import Notification, NotificationEvent
from magic_notifier.settings import NOTIFIER_DEFAULT_MODE


def create_notification(
    recipient,
    text,
    type,
    subject=None,
    link="",
    data=None,
    actions=None,
    mode=None,
    inited_by=None,
):
    """
    Create a Notification tied to a generic recipient.
    """
    data = data or {}
    actions = actions or {}
    ct = None
    object_id = None
    if recipient:
        ct = ContentType.objects.get_for_model(recipient)
        object_id = getattr(recipient, "pk", None) or getattr(recipient, "id", None)

    return Notification.objects.create(
        recipient_content_type=ct,
        recipient_object_id=object_id,
        inited_by=inited_by,
        subject=subject,
        text=text,
        type=type,
        link=link,
        data=data,
        actions=actions,
        mode=mode or NOTIFIER_DEFAULT_MODE,
    )


def log_notification_event(
    *,
    channel: str,
    status: str,
    gateway: str = None,
    provider: str = None,
    recipient=None,
    notification: Notification = None,
    is_test: bool = False,
    error_message: str = None,
    metadata: dict = None,
):
    """
    Persist a NotificationEvent entry for dashboard statistics.
    """
    metadata = metadata or {}
    ct = None
    object_id = None
    if recipient:
        ct = ContentType.objects.get_for_model(recipient)
        object_id = getattr(recipient, "pk", None) or getattr(recipient, "id", None)

    return NotificationEvent.objects.create(
        notification=notification,
        recipient_content_type=ct,
        recipient_object_id=object_id,
        channel=channel,
        gateway=gateway,
        provider=provider,
        status=status,
        is_test=is_test,
        error_message=error_message,
        metadata=metadata,
    )
