# SaaS Dashboard

Django-based dashboard for managing Google Maps leads, WhatsApp contacts, and AI-powered email outreach.

## 🚀 Features

### Google Maps Lead Scraping
- Integration with external GMaps scraper API
- Automatic job polling and lead import
- 342+ leads with full business data (phone, website, reviews, location)

### WhatsApp Contact Extraction
- Extracts Turkish mobile numbers (905XX) as WhatsApp contacts
- Generates chat IDs (`@c.us`) and JIDs (`@s.whatsapp.net`)
- 145+ WhatsApp contacts extracted

### Website Scraping
- Scrapes business websites for emails and structured content
- Extracts: emails, phone numbers, services, social links
- AI-ready structured data format

### AI Email Templates
- Rich text email templates linked to leads
- Status workflow: `draft` → `ready` → `approved` → `sent`
- Django signals for workflow automation
- Full OpenAPI 3.1 schema for LLM integration

## 📡 API Endpoints

### OpenAPI Schema (for LLMs)
| URL | Format | Purpose |
|-----|--------|---------|
| `/api/openapi.json` | JSON | **For AI agents** |
| `/api/schema/swagger/` | HTML | Interactive docs |
| `/api/schema/redoc/` | HTML | ReDoc documentation |

### AI Email Generation Workflow
```
GET  /gmaps-leads/api/leads/with-emails/           # Find leads ready for outreach
GET  /gmaps-leads/api/leads/{id}/context/          # Get lead info for AI
POST /gmaps-leads/api/leads/{id}/email-template/   # Submit AI-generated email
PATCH /gmaps-leads/api/email-templates/{id}/status/ # Update status (triggers signals)
```

### Lead Management
```
GET  /gmaps-leads/api/leads/                       # List all leads
GET  /gmaps-leads/api/leads/{id}/                  # Get lead details
GET  /gmaps-leads/api/jobs/                        # List scrape jobs
POST /gmaps-leads/api/jobs/{id}/import_results/    # Import job results
```

## 🛠️ Management Commands

```bash
# Sync all jobs from external scraper API
python manage.py sync_scraper_jobs --import-leads

# Poll pending jobs for completion
python manage.py poll_scrape_jobs --min-age 600

# Extract WhatsApp contacts from leads
python manage.py extract_whatsapp_contacts --stats

# Scrape websites for emails
python manage.py scrape_lead_websites --limit 50 --delay 2
```

## 🔧 Setup

### Prerequisites
- Python 3.10+
- PostgreSQL (for n8n/evolution databases)
- SQLite (for default Django database)

### Installation
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run server
python manage.py runserver 0.0.0.0:8000
```

### Environment Variables
```env
# Django
DEBUG=True
SECRET_KEY=your-secret-key

# Google Maps Scraper
GMAPS_SCRAPER_API_URL=https://gmaps.delilclinic.com

# OpenAI (for SQL Explorer AI assistant)
OPENAI_API_KEY=sk-...

# N8N Database (read-only mirror)
N8N_DB_NAME=n8n
N8N_DB_USER=postgres
N8N_DB_PASSWORD=...
N8N_DB_HOST=localhost
N8N_DB_PORT=5432

# Evolution API Database (optional)
EVO_DB_NAME=evolution
EVO_DB_USER=postgres
EVO_DB_PASSWORD=...
EVO_DB_HOST=localhost
EVO_DB_PORT=5432
```

## 📊 Admin Features

Access at `/admin/`:

- **Scrape Jobs**: Create, monitor, and import Google Maps scrape jobs
- **Leads**: Filter by phone type (WhatsApp/Local), website presence, emails
- **WhatsApp Contacts**: Manage extracted contacts
- **Lead Websites**: View scraped website data and emails
- **Email Templates**: Review and approve AI-generated emails

### Admin Filters
- 📱 Phone Type: WhatsApp (905XX), Local Landline (902XX), Other, None
- 🌐 Website: Has Website / No Website
- 📧 Emails: Has Emails / No Emails
- ✅ WhatsApp Extracted: Yes / No

## 🔌 Integrations

### SQL Explorer
Browse n8n and Evolution API databases at `/explorer/`

### Pengaa Flow
React-based workflow editor at `/static/pengaa-flow/`

## 📝 License

MIT
