def dashboard_overview(request):

    from django.shortcuts import render
    from django.contrib.auth.models import User
    from n8n_mirror.models import WorkflowEntity, ExecutionEntity
    from accounts_plus.models import OpenAIKeyPool

    workflows_total = WorkflowEntity.objects.count()
    workflows_active = WorkflowEntity.objects.filter(active=True).count()
    workflows_archived = WorkflowEntity.objects.filter(isArchived=True).count()

    executions_total = ExecutionEntity.objects.count()
    executions_finished = ExecutionEntity.objects.filter(finished=True).count()
    executions_failed = ExecutionEntity.objects.filter(status__iexact='failed').count()
    executions_running = ExecutionEntity.objects.filter(finished=False).count()

    users_total = User.objects.count()
    users_active = User.objects.filter(is_active=True).count()
    users_last_login = User.objects.order_by('-last_login').first()

    keypool_stats = OpenAIKeyPool.get_pool_stats()

    context = {
        'workflows_total': workflows_total,
        'workflows_active': workflows_active,
        'workflows_archived': workflows_archived,
        'executions_total': executions_total,
        'executions_finished': executions_finished,
        'executions_failed': executions_failed,
        'executions_running': executions_running,
        'users_total': users_total,
        'users_active': users_active,
        'users_last_login': users_last_login,
        'keypool_stats': keypool_stats,
    }
    return render(request, 'dashboard/index.html', context)



def recent_executions(request):
    from django.shortcuts import render
    from n8n_mirror.models import ExecutionEntity
    executions = ExecutionEntity.objects.order_by('-startedAt')[:10]
    return render(request, 'dashboard/recent_executions.html', {'executions': executions})



def workflow_table(request):
    from django.shortcuts import render
    from n8n_mirror.models import WorkflowEntity
    workflows = WorkflowEntity.objects.all().order_by('-createdAt')[:20]
    return render(request, 'dashboard/workflow_table.html', {'workflows': workflows})



def user_table(request):
    from django.shortcuts import render
    from django.contrib.auth.models import User
    users = User.objects.select_related('usern8nprofile').all()[:20]
    return render(request, 'dashboard/user_table.html', {'users': users})
