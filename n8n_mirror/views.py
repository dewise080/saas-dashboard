from django.db.models import Count
from django.shortcuts import get_object_or_404, render

from .models import (
    ExecutionEntity,
    SharedWorkflow,
    UserEntity,
    WebhookEntity,
    WorkflowEntity,
)


def dashboard(request):
    workflow_qs = WorkflowEntity.objects.using("n8n")
    execution_qs = ExecutionEntity.objects.using("n8n")

    context = {
        "segment": "n8n_dashboard",
        "workflow_count": workflow_qs.count(),
        "execution_count": execution_qs.count(),
        "recent_executions": execution_qs.order_by("-createdAt")[:10],
    }
    return render(request, "n8n_mirror/dashboard.html", context)


def my_workflows(request):
    user_email = getattr(request.user, "email", None)
    matched_users = (
        UserEntity.objects.using("n8n").filter(email__iexact=user_email)
        if user_email
        else UserEntity.objects.none()
    )

    shared_workflows = (
        SharedWorkflow.objects.using("n8n")
        .filter(projectId__in=matched_users.values_list("id", flat=True))
        if matched_users.exists()
        else SharedWorkflow.objects.none()
    )

    workflows = (
        WorkflowEntity.objects.using("n8n")
        .filter(id__in=shared_workflows.values_list("workflowId", flat=True))
        .order_by("-updatedAt")
        if shared_workflows.exists()
        else WorkflowEntity.objects.none()
    )

    context = {
        "segment": "n8n_my_workflows",
        "user_email": user_email,
        "workflows": workflows,
        "matched_users": matched_users,
    }
    return render(request, "n8n_mirror/my_workflows.html", context)


def workflow_detail(request, workflow_id):
    workflow = get_object_or_404(
        WorkflowEntity.objects.using("n8n"), id=workflow_id
    )
    executions = (
        ExecutionEntity.objects.using("n8n")
        .filter(workflowId=workflow_id)
        .order_by("-createdAt")[:50]
    )
    webhooks = WebhookEntity.objects.using("n8n").filter(workflowId=workflow_id)

    context = {
        "segment": "n8n_workflow_detail",
        "workflow": workflow,
        "executions": executions,
        "webhooks": webhooks,
    }
    return render(request, "n8n_mirror/workflow_detail.html", context)


def usage(request):
    execution_qs = ExecutionEntity.objects.using("n8n")

    status_breakdown = execution_qs.values("status").annotate(total=Count("id")).order_by("-total")
    mode_breakdown = execution_qs.values("mode").annotate(total=Count("id")).order_by("-total")
    workflow_totals = (
        execution_qs.values("workflowId")
        .annotate(total=Count("id"))
        .order_by("-total")[:25]
    )

    context = {
        "segment": "n8n_usage",
        "status_breakdown": status_breakdown,
        "mode_breakdown": mode_breakdown,
        "workflow_totals": workflow_totals,
        "execution_count": execution_qs.count(),
    }
    return render(request, "n8n_mirror/usage.html", context)
