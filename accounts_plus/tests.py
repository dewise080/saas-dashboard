from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import UserN8NProfile


class RegistrationFlowTests(TestCase):
    @patch("accounts_plus.views.get_owner_api_key", return_value="owner-key-123")
    @patch("accounts_plus.views.requests.post")
    def test_register_creates_profile_and_logs_in(self, mock_post, _mock_owner_key):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": "n8n-user-1", "apiKey": "api-key-xyz"}]
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        resp = self.client.post(
            reverse("accounts_plus:register"),
            {
                "username": "alice",
                "email": "alice@example.com",
                "password1": "StrongPass123__",
                "password2": "StrongPass123__",
            },
        )

        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("accounts_plus:onboarding_start"))

        user = User.objects.get(username="alice")
        profile = UserN8NProfile.objects.get(user=user)
        self.assertEqual(profile.n8n_user_id, "n8n-user-1")
        self.assertEqual(profile.api_key, "api-key-xyz")

        # Client should be authenticated after registration
        self.assertTrue("_auth_user_id" in self.client.session)


class LoginFlowTests(TestCase):
    def test_login_redirects_to_onboarding_when_missing_profile(self):
        user = User.objects.create_user(
            username="bob",
            email="bob@example.com",
            password="StrongPass123__",
        )

        resp = self.client.post(
            reverse("accounts_plus:login"),
            {"username": user.username, "password": "StrongPass123__"},
        )

        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("accounts_plus:onboarding_start"))
