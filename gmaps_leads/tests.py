
from django.urls import reverse
from rest_framework.test import APITestCase
from gmaps_leads.models import GmapsLead


class LeadCategoryStatsAPITest(APITestCase):
    def setUp(self):
        # Create leads with different categories, phones, and websites
        GmapsLead.objects.create(title="A", category="Cafe", phone="905555555555", website="https://a.com")
        GmapsLead.objects.create(title="B", category="Cafe", phone="902123456789", website="")
        GmapsLead.objects.create(title="C", category="Bakery", phone="905444444444", website="https://c.com")
        GmapsLead.objects.create(title="D", category="Bakery", phone="", website="")
        GmapsLead.objects.create(title="E", category="Bakery", phone="905333333333", website=None)

    def _assert_category_stats(self, url_name: str):
        url = reverse(url_name)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('categories', data)
        categories = {c['category']: c for c in data['categories']}
        self.assertIn('Cafe', categories)
        self.assertIn('Bakery', categories)
        # Cafe: 2 leads, 1 whatsapp, 1 website
        self.assertEqual(categories['Cafe']['total_leads'], 2)
        self.assertEqual(categories['Cafe']['leads_with_whatsapp'], 1)
        self.assertEqual(categories['Cafe']['leads_with_website'], 1)
        # Bakery: 3 leads, 2 whatsapp, 1 website
        self.assertEqual(categories['Bakery']['total_leads'], 3)
        self.assertEqual(categories['Bakery']['leads_with_whatsapp'], 2)
        self.assertEqual(categories['Bakery']['leads_with_website'], 1)

    def test_category_stats_under_api_prefix(self):
        self._assert_category_stats('gmaps_leads_api:api-leads-category-stats')

    def test_category_stats_under_gmaps_prefix(self):
        self._assert_category_stats('gmaps_leads:api-leads-category-stats')
