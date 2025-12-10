"""
Website scraper service for extracting emails and structured content from lead websites.

Designed to be AI-friendly - extracts structured data that can be used by
AI agents to generate contextual assistant prompts.

Usage:
    from gmaps_leads.website_scraper import WebsiteScraper, scrape_lead_website
    
    # Scrape single lead
    website_data = scrape_lead_website(lead)
    
    # Scrape with custom options
    scraper = WebsiteScraper(timeout=30)
    result = scraper.scrape(url)
"""
import re
import logging
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlparse, urljoin
from django.utils import timezone

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Email regex pattern - matches most common email formats
EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    re.IGNORECASE
)

# Phone pattern for Turkish numbers
PHONE_PATTERN = re.compile(
    r'(?:\+90|0)?[\s.-]?(?:\d{3})[\s.-]?(?:\d{3})[\s.-]?(?:\d{2})[\s.-]?(?:\d{2})',
    re.IGNORECASE
)

# Social media domains
SOCIAL_DOMAINS = {
    'facebook.com': 'facebook',
    'fb.com': 'facebook',
    'twitter.com': 'twitter',
    'x.com': 'twitter',
    'instagram.com': 'instagram',
    'linkedin.com': 'linkedin',
    'youtube.com': 'youtube',
    'tiktok.com': 'tiktok',
    'pinterest.com': 'pinterest',
    'whatsapp.com': 'whatsapp',
}


class WebsiteScraper:
    """
    Scrapes websites to extract emails and structured content.
    """
    
    def __init__(self, timeout: int = 30, max_content_length: int = 5_000_000):
        self.timeout = timeout
        self.max_content_length = max_content_length
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5,tr;q=0.3',
        })
    
    def scrape(self, url: str) -> Dict:
        """
        Scrape a website and extract structured content.
        
        Args:
            url: The website URL to scrape
            
        Returns:
            Dictionary with scraped data
        """
        result = {
            'url': url,
            'final_url': None,
            'status': 'pending',
            'error_message': None,
            'http_status_code': None,
            'emails': [],
            'page_title': None,
            'meta_description': None,
            'meta_keywords': None,
            'headings': {},
            'paragraphs': [],
            'navigation_links': [],
            'footer_content': None,
            'phone_numbers': [],
            'addresses': [],
            'social_links': {},
            'full_text': None,
            'raw_html': None,
        }
        
        try:
            # Ensure URL has scheme
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            result['status'] = 'scraping'
            
            # Fetch the page
            response = self.session.get(
                url,
                timeout=self.timeout,
                allow_redirects=True,
                stream=True
            )
            
            result['http_status_code'] = response.status_code
            result['final_url'] = response.url
            
            if response.status_code != 200:
                result['status'] = 'failed'
                result['error_message'] = f'HTTP {response.status_code}'
                return result
            
            # Check content type
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' not in content_type.lower():
                result['status'] = 'failed'
                result['error_message'] = f'Not HTML: {content_type}'
                return result
            
            # Get content (with size limit)
            content = response.content[:self.max_content_length]
            html = content.decode('utf-8', errors='ignore')
            
            # Store raw HTML (truncated)
            result['raw_html'] = html[:500_000]  # Max 500KB
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract data
            result['emails'] = self._extract_emails(soup, html)
            result['page_title'] = self._extract_title(soup)
            result['meta_description'] = self._extract_meta(soup, 'description')
            result['meta_keywords'] = self._extract_meta(soup, 'keywords')
            result['headings'] = self._extract_headings(soup)
            result['paragraphs'] = self._extract_paragraphs(soup)
            result['navigation_links'] = self._extract_navigation(soup)
            result['footer_content'] = self._extract_footer(soup)
            result['phone_numbers'] = self._extract_phones(html)
            result['social_links'] = self._extract_social_links(soup, url)
            result['full_text'] = self._extract_full_text(soup)
            
            result['status'] = 'completed' if result['full_text'] else 'no_content'
            
        except requests.Timeout:
            result['status'] = 'failed'
            result['error_message'] = 'Connection timeout'
        except requests.RequestException as e:
            result['status'] = 'failed'
            result['error_message'] = str(e)[:500]
        except Exception as e:
            result['status'] = 'failed'
            result['error_message'] = f'Error: {str(e)[:500]}'
            logger.exception(f'Error scraping {url}')
        
        return result
    
    def _extract_emails(self, soup: BeautifulSoup, html: str) -> List[str]:
        """Extract unique email addresses from the page."""
        emails = set()
        
        # Find in raw HTML (catches obfuscated emails)
        for match in EMAIL_PATTERN.findall(html):
            email = match.lower()
            # Filter out common false positives
            if not any(x in email for x in ['example.com', 'domain.com', 'email.com', 'test.com', '.png', '.jpg', '.gif', '.css', '.js']):
                emails.add(email)
        
        # Also check mailto: links
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if href.startswith('mailto:'):
                email = href[7:].split('?')[0].lower()
                if EMAIL_PATTERN.match(email):
                    emails.add(email)
        
        return sorted(list(emails))
    
    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract page title."""
        title_tag = soup.find('title')
        if title_tag:
            return title_tag.get_text(strip=True)[:500]
        return None
    
    def _extract_meta(self, soup: BeautifulSoup, name: str) -> Optional[str]:
        """Extract meta tag content."""
        meta = soup.find('meta', attrs={'name': name})
        if meta:
            return meta.get('content', '')[:1000]
        
        # Also try og: tags
        meta = soup.find('meta', attrs={'property': f'og:{name}'})
        if meta:
            return meta.get('content', '')[:1000]
        
        return None
    
    def _extract_headings(self, soup: BeautifulSoup) -> Dict[str, List[str]]:
        """Extract all headings by level."""
        headings = {}
        for level in range(1, 7):
            tag = f'h{level}'
            found = []
            for h in soup.find_all(tag):
                text = h.get_text(strip=True)
                if text and len(text) > 1:
                    found.append(text[:200])
            if found:
                headings[tag] = found[:20]  # Max 20 per level
        return headings
    
    def _extract_paragraphs(self, soup: BeautifulSoup) -> List[str]:
        """Extract main paragraph content."""
        paragraphs = []
        
        # Remove script/style/nav elements
        for element in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            element.decompose()
        
        # Find main content area
        main = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile(r'content|main|body', re.I))
        search_in = main if main else soup
        
        for p in search_in.find_all('p'):
            text = p.get_text(strip=True)
            # Filter short/empty paragraphs
            if text and len(text) > 30:
                paragraphs.append(text[:1000])
                if len(paragraphs) >= 50:  # Max 50 paragraphs
                    break
        
        return paragraphs
    
    def _extract_navigation(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract main navigation menu items."""
        nav_items = []
        
        # Look for nav element or common nav classes
        nav = soup.find('nav') or soup.find(class_=re.compile(r'nav|menu|navigation', re.I))
        
        if nav:
            for link in nav.find_all('a', href=True)[:30]:
                text = link.get_text(strip=True)
                if text and len(text) < 50:
                    nav_items.append({
                        'text': text,
                        'href': link.get('href', '')
                    })
        
        return nav_items
    
    def _extract_footer(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract footer text content."""
        footer = soup.find('footer')
        if footer:
            # Get text, clean up whitespace
            text = footer.get_text(separator=' ', strip=True)
            # Limit length
            return text[:2000] if text else None
        return None
    
    def _extract_phones(self, html: str) -> List[str]:
        """Extract phone numbers from HTML."""
        phones = set()
        for match in PHONE_PATTERN.findall(html):
            # Clean up the phone number
            cleaned = re.sub(r'[\s.-]', '', match)
            if len(cleaned) >= 10:
                phones.add(cleaned)
        return sorted(list(phones))[:10]
    
    def _extract_social_links(self, soup: BeautifulSoup, base_url: str) -> Dict[str, str]:
        """Extract social media links."""
        social = {}
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            
            # Parse the URL
            try:
                parsed = urlparse(href)
                domain = parsed.netloc.lower().replace('www.', '')
                
                for social_domain, social_name in SOCIAL_DOMAINS.items():
                    if social_domain in domain:
                        if social_name not in social:
                            social[social_name] = href
                        break
            except:
                continue
        
        return social
    
    def _extract_full_text(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract full page text content, cleaned."""
        # Remove unwanted elements
        for element in soup.find_all(['script', 'style', 'noscript', 'iframe']):
            element.decompose()
        
        # Get text
        text = soup.get_text(separator=' ', strip=True)
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Limit length
        return text[:50000] if text else None


def scrape_lead_website(lead, force: bool = False) -> Optional['LeadWebsite']:
    """
    Scrape website for a lead and save the data.
    
    Args:
        lead: GmapsLead instance
        force: If True, re-scrape even if already scraped
        
    Returns:
        LeadWebsite instance or None if no website
    """
    from .models import LeadWebsite
    
    if not lead.website:
        return None
    
    # Check if already scraped
    existing = LeadWebsite.objects.filter(lead=lead).first()
    if existing and not force:
        return existing
    
    # Scrape the website
    scraper = WebsiteScraper()
    result = scraper.scrape(lead.website)
    
    # Create or update LeadWebsite
    if existing:
        website_data = existing
    else:
        website_data = LeadWebsite(lead=lead)
    
    # Update fields
    website_data.url = lead.website
    website_data.final_url = result.get('final_url')
    website_data.status = result.get('status', 'failed')
    website_data.error_message = result.get('error_message')
    website_data.http_status_code = result.get('http_status_code')
    
    website_data.emails = result.get('emails', [])
    website_data.emails_count = len(result.get('emails', []))
    
    website_data.page_title = result.get('page_title')
    website_data.meta_description = result.get('meta_description')
    website_data.meta_keywords = result.get('meta_keywords')
    
    website_data.headings = result.get('headings', {})
    website_data.paragraphs = result.get('paragraphs', [])
    website_data.navigation_links = result.get('navigation_links', [])
    website_data.footer_content = result.get('footer_content')
    
    website_data.phone_numbers = result.get('phone_numbers', [])
    website_data.social_links = result.get('social_links', {})
    
    website_data.full_text = result.get('full_text')
    website_data.full_text_length = len(result.get('full_text', '') or '')
    
    # Don't store raw HTML by default (save space)
    # website_data.raw_html = result.get('raw_html')
    
    website_data.scraped_at = timezone.now()
    website_data.save()
    
    return website_data
