#!/usr/bin/env python3
"""
Supplyico Autopilot — autonomous sourcing agent that finds leads, reaches out,
runs sourcing audits, screens leads, and manages the pipeline.

Usage:
    python3 autopilot.py find-leads                              # Scrape for e-commerce brands
    python3 autopilot.py import-leads <file.json|file.csv>       # Import leads from file
    python3 autopilot.py scrape-emails <url1> <url2> ...         # Find emails from websites
    python3 autopilot.py outreach                                # Send cold emails (multi-touch sequence)
    python3 autopilot.py follow-ups                              # Send follow-ups to contacted leads
    python3 autopilot.py check-replies                           # Check inbox for lead replies
    python3 autopilot.py audit <company>                         # Run sourcing audit for a company
    python3 autopilot.py send-screen <email> <name> <company>    # Send pre-call screening quiz
    python3 autopilot.py request-demo <email> <name> <company>   # Check calendar + book (asks you first)
    python3 autopilot.py book-demo <email> <name> <company>      # Book Google Meet directly
    python3 autopilot.py personalize-deck <company>              # Create personalized pitch deck
    python3 autopilot.py pipeline                                # Show pipeline status
    python3 autopilot.py morning                                 # Full daily routine
    python3 autopilot.py run                                     # Run everything autonomously
"""

import sys
import os
import json
import time
import base64
import re
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText

BASE_DIR = Path(__file__).parent
EMAIL_DIR = Path.home() / "email-agent"
CONFIG_FILE = BASE_DIR / "config.json"
LEADS_FILE = BASE_DIR / "leads.json"
AUDIT_DIR = BASE_DIR / "audits"
LOG_FILE = BASE_DIR / "autopilot.log"

AUDIT_DIR.mkdir(exist_ok=True)

SUPPLYICO_EMAIL = "iruka@supplyico.com"
SHEET_ID = "128lUSIRHGNkD7lrikbS9vBcobtIHp4om4tuQEVU4uwU"
PITCH_DECK_ID = "1nAxg9EYIY6jlLIdHTRm4WzAq2fwySaw_KlMXu3tslpA"

# Single business account — all outreach from Supplyico only
EMAIL_ACCOUNTS = [
    {"name": "Supplyico", "token": "token_supplyico.json", "from": "Supplyico <iruka@supplyico.com>"},
]
_email_counter = 0


def _activate_venv():
    venv_site = EMAIL_DIR / "venv" / "lib"
    if venv_site.exists():
        for p in venv_site.glob("python*/site-packages"):
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def get_gmail_service():
    _activate_venv()
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    token_path = EMAIL_DIR / "token_supplyico.json"
    if not token_path.exists():
        log("ERROR: token_supplyico.json not found")
        return None
    creds = Credentials.from_authorized_user_file(str(token_path))
    return build('gmail', 'v1', credentials=creds)


def get_sheets_service():
    _activate_venv()
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    token_path = EMAIL_DIR / "token_supplyico.json"
    creds = Credentials.from_authorized_user_file(str(token_path))
    return build('sheets', 'v4', credentials=creds)


def send_email(to, subject, body, account_index=None):
    """Send email, rotating across accounts for deliverability."""
    global _email_counter
    _activate_venv()
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if account_index is not None:
        acct = EMAIL_ACCOUNTS[account_index % len(EMAIL_ACCOUNTS)]
    else:
        acct = EMAIL_ACCOUNTS[_email_counter % len(EMAIL_ACCOUNTS)]
        _email_counter += 1

    token_path = EMAIL_DIR / acct["token"]
    if not token_path.exists():
        log(f"Token not found: {acct['token']}, falling back to supplyico")
        token_path = EMAIL_DIR / "token_supplyico.json"
        acct = EMAIL_ACCOUNTS[0]

    creds = Credentials.from_authorized_user_file(str(token_path))
    service = build('gmail', 'v1', credentials=creds)

    msg = MIMEText(body)
    msg['to'] = to
    msg['from'] = acct['from']
    msg['subject'] = subject
    msg['reply-to'] = SUPPLYICO_EMAIL
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        service.users().messages().send(userId='me', body={'raw': raw}).execute()
        log(f"Email sent ({acct['name']}) -> {to}: {subject}")
        return True
    except Exception as e:
        log(f"Email failed ({acct['name']}) -> {to}: {e}")
        return False


def load_json(path, default=None):
    if Path(path).exists():
        with open(path) as f:
            return json.load(f)
    return default if default is not None else []


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ============================================================
# PIPELINE — Google Sheets CRM
# ============================================================

def get_pipeline():
    service = get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range="'Pipeline'!A2:P500"
    ).execute()
    rows = result.get('values', [])
    headers = ['stage', 'company', 'contact', 'email', 'instagram', 'website',
               'products', 'monthly_spend', 'found_date', 'contacted_date',
               'audit_sent', 'response', 'savings_found', 'our_fee', 'status', 'notes']
    leads = []
    for row in rows:
        row += [''] * (len(headers) - len(row))
        leads.append({headers[i]: row[i] for i in range(len(headers))})
    return leads


def add_to_pipeline(lead):
    service = get_sheets_service()
    row = [
        lead.get('stage', 'lead'),
        lead.get('company', ''),
        lead.get('contact', ''),
        lead.get('email', ''),
        lead.get('instagram', ''),
        lead.get('website', ''),
        lead.get('products', ''),
        lead.get('monthly_spend', ''),
        lead.get('found_date', datetime.now().strftime('%Y-%m-%d')),
        '', '', '', '', '',
        lead.get('status', 'new'),
        lead.get('notes', ''),
    ]
    service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range="'Pipeline'!A:P",
        valueInputOption='RAW',
        body={'values': [row]}
    ).execute()
    log(f"Added to pipeline: {lead.get('company', '?')}")


def update_pipeline_row(row_index, updates):
    """Update specific columns in a pipeline row (row_index is 0-based from data, +2 for sheet)."""
    service = get_sheets_service()
    sheet_row = row_index + 2
    headers = ['stage', 'company', 'contact', 'email', 'instagram', 'website',
               'products', 'monthly_spend', 'found_date', 'contacted_date',
               'audit_sent', 'response', 'savings_found', 'our_fee', 'status', 'notes']
    for key, value in updates.items():
        if key in headers:
            col_index = headers.index(key)
            col_letter = chr(65 + col_index)
            service.spreadsheets().values().update(
                spreadsheetId=SHEET_ID,
                range=f"'Pipeline'!{col_letter}{sheet_row}",
                valueInputOption='RAW',
                body={'values': [[value]]}
            ).execute()


def show_pipeline():
    leads = get_pipeline()
    if not leads:
        print("\nPipeline is empty. Run: autopilot.py find-leads")
        return

    stages = {}
    for lead in leads:
        stage = lead.get('stage', 'unknown')
        stages.setdefault(stage, []).append(lead)

    print(f"\n{'=' * 60}")
    print(f"  SUPPLYICO PIPELINE — {len(leads)} total leads")
    print(f"{'=' * 60}")

    stage_order = ['lead', 'contacted', 'audit_sent', 'interested', 'client', 'billing']
    for stage in stage_order:
        if stage in stages:
            print(f"\n  [{stage.upper()}] — {len(stages[stage])}")
            for l in stages[stage]:
                spend = l.get('monthly_spend', '?')
                print(f"    {l['company']:25} | {l.get('contact',''):15} | {l.get('email',''):30} | ~€{spend}/mo")

    total_savings = sum(float(l.get('savings_found', 0) or 0) for l in leads)
    total_fees = sum(float(l.get('our_fee', 0) or 0) for l in leads)
    clients = len(stages.get('client', []) + stages.get('billing', []))
    print(f"\n  Clients: {clients} | Total savings found: €{total_savings:.0f} | Our fees: €{total_fees:.0f}")
    print(f"{'=' * 60}\n")


# ============================================================
# LEAD SCRAPING
# ============================================================

_JUNK_EMAIL_PATTERNS = [
    'example.com', 'sentry.io', 'wixpress', 'shopify.com',
    'email.com', 'yourdomain', 'domain.com', '.png', '.jpg',
    '.gif', '.css', '.js', 'placeholder', 'test@',
]
_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'


def _fetch_page(url, timeout=10):
    """Fetch a URL and return decoded HTML, or empty string on failure."""
    for scheme in ('https://', 'http://'):
        full = url if url.startswith('http') else scheme + url
        try:
            req = urllib.request.Request(full, headers={'User-Agent': _UA})
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.read().decode('utf-8', errors='ignore')
        except Exception:
            continue
    return ''


def _extract_emails(html):
    """Pull email addresses from HTML, filtering junk."""
    raw = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', html)
    clean = set()
    for e in raw:
        e = e.lower()
        if not any(p in e for p in _JUNK_EMAIL_PATTERNS):
            clean.add(e)
    return clean


def scrape_contact_email(domain):
    """Try to find a contact email from a website by checking common pages."""
    pages = [
        domain,
        domain.rstrip('/') + '/pages/contact',
        domain.rstrip('/') + '/pages/contact-us',
        domain.rstrip('/') + '/contact',
        domain.rstrip('/') + '/contact-us',
    ]
    all_emails = set()
    for page in pages:
        html = _fetch_page(page)
        if html:
            all_emails |= _extract_emails(html)
        if all_emails:
            break
        time.sleep(0.5)

    if all_emails:
        # Prefer info@, hello@, contact@, customercare@
        for prefix in ('info@', 'hello@', 'contact@', 'customercare@', 'care@', 'sales@'):
            for e in all_emails:
                if e.startswith(prefix):
                    return e
        return next(iter(all_emails))

    # Guess common patterns if nothing scraped
    base = domain.replace('https://', '').replace('http://', '').replace('www.', '')
    return f'hello@{base}'


def find_leads_shopify():
    """Find small e-commerce stores selling physical products."""
    log("Searching for e-commerce leads...")

    search_terms = [
        "irish fashion brand shopify online store",
        "small clothing brand ireland e-commerce",
        "independent skincare brand ireland online",
        "irish accessories brand shop online",
        "uk small fashion brand shopify store",
        "dublin cork galway clothing brand online",
        "irish candle brand shop",
        "irish jewelry brand handmade online",
        "sustainable fashion brand ireland",
        "irish gift shop online e-commerce",
    ]

    existing = get_pipeline()
    existing_domains = {l.get('website', '').lower() for l in existing}
    existing_emails = {l.get('email', '').lower() for l in existing}

    leads_found = []

    for term in search_terms:
        try:
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(term)}"
            req = urllib.request.Request(url, headers={'User-Agent': _UA})
            resp = urllib.request.urlopen(req, timeout=10)
            html = resp.read().decode('utf-8', errors='ignore')

            # Extract result URLs from DuckDuckGo result links
            result_urls = re.findall(r'href="(https?://[^"]+)"', html)
            result_urls += re.findall(r'https?://[a-zA-Z0-9-]+\.myshopify\.com', html)

            for found_url in set(result_urls):
                found_url = found_url.strip('"').strip('/')
                # Skip search engines, social media, directories
                skip = ['duckduckgo', 'google', 'bing', 'facebook', 'instagram',
                        'twitter', 'youtube', 'linkedin', 'pinterest', 'reddit',
                        'wikipedia', 'amazon', 'ebay', 'supplyico', 'etsy']
                if any(s in found_url.lower() for s in skip):
                    continue
                # Must look like a brand website
                if not re.match(r'https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', found_url):
                    continue

                domain = re.sub(r'(/.*)', '', found_url)
                if domain.lower() in existing_domains:
                    continue

                brand_name = domain.replace('https://', '').replace('http://', '').replace('www.', '').split('.')[0]
                if len(brand_name) < 3:
                    continue

                email = scrape_contact_email(domain)
                if email and email.lower() in existing_emails:
                    continue

                lead = {
                    'stage': 'lead',
                    'company': brand_name.replace('-', ' ').title(),
                    'email': email or '',
                    'website': domain,
                    'products': ' '.join(term.split()[:2]),
                    'found_date': datetime.now().strftime('%Y-%m-%d'),
                    'notes': f'Auto-found via search',
                }
                leads_found.append(lead)
                existing_domains.add(domain.lower())
                if email:
                    existing_emails.add(email.lower())

                if len(leads_found) >= 20:
                    break

            time.sleep(2)
        except Exception as e:
            log(f"Search error for '{term}': {e}")

        if len(leads_found) >= 20:
            break

    # Deduplicate
    seen = set()
    unique = []
    for l in leads_found:
        key = l['website'].lower()
        if key not in seen:
            seen.add(key)
            unique.append(l)

    log(f"Found {len(unique)} new leads")

    for lead in unique[:20]:
        add_to_pipeline(lead)

    return unique


def import_leads(filepath):
    """Import leads from a JSON or CSV file into the pipeline.

    JSON format: [{"company": "...", "email": "...", "website": "...", "products": "...", "contact": "...", "monthly_spend": "..."}, ...]
    CSV format: company,email,website,products,contact,monthly_spend (first row = headers)
    """
    path = Path(filepath)
    if not path.exists():
        print(f"File not found: {filepath}")
        return []

    if path.suffix == '.json':
        with open(path) as f:
            data = json.load(f)
    elif path.suffix == '.csv':
        import csv
        with open(path) as f:
            reader = csv.DictReader(f)
            data = list(reader)
    else:
        print(f"Unsupported format: {path.suffix} (use .json or .csv)")
        return []

    existing = get_pipeline()
    existing_emails = {l.get('email', '').lower() for l in existing if l.get('email')}

    imported = []
    for row in data:
        email = row.get('email', '').strip().lower()
        if email and email in existing_emails:
            log(f"Skipping duplicate: {email}")
            continue

        lead = {
            'stage': 'lead',
            'company': row.get('company', row.get('brand', '')).strip(),
            'contact': row.get('contact', row.get('name', '')).strip(),
            'email': email,
            'website': row.get('website', row.get('url', '')).strip(),
            'products': row.get('products', row.get('category', '')).strip(),
            'monthly_spend': row.get('monthly_spend', row.get('spend', '')).strip(),
            'found_date': datetime.now().strftime('%Y-%m-%d'),
            'notes': f'Imported from {path.name}',
        }
        if not lead['company']:
            continue

        add_to_pipeline(lead)
        imported.append(lead)
        if email:
            existing_emails.add(email)

    log(f"Imported {len(imported)} leads from {path.name}")
    return imported


def scrape_emails_from_urls(urls):
    """Given a list of website URLs, scrape each for contact emails and print results."""
    for url in urls:
        url = url.strip()
        if not url:
            continue
        email = scrape_contact_email(url)
        print(f"  {url:40} -> {email or 'not found'}")
        time.sleep(1)


# ============================================================
# OUTREACH ENGINE
# ============================================================

PLAYBOOK_FILE = BASE_DIR / "cold_email_playbook.json"

OUTREACH_SEQUENCE = [
    {
        "touch": 1,
        "name": "cold_open",
        "day_offset": 0,
        "subjects": [
            "Quick question about {product}",
            "{company}'s {product} — sourcing idea",
            "Saving {company} 20-40% on sourcing",
            "Found something for {company}",
        ],
        "body": """Hi {first_name},

I saw {company} selling {product} — {hook}.

I run Supplyico. We help brands like yours find verified suppliers at 20-40% less than you're paying now.

I'd like to run a free sourcing audit on one of your products — takes me a day, costs you nothing. You get a report showing your current price vs what I found.

Want me to run one on {product}?

Iruka
Supplyico | supplyico.netlify.app""",
    },
    {
        "touch": 2,
        "name": "value_add",
        "day_offset": 3,
        "subjects": ["Re: {previous_subject}"],
        "body": """Hi {first_name},

Quick follow-up — I looked into {product_category} sourcing and brands in your space are typically overpaying by 25-35%.

The free audit would show you the exact gap for {company}. No commitment, just data.

Worth a look?

Iruka""",
    },
    {
        "touch": 3,
        "name": "soft_breakup",
        "day_offset": 8,
        "subjects": ["Re: {previous_subject}"],
        "body": """Hi {first_name},

I know you're busy running {company}, so I'll keep this short.

I've got capacity to run 3 more free audits this month. If you want one, just reply with the product you'd like me to look at.

If the timing's off, no hard feelings.

Iruka""",
    },
    {
        "touch": 4,
        "name": "final_breakup",
        "day_offset": 18,
        "subjects": ["Closing the loop"],
        "body": """Hi {first_name},

Looks like the timing isn't right for {company} — totally understand.

If sourcing costs ever become a priority, I'm at iruka@supplyico.com. The free audit offer stays open.

All the best with {company}.

Iruka""",
    },
]

PERSONALIZATION_HOOKS = [
    "nice product range you've got",
    "love what you're building",
    "the brand looks sharp",
    "solid collection",
]


def _get_touch_for_lead(lead):
    """Determine which touch in the sequence this lead should receive."""
    status = lead.get('status', '')
    contacted = lead.get('contacted_date', '')
    if not contacted:
        return 1
    try:
        contacted_dt = datetime.strptime(contacted, '%Y-%m-%d')
    except ValueError:
        return None
    days_since = (datetime.now() - contacted_dt).days

    if 'touch_1' in status and days_since >= 3:
        return 2
    elif 'touch_2' in status and days_since >= 8:
        return 3
    elif 'touch_3' in status and days_since >= 18:
        return 4
    return None


def run_outreach():
    """Send cold emails following the multi-touch sequence."""
    leads = get_pipeline()

    # Touch 1: new leads with email but not yet contacted
    new_leads = [l for l in leads if l.get('stage') == 'lead' and l.get('email')]
    # Follow-ups: contacted leads ready for next touch
    followups = [l for l in leads if l.get('stage') == 'contacted' and l.get('email')]

    if not new_leads and not followups:
        print("\nNo leads ready for outreach.")
        print("Run 'find-leads' first, then add emails to the pipeline sheet.")
        return

    sent = 0
    max_per_run = 30

    # Touch 1 — new cold opens
    for lead in new_leads:
        if sent >= max_per_run:
            break
        touch = OUTREACH_SEQUENCE[0]
        first_name = lead.get('contact', '').split()[0] if lead.get('contact') else 'there'
        product = lead.get('products', 'your products')
        hook = PERSONALIZATION_HOOKS[sent % len(PERSONALIZATION_HOOKS)]
        subject = touch['subjects'][sent % len(touch['subjects'])].format(
            company=lead['company'], product=product,
        )
        body = touch['body'].format(
            first_name=first_name, company=lead['company'],
            product=product, hook=hook,
        )

        if send_email(lead['email'], subject, body):
            row_idx = leads.index(lead)
            update_pipeline_row(row_idx, {
                'stage': 'contacted',
                'contacted_date': datetime.now().strftime('%Y-%m-%d'),
                'status': 'touch_1_sent',
                'notes': f'Subject: {subject}',
            })
            sent += 1
            time.sleep(3)

    # Touches 2-4 — follow-ups
    for lead in followups:
        if sent >= max_per_run:
            break
        touch_num = _get_touch_for_lead(lead)
        if touch_num is None or touch_num > 4:
            continue

        touch = OUTREACH_SEQUENCE[touch_num - 1]
        first_name = lead.get('contact', '').split()[0] if lead.get('contact') else 'there'
        product = lead.get('products', 'your products')
        product_category = product.split()[0] if product else 'product'

        prev_subject = lead.get('notes', '').replace('Subject: ', '') if 'Subject:' in lead.get('notes', '') else f"Saving {lead['company']} 20-40% on sourcing"

        subject = touch['subjects'][0].format(
            company=lead['company'], product=product,
            previous_subject=prev_subject, product_category=product_category,
        )
        body = touch['body'].format(
            first_name=first_name, company=lead['company'],
            product=product, product_category=product_category,
            previous_subject=prev_subject,
        )

        if send_email(lead['email'], subject, body):
            row_idx = leads.index(lead)
            new_status = f'touch_{touch_num}_sent'
            stage = 'contacted' if touch_num < 4 else 'contacted'
            update_pipeline_row(row_idx, {
                'stage': stage,
                'status': new_status,
            })
            sent += 1
            time.sleep(3)

    log(f"Outreach complete: {sent} emails sent")


# ============================================================
# SOURCING AUDIT
# ============================================================

def run_audit(company_name):
    """Run a sourcing audit for a specific company."""
    leads = get_pipeline()
    lead = next((l for l in leads if company_name.lower() in l.get('company', '').lower()), None)

    if not lead:
        print(f"Company '{company_name}' not found in pipeline.")
        return

    product = lead.get('products', 'general product')
    log(f"Running sourcing audit for {lead['company']} — {product}")

    # Search 1688/Alibaba for cheaper alternatives
    search_results = search_suppliers(product)

    audit = {
        "company": lead['company'],
        "product": product,
        "date": datetime.now().isoformat(),
        "current_estimate": lead.get('monthly_spend', 'unknown'),
        "suppliers_found": search_results,
        "potential_savings": "20-40%",
    }

    audit_file = AUDIT_DIR / f"audit_{lead['company'].lower().replace(' ', '_')}.json"
    save_json(audit_file, audit)

    # Generate report text
    report = generate_audit_report(audit)

    print(f"\n{'=' * 60}")
    print(f"  SOURCING AUDIT: {lead['company']}")
    print(f"{'=' * 60}")
    print(report)

    # Update pipeline
    row_idx = leads.index(lead)
    update_pipeline_row(row_idx, {
        'stage': 'audit_sent',
        'audit_sent': datetime.now().strftime('%Y-%m-%d'),
        'status': 'audit_complete',
    })

    # Email the audit if we have their email
    if lead.get('email'):
        send_email(
            lead['email'],
            f"Your Free Sourcing Audit — {lead['company']}",
            f"Hi {lead.get('contact', '').split()[0] if lead.get('contact') else 'there'},\n\n"
            f"Here's the sourcing audit I promised:\n\n{report}\n\n"
            f"Happy to jump on a quick call to walk through these numbers. "
            f"Just reply to this email and we'll set something up.\n\n"
            f"Best,\nIruka\nSupplyico"
        )

    return audit


def search_suppliers(product):
    """Search for supplier alternatives on 1688/Alibaba."""
    results = []

    search_terms = [product]
    if ' ' in product:
        search_terms.append(product.split()[0])

    for term in search_terms[:2]:
        try:
            encoded = urllib.parse.quote(term)
            url = f"https://html.duckduckgo.com/html/?q={encoded}+supplier+wholesale+1688+alibaba"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            resp = urllib.request.urlopen(req, timeout=10)
            html = resp.read().decode('utf-8', errors='ignore')

            # Extract Alibaba links
            alibaba_links = re.findall(r'https?://[a-zA-Z0-9.-]*alibaba\.com[^\s"<>]*', html)
            for link in alibaba_links[:3]:
                results.append({
                    'source': 'alibaba',
                    'url': link,
                    'term': term,
                })

            time.sleep(2)
        except Exception as e:
            log(f"Supplier search error: {e}")

    if not results:
        results.append({
            'source': 'manual',
            'note': f'Manual search needed for: {product}',
            'suggestion': '1688.com, alibaba.com, made-in-china.com',
        })

    return results


def generate_audit_report(audit):
    """Generate a text audit report."""
    report = f"""
SOURCING AUDIT REPORT
Company: {audit['company']}
Product: {audit['product']}
Date: {audit['date'][:10]}

CURRENT SITUATION
Estimated monthly spend: {audit.get('current_estimate', 'Unknown')}

ALTERNATIVE SUPPLIERS FOUND
"""
    for i, s in enumerate(audit.get('suppliers_found', []), 1):
        if s.get('url'):
            report += f"  {i}. {s['source'].title()}: {s['url'][:80]}\n"
        elif s.get('note'):
            report += f"  {i}. {s['note']}\n"

    report += f"""
ESTIMATED SAVINGS
Based on similar audits, brands typically save 20-40% when switching to
optimised suppliers. On a €5,000/month spend, that's €1,000-€2,000/month saved.

HOW SUPPLYICO WORKS
- We find and verify alternative suppliers
- You only pay 25% of verified savings
- No savings = no fee
- No lock-in contract

Next step: Reply to discuss which products to optimise first.

Supplyico — AI-Powered Sourcing
supplyico.netlify.app | iruka@supplyico.com
"""
    return report


# ============================================================
# GOOGLE MEET — Schedule demo calls
# ============================================================

def book_demo(lead_email, lead_name, company, days_from_now=2):
    """Create a Google Calendar event with Meet link and email the lead."""
    _activate_venv()
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(EMAIL_DIR / "token_supplyico.json"))
    cal_service = build('calendar', 'v3', credentials=creds)

    from datetime import timedelta
    start = datetime.now().replace(hour=14, minute=0, second=0) + timedelta(days=days_from_now)
    end = start + timedelta(minutes=30)

    event = {
        'summary': f'Supplyico x {company} — Sourcing Audit Review',
        'description': f'Reviewing the sourcing audit results for {company}.\n\nAgenda:\n1. Walk through audit findings\n2. Discuss potential savings\n3. Next steps\n\nPitch deck: https://docs.google.com/presentation/d/{PITCH_DECK_ID}/edit',
        'start': {'dateTime': start.isoformat(), 'timeZone': 'Europe/Dublin'},
        'end': {'dateTime': end.isoformat(), 'timeZone': 'Europe/Dublin'},
        'attendees': [
            {'email': lead_email},
            {'email': SUPPLYICO_EMAIL},
        ],
        'conferenceData': {
            'createRequest': {
                'requestId': f'supplyico-{company.lower().replace(" ", "-")}-{int(time.time())}',
                'conferenceSolutionKey': {'type': 'hangoutsMeet'},
            }
        },
        'reminders': {'useDefault': False, 'overrides': [
            {'method': 'email', 'minutes': 60},
            {'method': 'popup', 'minutes': 15},
        ]},
    }

    # Auto-generate personalized pitch deck
    deck_info = None
    try:
        leads = get_pipeline()
        lead_data = next((l for l in leads if l.get('email', '').lower() == lead_email.lower()), {})
        product = lead_data.get('products', 'your products')
        spend = lead_data.get('monthly_spend', '')
        spend_val = float(spend) if spend and spend.replace('.', '').isdigit() else None
        deck_info = personalize_pitch_deck(company, lead_name, product, spend_val)
        log(f"Personalized deck ready: {deck_info['url']}")
    except Exception as e:
        log(f"Deck personalization skipped: {e}")

    try:
        created = cal_service.events().insert(
            calendarId='primary',
            body=event,
            conferenceDataVersion=1,
            sendUpdates='all',
        ).execute()

        meet_link = created.get('hangoutLink', 'No Meet link generated')
        event_link = created.get('htmlLink', '')

        log(f"Demo booked: {company} — {start.strftime('%A %d %b at %H:%M')}")
        log(f"  Meet: {meet_link}")
        log(f"  Event: {event_link}")

        deck_line = f"\nAudit deck: {deck_info['url']}\n" if deck_info else ""

        # Send confirmation email
        send_email(
            lead_email,
            f"Supplyico x {company} — Demo Booked",
            f"Hi {lead_name},\n\n"
            f"Great to connect! I've booked us in for {start.strftime('%A %d %B at %I:%M %p')} (Irish time) "
            f"to walk through your sourcing audit results.\n\n"
            f"Google Meet link: {meet_link}\n"
            f"{deck_line}\n"
            f"If the time doesn't work, just reply and we'll reschedule.\n\n"
            f"Looking forward to it!\n\n"
            f"Iruka\nSupplyico",
            account_index=0,
        )

        # Update pipeline
        leads = get_pipeline()
        for i, l in enumerate(leads):
            if l.get('email', '').lower() == lead_email.lower():
                update_pipeline_row(i, {
                    'stage': 'interested',
                    'status': f'demo booked {start.strftime("%d/%m")}',
                    'notes': f'Meet: {meet_link}',
                })
                break

        return {'meet_link': meet_link, 'event_link': event_link, 'time': start.isoformat()}

    except Exception as e:
        log(f"Failed to book demo: {e}")
        return None


# ============================================================
# PITCH DECK — Per-client personalization
# ============================================================

def personalize_pitch_deck(company, contact_name, product, monthly_spend=None):
    """Copy the template pitch deck and personalize it for a specific lead."""
    _activate_venv()
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(EMAIL_DIR / "token_supplyico.json"))
    drive = build('drive', 'v3', credentials=creds)
    slides = build('slides', 'v1', credentials=creds)

    # Copy the template deck
    copy = drive.files().copy(
        fileId=PITCH_DECK_ID,
        body={'name': f'Supplyico x {company} — Sourcing Audit'}
    ).execute()
    new_deck_id = copy['id']

    # Make it viewable by anyone with link
    drive.permissions().create(
        fileId=new_deck_id,
        body={'type': 'anyone', 'role': 'reader'}
    ).execute()

    # Replace placeholder text in the deck
    spend_str = f"€{monthly_spend:,.0f}/month" if monthly_spend else "your current spend"
    savings_low = f"€{float(monthly_spend) * 0.2:,.0f}" if monthly_spend else "20%"
    savings_high = f"€{float(monthly_spend) * 0.4:,.0f}" if monthly_spend else "40%"

    requests = [
        {'replaceAllText': {'containsText': {'text': '{{COMPANY}}', 'matchCase': False}, 'replaceText': company}},
        {'replaceAllText': {'containsText': {'text': '{{CONTACT}}', 'matchCase': False}, 'replaceText': contact_name or 'there'}},
        {'replaceAllText': {'containsText': {'text': '{{PRODUCT}}', 'matchCase': False}, 'replaceText': product or 'your products'}},
        {'replaceAllText': {'containsText': {'text': '{{SPEND}}', 'matchCase': False}, 'replaceText': spend_str}},
        {'replaceAllText': {'containsText': {'text': '{{SAVINGS_LOW}}', 'matchCase': False}, 'replaceText': savings_low}},
        {'replaceAllText': {'containsText': {'text': '{{SAVINGS_HIGH}}', 'matchCase': False}, 'replaceText': savings_high}},
    ]

    try:
        slides.presentations().batchUpdate(
            presentationId=new_deck_id,
            body={'requests': requests}
        ).execute()
    except Exception as e:
        log(f"Slide personalization partial — placeholders may not exist yet: {e}")

    deck_url = f"https://docs.google.com/presentation/d/{new_deck_id}/edit"
    log(f"Personalized deck for {company}: {deck_url}")
    return {'deck_id': new_deck_id, 'url': deck_url}


# ============================================================
# MORNING ROUTINE
# ============================================================

def morning():
    """Full daily autonomous routine."""
    print(f"\n{'=' * 60}")
    print(f"  SUPPLYICO AUTOPILOT — {datetime.now().strftime('%A %d %B %Y')}")
    print(f"{'=' * 60}")

    # 1. Check for replies
    print(f"\n  INBOX")
    service = get_gmail_service()
    if service:
        try:
            results = service.users().messages().list(
                userId='me',
                q='is:unread -from:me newer_than:1d',
                maxResults=10
            ).execute()
            messages = results.get('messages', [])
            if messages:
                print(f"  {len(messages)} unread messages:")
                for msg_meta in messages[:5]:
                    msg = service.users().messages().get(
                        userId='me', id=msg_meta['id'], format='metadata',
                        metadataHeaders=['From', 'Subject']
                    ).execute()
                    headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
                    print(f"    {headers.get('From', '?')[:40]} — {headers.get('Subject', '?')[:50]}")
            else:
                print(f"  No new messages")
        except Exception as e:
            print(f"  Gmail check failed: {e}")

    # 2. Pipeline status
    print(f"\n  PIPELINE")
    leads = get_pipeline()
    stages = {}
    for l in leads:
        stage = l.get('stage', 'unknown')
        stages[stage] = stages.get(stage, 0) + 1
    for stage, count in stages.items():
        print(f"    {stage}: {count}")
    if not leads:
        print(f"    Empty — run find-leads to start")

    # 3. Find new leads
    print(f"\n  LEAD GENERATION")
    new_leads = find_leads_shopify()
    print(f"    Found {len(new_leads)} new leads")

    # 4. Check for replies from leads
    print(f"\n  LEAD REPLIES")
    replied = check_replies()
    screening = check_screening_replies()

    # 5. Summary
    print(f"\n{'=' * 60}")
    print(f"  Next steps:")
    if replied:
        print(f"    1. Send screening quiz to replied leads")
    if screening:
        print(f"    2. Review screening replies and book demos")
    print(f"    3. Add emails to new leads in the Google Sheet")
    print(f"    4. Run 'autopilot.py outreach' to email them")
    print(f"{'=' * 60}\n")


# ============================================================
# FULL AUTONOMOUS RUN
# ============================================================

def run_all():
    """Run everything in sequence — fully autonomous except demo booking."""
    log("=== SUPPLYICO AUTONOMOUS RUN ===")

    # 1. Find leads
    log("Step 1: Finding leads...")
    find_leads_shopify()

    # 2. Outreach
    log("Step 2: Running outreach...")
    run_outreach()

    # 3. Check replies — auto-detect interested leads
    log("Step 3: Checking for replies...")
    replied = check_replies()

    # 4. Auto-send screening to interested leads (no meeting without screening first)
    if replied:
        log(f"Step 4: Sending screening to {len(replied)} replied leads...")
        for lead in replied:
            if lead.get('email') and lead.get('contact'):
                send_screening(lead['email'], lead['contact'], lead.get('company', ''))
                time.sleep(3)

    # 5. Check for screening replies (these need manual demo booking)
    log("Step 5: Checking screening replies...")
    screening = check_screening_replies()

    # 6. Pipeline summary
    log("Step 6: Pipeline summary")
    show_pipeline()

    if screening:
        log(f"ACTION NEEDED: {len(screening)} leads ready to book demos")
        log("Run: autopilot.py request-demo <email> <name> <company>")

    log("=== AUTONOMOUS RUN COMPLETE ===")


# ============================================================
# SCREENING QUIZ — Pre-call qualification
# ============================================================

SCREENING_QUESTIONS = [
    "Company name",
    "Your name and role",
    "What products do you sell?",
    "Roughly how much do you spend on sourcing per month? (€)",
    "What's the biggest sourcing problem you face right now?",
    "Phone number (for call confirmation)",
]

SCREENING_EMAIL_SUBJECT = "Before our call — 5 quick questions"

SCREENING_EMAIL_BODY = """Hi {first_name},

Thanks for your interest in Supplyico.

Before we set up a call, I'd love to get a quick picture of your sourcing so I can prepare something useful for you. Could you reply to this email with answers to these questions?

1. What products do you sell?
2. Roughly how much do you spend on sourcing per month?
3. What's the biggest sourcing problem you face right now?
4. How many SKUs do you source regularly?
5. Your phone number (for call confirmation)

This helps me run a targeted audit before we speak, so the call is actually worth your time.

Iruka
Supplyico | supplyico.netlify.app"""


def send_screening(lead_email, lead_name, company):
    """Send pre-call screening quiz to a lead before booking any meeting."""
    first_name = lead_name.split()[0] if lead_name else 'there'
    body = SCREENING_EMAIL_BODY.format(first_name=first_name)

    if send_email(lead_email, SCREENING_EMAIL_SUBJECT, body):
        log(f"Screening quiz sent to {lead_name} ({company})")
        leads = get_pipeline()
        for i, l in enumerate(leads):
            if l.get('email', '').lower() == lead_email.lower():
                update_pipeline_row(i, {
                    'status': 'screening_sent',
                    'notes': f'Screening sent {datetime.now().strftime("%d/%m")}',
                })
                break
        return True
    return False


def check_screening_replies():
    """Check inbox for screening quiz replies and flag leads ready to book."""
    service = get_gmail_service()
    if not service:
        return []

    results = service.users().messages().list(
        userId='me',
        q='is:unread -from:me newer_than:7d subject:"Before our call"',
        maxResults=20,
    ).execute()
    messages = results.get('messages', [])

    ready = []
    for msg_meta in messages:
        msg = service.users().messages().get(
            userId='me', id=msg_meta['id'], format='metadata',
            metadataHeaders=['From', 'Subject'],
        ).execute()
        headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
        from_addr = headers.get('From', '')
        # Extract email from "Name <email>" format
        email_match = re.search(r'<([^>]+)>', from_addr)
        email = email_match.group(1) if email_match else from_addr

        ready.append({
            'email': email,
            'from': from_addr,
            'msg_id': msg_meta['id'],
        })
        log(f"Screening reply from: {from_addr}")

    if ready:
        log(f"{len(ready)} screening replies found — leads ready to book")
        print(f"\n  LEADS READY TO BOOK ({len(ready)}):")
        for r in ready:
            print(f"    {r['from']}")
        print(f"\n  Run: autopilot.py request-demo <email> <name> <company>")
        print(f"  This will ask you for confirmation before booking.\n")

    return ready


def request_demo(lead_email, lead_name, company):
    """Request a demo booking — checks calendar, shows available slots, asks for confirmation."""
    _activate_venv()
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from datetime import timedelta

    creds = Credentials.from_authorized_user_file(str(EMAIL_DIR / "token_supplyico.json"))
    cal_service = build('calendar', 'v3', credentials=creds)

    # Check calendar for next 5 business days
    now = datetime.now()
    slots = []
    for day_offset in range(1, 8):
        day = now + timedelta(days=day_offset)
        if day.weekday() >= 5:  # Skip weekends
            continue

        # Check for conflicts at 10am, 2pm, 4pm
        for hour in [10, 14, 16]:
            slot_start = day.replace(hour=hour, minute=0, second=0, microsecond=0)
            slot_end = slot_start + timedelta(minutes=30)

            try:
                events = cal_service.events().list(
                    calendarId='primary',
                    timeMin=slot_start.isoformat() + 'Z',
                    timeMax=slot_end.isoformat() + 'Z',
                    singleEvents=True,
                ).execute()
                if not events.get('items'):
                    slots.append(slot_start)
            except Exception:
                slots.append(slot_start)

        if len(slots) >= 6:
            break

    if not slots:
        print("No available slots found in the next week.")
        return

    print(f"\n  BOOK DEMO: {company} ({lead_name})")
    print(f"  Email: {lead_email}")
    print(f"\n  Available slots:")
    for i, slot in enumerate(slots[:6], 1):
        print(f"    {i}. {slot.strftime('%A %d %B at %I:%M %p')}")

    print(f"\n  Type a slot number to book, or 'skip' to skip:")
    choice = input("  > ").strip()

    if choice.lower() == 'skip':
        print("  Skipped.")
        return

    try:
        idx = int(choice) - 1
        chosen_slot = slots[idx]
    except (ValueError, IndexError):
        print("  Invalid choice.")
        return

    print(f"\n  Booking: {chosen_slot.strftime('%A %d %B at %I:%M %p')}")
    print(f"  Confirm? (y/n)")
    confirm = input("  > ").strip().lower()

    if confirm != 'y':
        print("  Cancelled.")
        return

    # Send screening first if not already sent
    leads = get_pipeline()
    lead = next((l for l in leads if l.get('email', '').lower() == lead_email.lower()), None)
    if lead and 'screening' not in lead.get('status', ''):
        send_screening(lead_email, lead_name, company)

    days_from_now = (chosen_slot.date() - now.date()).days
    result = book_demo(lead_email, lead_name, company, days_from_now)
    if result:
        print(f"\n  Booked! Meet link: {result['meet_link']}")


# ============================================================
# AUTO CHECK REPLIES — Detect interested leads
# ============================================================

def check_replies():
    """Check inbox for replies from pipeline leads and update their status."""
    service = get_gmail_service()
    if not service:
        log("Gmail not available")
        return

    leads = get_pipeline()
    lead_emails = {l.get('email', '').lower(): i for i, l in enumerate(leads) if l.get('email')}

    results = service.users().messages().list(
        userId='me',
        q='is:unread -from:me newer_than:7d',
        maxResults=30,
    ).execute()
    messages = results.get('messages', [])

    interested = []
    for msg_meta in messages:
        msg = service.users().messages().get(
            userId='me', id=msg_meta['id'], format='metadata',
            metadataHeaders=['From', 'Subject'],
        ).execute()
        headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
        from_field = headers.get('From', '')
        email_match = re.search(r'<([^>]+)>', from_field)
        sender = (email_match.group(1) if email_match else from_field).lower()

        if sender in lead_emails:
            idx = lead_emails[sender]
            lead = leads[idx]
            interested.append(lead)
            update_pipeline_row(idx, {
                'stage': 'interested',
                'response': f'Replied {datetime.now().strftime("%d/%m")}',
                'status': 'replied — send screening',
            })
            log(f"Lead replied: {lead.get('company')} ({sender})")

    if interested:
        print(f"\n  {len(interested)} LEADS REPLIED:")
        for l in interested:
            print(f"    {l.get('company', '?'):25} | {l.get('email', '?')}")
        print(f"\n  Next: send screening quiz, then book demo after they reply.")
        print(f"  Run: autopilot.py send-screen <email> <name> <company>")
    else:
        print(f"\n  No new replies from pipeline leads.")

    return interested


# ============================================================
# MAIN
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1].lower().replace('-', '_')

    if cmd == "find_leads":
        find_leads_shopify()
    elif cmd in ("import_leads", "import"):
        filepath = sys.argv[2] if len(sys.argv) > 2 else input("File path (.json or .csv): ").strip()
        import_leads(filepath)
    elif cmd in ("scrape_emails", "scrape"):
        if len(sys.argv) > 2:
            scrape_emails_from_urls(sys.argv[2:])
        else:
            print("Usage: autopilot.py scrape-emails <url1> <url2> ...")
    elif cmd == "outreach":
        run_outreach()
    elif cmd in ("follow_ups", "followups"):
        run_outreach()
    elif cmd in ("check_replies", "replies"):
        check_replies()
        check_screening_replies()
    elif cmd == "audit":
        company = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else input("Company name: ").strip()
        run_audit(company)
    elif cmd in ("send_screen", "screen"):
        if len(sys.argv) >= 5:
            send_screening(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]))
        else:
            email = input("Lead email: ").strip()
            name = input("Lead name: ").strip()
            company = input("Company: ").strip()
            send_screening(email, name, company)
    elif cmd == "request_demo":
        if len(sys.argv) >= 5:
            request_demo(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]))
        else:
            email = input("Lead email: ").strip()
            name = input("Lead name: ").strip()
            company = input("Company: ").strip()
            request_demo(email, name, company)
    elif cmd == "pipeline":
        show_pipeline()
    elif cmd == "morning":
        morning()
    elif cmd == "run":
        run_all()
    elif cmd == "book_demo":
        if len(sys.argv) >= 5:
            book_demo(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]))
        else:
            email = input("Lead email: ").strip()
            name = input("Lead name: ").strip()
            company = input("Company: ").strip()
            book_demo(email, name, company)
    elif cmd == "personalize_deck":
        company = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else input("Company name: ").strip()
        leads = get_pipeline()
        lead = next((l for l in leads if company.lower() in l.get('company', '').lower()), None)
        if lead:
            result = personalize_pitch_deck(
                lead['company'],
                lead.get('contact', ''),
                lead.get('products', ''),
                float(lead['monthly_spend']) if lead.get('monthly_spend', '').replace('.', '').isdigit() else None,
            )
            print(f"Deck URL: {result['url']}")
        else:
            print(f"Company '{company}' not found in pipeline.")
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
