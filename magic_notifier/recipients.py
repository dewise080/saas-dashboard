def _get_attr_or_key(obj, *keys):
    for key in keys:
        if hasattr(obj, key):
            value = getattr(obj, key)
            if value:
                return value
        if isinstance(obj, dict) and key in obj and obj[key]:
            return obj[key]
    return None


def get_email(obj):
    return _get_attr_or_key(obj, "email", "mail")


def get_phone(obj):
    return _get_attr_or_key(obj, "phone_number", "phone", "number")


def get_whatsapp_chat_id(obj):
    return _get_attr_or_key(obj, "chat_id", "jid", "whatsapp_chat_id")
