import json
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth.models import User

from n8n_mirror.models import ExecutionEntity, ExecutionData, WorkflowEntity, UserEntity, ProjectRelation, SharedWorkflow
from apps.pages.models import N8NExecutionSnapshot
from accounts_plus.models import UserN8NProfile


def best_usage_dict(obj):
    """Recursively scan for token usage dicts and return the most complete one."""
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
    """Extract token totals from an ExecutionData record."""
    if not ed:
        return None
    for raw in (ed.data, ed.workflowData):
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        usage_dict = best_usage_dict(parsed)
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
        if isinstance(raw, str):
            prompt_match = re.search(r'"?promptTokens"?\s*:\s*(\d+)', raw)
            completion_match = re.search(r'"?completionTokens"?\s*:\s*(\d+)', raw)
            total_match = re.search(r'"?totalTokens"?\s*:\s*(\d+)', raw)
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


class Command(BaseCommand):
    help = "Sync token usage from n8n mirror ExecutionData into local snapshots"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=500, help="Max executions to process")
        parser.add_argument("--workflow-id", type=str, help="Filter to specific workflowId")
        parser.add_argument("--status", type=str, help="Filter by execution status")

    def handle(self, *args, **options):
        limit = options["limit"]
        workflow_filter = options.get("workflow_id")
        status_filter = options.get("status")

        qs = ExecutionEntity.objects.using("n8n").order_by("-startedAt")
        if workflow_filter:
            qs = qs.filter(workflowId=workflow_filter)
        if status_filter:
            qs = qs.filter(status=status_filter)
        executions = list(qs[:limit])

        data_map = {
            str(ed.executionId_id): ed
            for ed in ExecutionData.objects.using("n8n").filter(executionId__in=[e.id for e in executions])
        }

        # map workflowId -> user (best-effort) via SharedWorkflow/ProjectRelation/UserEntity/email match to Django User
        workflow_owner_map = {}
        # preload workflow->project links
        shared = SharedWorkflow.objects.using("n8n").filter(workflowId__in=[e.workflowId for e in executions])
        wf_to_project = {sw.workflowId: sw.projectId for sw in shared}
        # preload project relations
        project_ids = list(set(wf_to_project.values()))
        proj_rels = list(
            ProjectRelation.objects.using("n8n")
            .filter(projectId__in=project_ids)
            .values("projectId", "userId")
        )
        user_ids = set(pr["userId"] for pr in proj_rels)
        n8n_users = {
            str(row["id"]): row["email"]
            for row in UserEntity.objects.using("n8n")
            .filter(id__in=user_ids)
            .values("id", "email")
        }
        email_to_user = {
            u.email.lower(): u
            for u in User.objects.filter(
                email__in=[email for email in n8n_users.values() if email]
            )
        }

        created = 0
        updated = 0
        with transaction.atomic():
            for exec in executions:
                usage = extract_tokens(data_map.get(str(exec.id))) or {}
                # best-effort user link
                n8n_project = wf_to_project.get(exec.workflowId)
                candidate_user = None
                if n8n_project:
                    rel = next((pr for pr in proj_rels if pr["projectId"] == n8n_project), None)
                    if rel:
                        n8n_email = n8n_users.get(str(rel["userId"]))
                        if n8n_email:
                            candidate_user = email_to_user.get(n8n_email.lower())
                        if not candidate_user and rel["userId"]:
                            prof = (
                                UserN8NProfile.objects.filter(n8n_user_id=str(rel["userId"]))
                                .select_related("user")
                                .first()
                            )
                            candidate_user = prof.user if prof else None

                obj, is_created = N8NExecutionSnapshot.objects.update_or_create(
                    execution_id=exec.id,
                    defaults={
                        "user": candidate_user,
                        "workflow_id": exec.workflowId,
                        "status": exec.status,
                        "mode": getattr(exec, "mode", "") or "",
                        "started_at": exec.startedAt,
                        "stopped_at": exec.stoppedAt,
                        "tokens_total": usage.get("total"),
                        "tokens_prompt": usage.get("prompt"),
                        "tokens_completion": usage.get("completion"),
                        "usage_raw": usage.get("raw") or usage or None,
                    },
                )
                created += 1 if is_created else 0
                updated += 0 if is_created else 1

        self.stdout.write(self.style.SUCCESS(f"Processed {len(executions)} executions. Created: {created}, Updated: {updated}"))
