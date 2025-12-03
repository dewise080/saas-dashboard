from django.urls import path

from . import views

app_name = "n8n_mirror"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("my-workflows/", views.my_workflows, name="my_workflows"),
    path("workflow/<str:workflow_id>/", views.workflow_detail, name="workflow_detail"),
    path("usage/", views.usage, name="usage"),
]
