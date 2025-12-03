from n8n_mirror.models import UserEntity as N8NUser, UserApiKeys


def get_owner_api_key():
    owner = (
        N8NUser.objects.using("n8n")
        .filter(roleSlug__in=["global:owner", "global:admin"])
        .order_by("createdAt")
        .first()
    )
    if not owner:
        return None

    key = (
        UserApiKeys.objects.using("n8n")
        .filter(userId_id=str(owner.id))
        .exclude(label__iexact="MCP Server API Key")
        .order_by("createdAt")
        .first()
    )
    return key.apiKey if key else None
