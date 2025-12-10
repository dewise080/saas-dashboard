from django.urls import path
from . import dashboard_views

urlpatterns = [
    path('dashboard/', dashboard_views.dashboard_overview, name='dashboard-index'),
    path('dashboard/executions/', dashboard_views.recent_executions, name='dashboard-executions'),
    path('dashboard/workflows/', dashboard_views.workflow_table, name='dashboard-workflows'),
    path('dashboard/users/', dashboard_views.user_table, name='dashboard-users'),
]
