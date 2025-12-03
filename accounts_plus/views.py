import logging

import requests
from admin_datta.forms import LoginForm
from accounts_plus.forms import EmailRegistrationForm
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .models import UserN8NProfile, OpenAIKeyPool
from .utils import get_owner_api_key

logger = logging.getLogger(__name__)

N8N_USERS_ENDPOINT = "https://n8n.lotfinity.tech/api/v1/users"


def _parse_n8n_user_response(data):
    # n8n returns a list of objects, each with a "user" dict. No apiKey is returned.
    record = None
    if isinstance(data, dict):
        record = data.get("data") or data
    elif isinstance(data, list):
        record = data[0] if data else None

    if isinstance(record, dict) and "user" in record:
        record = record["user"]

    if not isinstance(record, dict):
        return None, None

    n8n_user_id = record.get("id") or record.get("userId") or record.get("user_id")
    if not n8n_user_id:
        invite_url = record.get("inviteAcceptUrl")
        if invite_url and "inviteeId=" in invite_url:
            n8n_user_id = invite_url.split("inviteeId=")[-1].split("&")[0]

    api_key = record.get("apiKey") or record.get("api_key")
    return n8n_user_id, api_key


def register_user(request):
    if request.method == "POST":
        form = EmailRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()

            owner_key = get_owner_api_key()
            if not owner_key:
                print("[accounts_plus][ERROR] No owner/admin API key found in n8n.", flush=True)
                messages.error(request, "No owner/admin API key found in n8n.")
                return redirect("accounts_plus:register_user")

            payload = [{"email": user.email, "role": "global:member"}]

            try:
                logger.info(
                    "Creating n8n user",
                    extra={
                        "endpoint": N8N_USERS_ENDPOINT,
                        "payload": payload,
                        "api_key": owner_key,
                    },
                )
                print(
                    f"[accounts_plus] POST {N8N_USERS_ENDPOINT} "
                    f"headers={{'X-N8N-API-KEY': '{owner_key}'}} "
                    f"payload={payload}",
                    flush=True,
                )
                resp = requests.post(
                    N8N_USERS_ENDPOINT,
                    headers={"X-N8N-API-KEY": owner_key},
                    json=payload,
                    timeout=10,
                )
                resp.raise_for_status()
                n8n_user_id, api_key = _parse_n8n_user_response(resp.json())
                if not n8n_user_id:
                    raise ValueError("n8n user creation response missing id")
            except Exception as exc:
                logger.exception(
                    "Failed creating n8n user for %s (status=%s, body=%s)",
                    user.email,
                    getattr(resp, "status_code", None),
                    getattr(resp, "text", None),
                )
                print(
                    f"[accounts_plus][ERROR] n8n user creation failed: "
                    f"status={getattr(resp, 'status_code', None)} "
                    f"body={getattr(resp, 'text', None)} "
                    f"endpoint={N8N_USERS_ENDPOINT} "
                    f"headers={{'X-N8N-API-KEY': '{owner_key}'}} "
                    f"payload={payload}",
                    flush=True,
                )
                messages.error(
                    request,
                    "Account created locally but failed to create linked n8n user. Please contact support.",
                )
                return redirect("accounts_plus:login")

            UserN8NProfile.objects.update_or_create(
                user=user,
                defaults={
                    "n8n_user_id": n8n_user_id,
                    "api_key": api_key or "",
                },
            )
            
            # Auto-assign an OpenAI API key from the pool
            assigned_key = OpenAIKeyPool.assign_to_user(user)
            if assigned_key:
                print(
                    f"[accounts_plus] Assigned OpenAI API key to user {user.email}: "
                    f"{assigned_key.api_key[:8]}...{assigned_key.api_key[-4:]}",
                    flush=True,
                )
            else:
                print(
                    f"[accounts_plus] No available OpenAI API keys in pool for user {user.email}",
                    flush=True,
                )
            
            auth_login(request, user)
            print(
                f"[accounts_plus] Login established after register: user={user.email} "
                f"session_key={request.session.session_key}",
                flush=True,
            )
            return redirect(reverse("apps.pages:index"))
    else:
        form = EmailRegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


@require_http_methods(["GET", "POST"])
def login_user(request):
    if request.user.is_authenticated:
        print(f"[accounts_plus] User already authenticated: {request.user.email}", flush=True)
        return redirect(reverse("apps.pages:index"))

    form = LoginForm(request=request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        auth_login(request, user)
        # Make session persistent (30 days)
        request.session.set_expiry(60 * 60 * 24 * 30)
        print(
            f"[accounts_plus] Login successful! User is in: {user.email} "
            f"session_key={request.session.session_key} (persistent)",
            flush=True,
        )
        return redirect(reverse("apps.pages:index"))

    return render(request, "accounts/login.html", {"form": form})
