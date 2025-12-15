from rest_framework.routers import DefaultRouter

from .views import (
    CampaignRecipientViewSet,
    EmailCampaignViewSet,
    EmailTemplateViewSet,
    RecipientViewSet,
)

router = DefaultRouter()
router.register(r"templates", EmailTemplateViewSet, basename="email-templates")
router.register(r"campaigns", EmailCampaignViewSet, basename="email-campaigns")
router.register(r"recipients", RecipientViewSet, basename="email-recipients")
router.register(r"campaign-recipients", CampaignRecipientViewSet, basename="campaign-recipients")

urlpatterns = router.urls
