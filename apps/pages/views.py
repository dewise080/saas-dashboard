import json
import re
import requests
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.http import JsonResponse
from django.db.models import Count, Sum
from django.utils import timezone
from datetime import timedelta

from apps.pages.models import Product, UserTelegramCredential, UserWhatsAppInstance, N8NExecutionSnapshot
from apps.pages.evolution_db import (
    get_all_instances_status, 
    get_instance_status, 
    get_instance_details,
    get_instance_stats,
    get_instance_settings,
    get_instance_webhook,
    get_instance_chats,
    get_instance_contacts,
    get_instance_recent_messages,
    get_instance_labels,
)
from accounts_plus.models import UserN8NProfile, OpenAIKeyPool
from n8n_mirror.models import UserApiKeys

EVOLUTION_API_URL = "https://evo.lotfinity.tech"
EVOLUTION_API_KEY = "123456789Tt@"
N8N_CREDENTIALS_URL = "https://n8n.lotfinity.tech/api/v1/credentials"


def create_n8n_credentials_for_user(user):
    """
    Create OpenAI and Evolution API credentials in n8n for a user.
    Called when user first connects their WhatsApp instance.
    Returns tuple (success, message).
    """
    # Get user's n8n profile and API key
    profile = UserN8NProfile.objects.filter(user=user).first()
    if not profile or not profile.n8n_user_id:
        return False, "User has no n8n profile"
    
    # Get user's n8n API key for authentication
    api_key_obj = (
        UserApiKeys.objects.using("n8n")
        .filter(userId_id=str(profile.n8n_user_id))
        .exclude(label__iexact="MCP Server API Key")
        .order_by("-createdAt")
        .first()
    )
    
    if not api_key_obj:
        return False, "User has no n8n API key"
    
    user_n8n_api_key = api_key_obj.apiKey
    headers = {
        "X-N8N-API-KEY": user_n8n_api_key,
        "Content-Type": "application/json",
    }
    
    # Get user's assigned OpenAI key from pool
    assigned_openai_key = OpenAIKeyPool.get_user_key(user)
    
    results = []
    
    # 1. Create OpenAI credential (if user has an assigned key)
    if assigned_openai_key:
        openai_payload = {
            "name": "OpenAI API Key",
            "type": "openAiApi",
            "data": {
                "apiKey": assigned_openai_key.api_key,
                "header": False,
            },
        }
        
        try:
            print(f"[n8n_creds] Creating OpenAI credential for {user.email}", flush=True)
            resp = requests.post(
                N8N_CREDENTIALS_URL,
                headers=headers,
                json=openai_payload,
                timeout=15,
            )
            if resp.status_code in [200, 201]:
                print(f"[n8n_creds] ✅ OpenAI credential created for {user.email}", flush=True)
                results.append(("openai", True, "Created"))
            else:
                print(f"[n8n_creds] ❌ OpenAI credential failed: {resp.status_code} - {resp.text}", flush=True)
                results.append(("openai", False, f"HTTP {resp.status_code}"))
        except Exception as e:
            print(f"[n8n_creds] ❌ OpenAI credential error: {e}", flush=True)
            results.append(("openai", False, str(e)))
    else:
        print(f"[n8n_creds] ⚠️ No OpenAI key assigned to {user.email}, skipping", flush=True)
        results.append(("openai", False, "No key assigned"))
    
    # 2. Create Evolution API credential
    evolution_payload = {
        "name": "Evolution API",
        "type": "evolutionApi",
        "data": {
            "server-url": EVOLUTION_API_URL,
            "apikey": EVOLUTION_API_KEY,
            "allowedHttpRequestDomains": "all",
        },
    }
    
    try:
        print(f"[n8n_creds] Creating Evolution API credential for {user.email}", flush=True)
        resp = requests.post(
            N8N_CREDENTIALS_URL,
            headers=headers,
            json=evolution_payload,
            timeout=15,
        )
        if resp.status_code in [200, 201]:
            print(f"[n8n_creds] ✅ Evolution API credential created for {user.email}", flush=True)
            results.append(("evolution", True, "Created"))
        else:
            print(f"[n8n_creds] ❌ Evolution API credential failed: {resp.status_code} - {resp.text}", flush=True)
            results.append(("evolution", False, f"HTTP {resp.status_code}"))
    except Exception as e:
        print(f"[n8n_creds] ❌ Evolution API credential error: {e}", flush=True)
        results.append(("evolution", False, str(e)))
    
    success_count = sum(1 for _, success, _ in results if success)
    return success_count > 0, results


@login_required
def index(request):
  context = {
    'segment': 'dashboard'
  }
  return render(request, "pages/index.html", context)


@login_required
def workflows(request):
  """Workflows page - placeholder for user workflow management."""
  context = {
    'segment': 'workflows'
  }
  return render(request, "pages/workflows.html", context)


@login_required
def n8n_user_dashboard(request):
  """
  Personalized n8n overview for the logged-in user:
  - Workflows shared with them
  - Recent executions
  - Basic status breakdown and token usage (best-effort parse)
  """
  from n8n_mirror.models import (
    UserEntity,
    SharedWorkflow,
    WorkflowEntity,
    ExecutionEntity,
    ExecutionData,
    ProjectRelation,
  )

  user_email = (request.user.email or "").strip()

  matched_users = UserEntity.objects.using("n8n").filter(email__iexact=user_email) if user_email else UserEntity.objects.none()

  # Collect all possible n8n user IDs tied to this Django user
  n8n_user_ids = set(matched_users.values_list("id", flat=True))
  profile = UserN8NProfile.objects.filter(user=request.user).first()
  if profile and profile.n8n_user_id:
    n8n_user_ids.add(profile.n8n_user_id)

  # Map user -> project(s) -> shared workflows
  project_ids = set()
  if n8n_user_ids:
    project_ids.update(
      SharedWorkflow.objects.using("n8n")
      .filter(projectId__in=n8n_user_ids)
      .values_list("projectId", flat=True)
    )
    project_ids.update(
      ProjectRelation.objects.using("n8n")
      .filter(userId__in=n8n_user_ids)
      .values_list("projectId", flat=True)
    )

  shared_workflows = (
    SharedWorkflow.objects.using("n8n").filter(projectId__in=project_ids)
    if project_ids
    else SharedWorkflow.objects.none()
  )

  workflow_ids = list(shared_workflows.values_list("workflowId", flat=True))
  workflows = (
    WorkflowEntity.objects.using("n8n")
    .filter(id__in=workflow_ids)
    .order_by("-updatedAt")
  )

  executions_qs = (
    ExecutionEntity.objects.using("n8n")
    .filter(workflowId__in=workflow_ids)
    .order_by("-startedAt")
  )

  recent_executions = list(executions_qs[:10])
  # Prefetch any stored snapshots to avoid reparsing large payloads
  snapshot_map = {
    snap.execution_id: snap
    for snap in N8NExecutionSnapshot.objects.filter(execution_id__in=[e.id for e in recent_executions])
  }
  status_breakdown = (
    executions_qs.values("status").annotate(total=Count("id")).order_by("-total")
  )

  # Best-effort token usage extraction from execution data payloads
  token_usage = {}
  recent_exec_data = []
  if recent_executions:
    execution_ids = [exec.id for exec in recent_executions]
    data_map = {
      str(ed.executionId_id): ed
      for ed in ExecutionData.objects.using("n8n").filter(executionId__in=execution_ids)
    }

    def _best_usage_dict(obj):
      """
      Recursively scan for token usage dicts.
      Returns the most complete dict found.
      """
      best = None

      def score(dct):
        if not isinstance(dct, dict):
          return -1
        keys = {"total_tokens", "prompt_tokens", "completion_tokens", "tokens"}
        return sum(1 for k in dct if k in keys)

      def walk(node):
        nonlocal best
        if isinstance(node, dict):
          if "usage" in node and isinstance(node["usage"], dict):
            if score(node["usage"]) > score(best or {}):
              best = node["usage"]
          if score(node) > score(best or {}):
            best = node
          for v in node.values():
            walk(v)
        elif isinstance(node, list):
          for item in node:
            walk(item)

      walk(obj)
      return best

    def extract_tokens(ed):
      if not ed:
        return None
      for raw in (ed.data, ed.workflowData):
        parsed = None
        if isinstance(raw, (dict, list)):
          parsed = raw
        elif isinstance(raw, str):
          try:
            parsed = json.loads(raw)
          except Exception:
            parsed = None
        if parsed is not None:
          usage_dict = _best_usage_dict(parsed)
          if isinstance(usage_dict, dict):
            total = usage_dict.get("total_tokens") or usage_dict.get("tokens")
            prompt = usage_dict.get("prompt_tokens")
            completion = usage_dict.get("completion_tokens")
            return {
              "total": total or (prompt or 0) + (completion or 0) if (prompt or completion) else None,
              "prompt": prompt,
              "completion": completion,
              "raw": usage_dict,
            }
        # Regex fallback for token patterns inside raw strings
        if isinstance(raw, str):
          prompt_match = re.search(r'"?promptTokens"?\\s*:\\s*(\\d+)', raw)
          completion_match = re.search(r'"?completionTokens"?\\s*:\\s*(\\d+)', raw)
          total_match = re.search(r'"?totalTokens"?\\s*:\\s*(\\d+)', raw)
          if prompt_match or completion_match or total_match:
            prompt_val = int(prompt_match.group(1)) if prompt_match else None
            completion_val = int(completion_match.group(1)) if completion_match else None
            total_val = int(total_match.group(1)) if total_match else None
            if total_val is None and (prompt_val is not None or completion_val is not None):
              total_val = (prompt_val or 0) + (completion_val or 0)
            return {
              "total": total_val,
              "prompt": prompt_val,
              "completion": completion_val,
              "raw": {"promptTokens": prompt_val, "completionTokens": completion_val, "totalTokens": total_val},
            }
      return None

    for exec in recent_executions:
      snap = snapshot_map.get(exec.id)
      if snap and (snap.tokens_total or snap.tokens_prompt or snap.tokens_completion):
        token_usage[exec.id] = {
          "total": snap.tokens_total,
          "prompt": snap.tokens_prompt,
          "completion": snap.tokens_completion,
        }
      else:
        token_usage[exec.id] = extract_tokens(data_map.get(str(exec.id)))
      recent_exec_data.append({"exec": exec, "tokens": token_usage[exec.id]})

    # Persist summaries for later billing/analytics
    for exec in recent_executions:
      usage = token_usage.get(exec.id) or {}
      N8NExecutionSnapshot.objects.update_or_create(
        execution_id=exec.id,
        defaults={
          "user": request.user if request.user.is_authenticated else None,
          "workflow_id": exec.workflowId,
          "status": exec.status,
          "mode": getattr(exec, "mode", "") or "",
          "started_at": exec.startedAt,
          "stopped_at": exec.stoppedAt,
          "tokens_total": usage.get("total"),
          "tokens_prompt": usage.get("prompt"),
          "tokens_completion": usage.get("completion"),
          "usage_raw": usage.get("raw") or usage,
        },
      )

  context = {
    "segment": "n8n_user_dashboard",
    "user_email": user_email,
    "workflows": workflows,
    "workflows_count": workflows.count(),
    "recent_executions": recent_executions,
    "recent_exec_data": recent_exec_data or [{"exec": e, "tokens": None} for e in recent_executions],
    "status_breakdown": status_breakdown,
    "token_usage": token_usage,
  }
  # Fallback: if nothing is linked, try user-bound snapshots
  if not recent_exec_data:
    snaps = list(
      N8NExecutionSnapshot.objects.filter(user=request.user)
      .order_by("-started_at")[:10]
    )
    if snaps:
      from types import SimpleNamespace
      recent_exec_data = []
      for snap in snaps:
        exec_obj = SimpleNamespace(
          id=snap.execution_id,
          status=snap.status,
          workflowId=snap.workflow_id,
          startedAt=snap.started_at,
          stoppedAt=snap.stopped_at,
        )
        recent_exec_data.append({
          "exec": exec_obj,
          "tokens": {
            "total": snap.tokens_total,
            "prompt": snap.tokens_prompt,
            "completion": snap.tokens_completion,
          },
        })
      context["recent_exec_data"] = recent_exec_data
      context["recent_executions"] = [row["exec"] for row in recent_exec_data]
      context["status_breakdown"] = []
      context["workflows"] = []
      context["workflows_count"] = 0

  # Totals for billing/usage
  snapshots_qs = N8NExecutionSnapshot.objects.filter(user=request.user)
  totals_all = snapshots_qs.aggregate(
    total_tokens=Sum("tokens_total"),
    prompt_tokens=Sum("tokens_prompt"),
    completion_tokens=Sum("tokens_completion"),
  )
  cutoff = timezone.now() - timedelta(days=30)
  totals_30d = snapshots_qs.filter(started_at__gte=cutoff).aggregate(
    total_tokens=Sum("tokens_total"),
    prompt_tokens=Sum("tokens_prompt"),
    completion_tokens=Sum("tokens_completion"),
  )
  context["usage_totals_all"] = totals_all
  context["usage_totals_30d"] = totals_30d

  return render(request, "pages/n8n_user_dashboard.html", context)

# Components
def color(request):
  context = {
    'segment': 'color'
  }
  return render(request, "pages/color.html", context)

def typography(request):
  context = {
    'segment': 'typography'
  }
  return render(request, "pages/typography.html", context)

def icon_feather(request):
  context = {
    'segment': 'feather_icon'
  }
  return render(request, "pages/icon-feather.html", context)

@login_required
def credentials(request):
  print(f"[credentials] User authenticated: {request.user.is_authenticated}, User: {request.user}", flush=True)
  profile = UserN8NProfile.objects.filter(user=request.user).first()
  
  # Get API key if profile exists
  api_key_obj = None
  if profile and profile.n8n_user_id:
    api_key_obj = (
      UserApiKeys.objects.using("n8n")
      .filter(userId_id=str(profile.n8n_user_id))
      .exclude(label__iexact="MCP Server API Key")
      .order_by("-createdAt")
      .first()
    )

  existing_telegram = UserTelegramCredential.objects.filter(user=request.user)
  existing_whatsapp = UserWhatsAppInstance.objects.filter(user=request.user)
  
  # Fetch LIVE status from Evolution DB for all user's instances
  instance_names = list(existing_whatsapp.values_list('instance_name', flat=True))
  live_statuses = {}
  try:
    live_statuses = get_all_instances_status(instance_names)
  except Exception as e:
    print(f"[credentials] Failed to get live statuses from Evolution DB: {e}", flush=True)
  
  # Enrich instances with live data
  whatsapp_with_live_status = []
  for instance in existing_whatsapp:
      live = live_statuses.get(instance.instance_name, {})
      whatsapp_with_live_status.append({
          'instance': instance,
          'live_status': live.get('connectionStatus', 'unknown'),
          'profile_name': live.get('profileName'),
          'profile_pic': live.get('profilePicUrl'),
          'owner_jid': live.get('ownerJid'),
          'number': live.get('number'),
          'is_connected': live.get('connectionStatus') == 'open',
      })

  if request.method == "POST":
    form_type = request.POST.get("form_type")
    
    # Handle Telegram form submission
    if form_type == "telegram":
      name = (request.POST.get("name") or "").strip()
      token = (request.POST.get("token") or "").strip()

      if not name or not token:
        messages.error(request, "Name and token are required.")
        return redirect("apps.pages:credentials")

      if not api_key_obj:
        messages.error(request, "No n8n API key found for your account.")
        return redirect("apps.pages:credentials")

      payload = {
        "name": name,
        "type": "telegramApi",
        "data": {"accessToken": token},
      }
      headers = {"X-N8N-API-KEY": api_key_obj.apiKey}

      try:
        print(
          f"[credentials] POST https://n8n.lotfinity.tech/api/v1/credentials "
          f"headers={{'X-N8N-API-KEY': '{api_key_obj.apiKey}'}} payload={payload}",
          flush=True,
        )
        resp = requests.post(
          "https://n8n.lotfinity.tech/api/v1/credentials",
          headers=headers,
          json=payload,
          timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        n8n_cred_id = body.get("id") or body.get("data", {}).get("id")
        if not n8n_cred_id:
          raise ValueError("Credential ID missing from n8n response")

        UserTelegramCredential.objects.create(
          user=request.user,
          n8n_credential_id=n8n_cred_id,
          name=body.get("name") or name,
          token=token,
        )
        messages.success(request, "Telegram token saved and synced to n8n.")
        return redirect("apps.pages:credentials")
      except Exception as exc:
        print(
          f"[credentials][ERROR] status={getattr(resp, 'status_code', None)} "
          f"body={getattr(resp, 'text', None)}",
          flush=True,
        )
        messages.error(request, f"Failed to save credential: {exc}")
        return redirect("apps.pages:credentials")

    # Handle WhatsApp form submission
    elif form_type == "whatsapp":
      instance_name = (request.POST.get("instance_name") or "").strip()
      whatsapp_number = (request.POST.get("whatsapp_number") or "").strip()

      if not instance_name or not whatsapp_number:
        messages.error(request, "Instance name and WhatsApp number are required.")
        return redirect("apps.pages:credentials")

      # Check if instance name already exists
      if UserWhatsAppInstance.objects.filter(instance_name=instance_name).exists():
        messages.error(request, "An instance with this name already exists.")
        return redirect("apps.pages:credentials")

      payload = {
        "instanceName": instance_name,
        "integration": "WHATSAPP-BAILEYS",
        "number": whatsapp_number,
        "qrcode": True,
      }
      headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json",
      }

      try:
        print(
          f"[whatsapp] POST {EVOLUTION_API_URL}/instance/create "
          f"payload={payload}",
          flush=True,
        )
        resp = requests.post(
          f"{EVOLUTION_API_URL}/instance/create",
          headers=headers,
          json=payload,
          timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        print(f"[whatsapp] Response: {body}", flush=True)

        # Extract data from response
        instance_data = body.get("instance", {})
        qrcode_data = body.get("qrcode", {})
        
        # Save instance to database
        whatsapp_instance = UserWhatsAppInstance.objects.create(
          user=request.user,
          instance_name=instance_data.get("instanceName", instance_name),
          instance_id=instance_data.get("instanceId"),
          whatsapp_number=whatsapp_number,
          hash_key=body.get("hash"),
          status=instance_data.get("status", "connecting"),
        )
        
        # Store QR data in session for display
        request.session["whatsapp_qr_data"] = {
          "instance_name": whatsapp_instance.instance_name,
          "pairing_code": qrcode_data.get("pairingCode"),
          "qr_base64": qrcode_data.get("base64"),
          "code": qrcode_data.get("code"),
        }
        
        messages.success(request, "WhatsApp instance created! Scan the QR code to connect.")
        return redirect("apps.pages:whatsapp_connect", instance_name=whatsapp_instance.instance_name)
      except requests.exceptions.RequestException as exc:
        print(
          f"[whatsapp][ERROR] status={getattr(resp, 'status_code', None)} "
          f"body={getattr(resp, 'text', None)}",
          flush=True,
        )
        messages.error(request, f"Failed to create WhatsApp instance: {exc}")
        return redirect("apps.pages:credentials")

  # Get the user's assigned OpenAI key from the pool
  assigned_openai_key = OpenAIKeyPool.get_user_key(request.user)

  context = {
    'segment': 'credentials',
    "credentials": existing_telegram,
    "whatsapp_instances": whatsapp_with_live_status,
    "has_api_key": bool(api_key_obj),
    "has_profile": bool(profile),
    "has_openai_key": bool(assigned_openai_key),
    "openai_key_preview": f"{assigned_openai_key.api_key[:8]}...{assigned_openai_key.api_key[-4:]}" if assigned_openai_key and len(assigned_openai_key.api_key) > 12 else None,
    "openai_key_assigned_at": assigned_openai_key.assigned_at if assigned_openai_key else None,
  }
  return render(request, 'pages/credentials.html', context)


@login_required
def whatsapp_connect(request, instance_name):
    """Display QR code for WhatsApp instance connection."""
    instance = UserWhatsAppInstance.objects.filter(
        user=request.user, instance_name=instance_name
    ).first()

    if not instance:
        messages.error(request, "WhatsApp instance not found.")
        return redirect("apps.pages:credentials")

    # Get LIVE status from Evolution DB
    live_status = None
    evo_details = None
    try:
        live_status = get_instance_status(instance_name)
        evo_details = get_instance_details(instance_name)
    except Exception as e:
        print(f"[whatsapp_connect] Failed to get live status: {e}", flush=True)
    
    # If already connected, update local status and redirect back with success
    if live_status and live_status.get('connectionStatus') == 'open':
        # Update our local status to match and create credentials if first time
        if instance.status != 'connected':
            instance.status = 'connected'
            instance.save(update_fields=['status'])
            
            # First time connecting - create n8n credentials
            print(f"[whatsapp_connect] WhatsApp connected! Creating n8n credentials for {request.user.email}", flush=True)
            success, results = create_n8n_credentials_for_user(request.user)
            print(f"[whatsapp_connect] Credentials creation: success={success}, results={results}", flush=True)
            
        messages.success(request, f"WhatsApp connected as {live_status.get('profileName', 'Unknown')}!")
        return redirect("apps.pages:credentials")

    # Get QR data from session (set during instance creation)
    qr_data = request.session.pop("whatsapp_qr_data", None)
    
    context = {
        "segment": "credentials",
        "instance": instance,
        "qr_data": qr_data,
        "live_status": live_status,
        "evo_details": evo_details,
    }
    return render(request, "pages/whatsapp_connect.html", context)


@login_required
def whatsapp_refresh_qr(request, instance_name):
    """API endpoint to refresh QR code for an existing instance."""
    instance = UserWhatsAppInstance.objects.filter(
        user=request.user, instance_name=instance_name
    ).first()

    if not instance:
        return JsonResponse({"error": "Instance not found"}, status=404)

    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }

    try:
        print(
            f"[whatsapp_qr] GET {EVOLUTION_API_URL}/instance/connect/{instance_name}",
            flush=True,
        )
        resp = requests.get(
            f"{EVOLUTION_API_URL}/instance/connect/{instance_name}",
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"[whatsapp_qr] Response: {data}", flush=True)

        return JsonResponse({
            "pairingCode": data.get("pairingCode"),
            "base64": data.get("base64"),
            "code": data.get("code"),
            "count": data.get("count"),
        })
    except requests.exceptions.RequestException as exc:
        print(
            f"[whatsapp_qr][ERROR] status={getattr(resp, 'status_code', None)} "
            f"body={getattr(resp, 'text', None)}",
            flush=True,
        )
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
def save_openai_key(request):
    """Save OpenAI API key for the user."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    api_key = request.POST.get("openai_api_key", "").strip()
    
    if not api_key:
        messages.error(request, "API key is required.")
        return redirect("apps.pages:credentials")
    
    if not api_key.startswith("sk-"):
        messages.error(request, "Invalid OpenAI API key format. It should start with 'sk-'.")
        return redirect("apps.pages:credentials")
    
    profile = UserN8NProfile.objects.filter(user=request.user).first()
    if not profile:
        # Create profile if it doesn't exist
        profile = UserN8NProfile.objects.create(
            user=request.user,
            n8n_user_id="",
            api_key="",
            openai_api_key=api_key,
        )
    else:
        profile.openai_api_key = api_key
        profile.save(update_fields=["openai_api_key"])
    
    messages.success(request, "OpenAI API key saved successfully!")
    return redirect("apps.pages:credentials")


@login_required
def validate_openai_key(request):
    """Validate OpenAI API key by making a test request."""
    profile = UserN8NProfile.objects.filter(user=request.user).first()
    
    if not profile or not profile.openai_api_key:
        return JsonResponse({
            "valid": False,
            "status": "not_found",
            "message": "No OpenAI API key configured."
        })
    
    api_key = profile.openai_api_key
    
    try:
        # Test the API key by listing models
        resp = requests.get(
            "https://api.openai.com/v1/models",
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            timeout=10,
        )
        
        if resp.status_code == 200:
            data = resp.json()
            models = [m["id"] for m in data.get("data", []) if "gpt" in m["id"].lower()][:5]
            return JsonResponse({
                "valid": True,
                "status": "connected",
                "message": "AI models connected and ready!",
                "models": models,
            })
        elif resp.status_code == 401:
            return JsonResponse({
                "valid": False,
                "status": "invalid",
                "message": "Invalid API key. Please check your key and try again.",
            })
        elif resp.status_code == 429:
            return JsonResponse({
                "valid": False,
                "status": "rate_limited",
                "message": "API key is valid but rate limited. Please try again later.",
            })
        else:
            return JsonResponse({
                "valid": False,
                "status": "error",
                "message": f"OpenAI API error: {resp.status_code}",
            })
    except requests.exceptions.Timeout:
        return JsonResponse({
            "valid": False,
            "status": "timeout",
            "message": "Connection to OpenAI timed out. Please try again.",
        })
    except requests.exceptions.RequestException as exc:
        return JsonResponse({
            "valid": False,
            "status": "error",
            "message": f"Connection error: {str(exc)}",
        })


@login_required
def whatsapp_status_api(request, instance_name):
    """API endpoint to get live WhatsApp status from Evolution DB."""
    instance = UserWhatsAppInstance.objects.filter(
        user=request.user, instance_name=instance_name
    ).first()

    if not instance:
        return JsonResponse({"error": "Instance not found"}, status=404)

    try:
        live_status = get_instance_status(instance_name)
        evo_details = get_instance_details(instance_name)
        
        is_connected = live_status.get('connectionStatus') == 'open' if live_status else False
        
        credentials_created = False
        
        # Sync local status if connected AND trigger credential creation on first connect
        if is_connected and instance.status != 'connected':
            old_status = instance.status
            instance.status = 'connected'
            instance.save(update_fields=['status'])
            
            # First time connecting - create n8n credentials
            print(f"[whatsapp_status_api] WhatsApp connected! Creating n8n credentials for {request.user.email}", flush=True)
            success, results = create_n8n_credentials_for_user(request.user)
            credentials_created = success
            print(f"[whatsapp_status_api] Credentials creation: success={success}, results={results}", flush=True)
        
        return JsonResponse({
            "instance_name": instance_name,
            "local_status": instance.status,
            "live_status": live_status,
            "details": evo_details,
            "is_connected": is_connected,
            "credentials_created": credentials_created,
        })
    except Exception as e:
        print(f"[whatsapp_status_api] Error: {e}", flush=True)
        return JsonResponse({
            "instance_name": instance_name,
            "local_status": instance.status,
            "live_status": None,
            "details": None,
            "is_connected": False,
            "error": str(e),
        })


@login_required
def whatsapp_dashboard(request, instance_name):
    """WhatsApp instance dashboard with full Evolution DB data."""
    # Verify user owns this instance
    instance = UserWhatsAppInstance.objects.filter(
        user=request.user, instance_name=instance_name
    ).first()

    if not instance:
        messages.error(request, "WhatsApp instance not found.")
        return redirect("apps.pages:credentials")

    # Fetch all data from Evolution DB
    try:
        details = get_instance_details(instance_name)
        stats = get_instance_stats(instance_name)
        settings = get_instance_settings(instance_name)
        webhook = get_instance_webhook(instance_name)
        chats = get_instance_chats(instance_name, limit=20)
        contacts = get_instance_contacts(instance_name, limit=30)
        recent_messages = get_instance_recent_messages(instance_name, limit=15)
        labels = get_instance_labels(instance_name)
    except Exception as e:
        print(f"[whatsapp_dashboard] Error fetching Evolution DB data: {e}", flush=True)
        messages.error(request, f"Error fetching WhatsApp data: {e}")
        details = stats = settings = webhook = None
        chats = contacts = recent_messages = labels = []

    context = {
        "segment": "whatsapp_dashboard",
        "instance": instance,
        "details": details,
        "stats": stats,
        "settings": settings,
        "webhook": webhook,
        "chats": chats,
        "contacts": contacts,
        "recent_messages": recent_messages,
        "labels": labels,
        "is_connected": details.get('connectionStatus') == 'open' if details else False,
    }
    return render(request, "pages/whatsapp_dashboard.html", context)


@login_required
def whatsapp_dashboard_api(request, instance_name):
    """API endpoint to get full dashboard data for AJAX refresh."""
    instance = UserWhatsAppInstance.objects.filter(
        user=request.user, instance_name=instance_name
    ).first()

    if not instance:
        return JsonResponse({"error": "Instance not found"}, status=404)

    try:
        details = get_instance_details(instance_name)
        stats = get_instance_stats(instance_name)
        
        return JsonResponse({
            "instance_name": instance_name,
            "details": details,
            "stats": stats,
            "is_connected": details.get('connectionStatus') == 'open' if details else False,
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def api_n8n_credentials(request):
    """
    API endpoint to fetch user's n8n credentials.
    Used by Pengaa Flow to populate credential dropdowns.
    """
    from n8n_mirror.models import CredentialsEntity, SharedCredentials, ProjectRelation
    
    profile = UserN8NProfile.objects.filter(user=request.user).first()
    if not profile or not profile.n8n_user_id:
        return JsonResponse({"credentials": [], "error": "No n8n profile"})
    
    # Get credential type filter from query params
    cred_type = request.GET.get('type', None)
    
    try:
        # Get user's projects
        user_projects = ProjectRelation.objects.using("n8n").filter(
            userId=str(profile.n8n_user_id)
        ).values_list('projectId', flat=True)
        
        # Get credentials shared with those projects
        shared_cred_ids = SharedCredentials.objects.using("n8n").filter(
            projectId__in=list(user_projects)
        ).values_list('credentialsId', flat=True)
        
        # Fetch the actual credentials
        credentials_qs = CredentialsEntity.objects.using("n8n").filter(
            id__in=list(shared_cred_ids)
        )
        
        if cred_type:
            credentials_qs = credentials_qs.filter(type=cred_type)
        
        credentials = []
        for cred in credentials_qs:
            credentials.append({
                "id": str(cred.id),
                "name": cred.name,
                "type": cred.type,
                "createdAt": cred.createdAt.isoformat() if cred.createdAt else None,
                "updatedAt": cred.updatedAt.isoformat() if cred.updatedAt else None,
            })
        
        return JsonResponse({"credentials": credentials})
    except Exception as e:
        print(f"[api_n8n_credentials] Error: {e}", flush=True)
        return JsonResponse({"credentials": [], "error": str(e)})
