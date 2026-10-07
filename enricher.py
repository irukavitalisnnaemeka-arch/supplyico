#!/usr/bin/env python3
"""
Supplyico Lead Enricher — find verified contact emails for pipeline leads.

Combines:
  1. Website scraping (extracts emails from company websites)
  2. Email permutation (guesses patterns: first@domain, info@domain, hello@domain)
  3. SMTP verification (checks if email actually exists)
  4. Holehe check (verifies email is used on social platforms)

Usage:
    python3 enricher.py enrich                    # Enrich all leads missing emails
    python3 enricher.py find <domain>             # Find emails for a domain
    python3 enricher.py verify <email>            # Verify a single email
    python3 enricher.py scrape <url>              # Scrape emails from a URL
"""

import sys
import os
import re
import json
import time
import socket
import smtplib
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
EMAIL_DIR = Path.home() / "email-agent"
CACHE_FILE = BASE_DIR / "enrichment_cache.json"
LOG_FILE = BASE_DIR / "enricher.log"

SHEET_ID = "128lUSIRHGNkD7lrikbS9vBcobtIHp4om4tuQEVU4uwU"

EMAIL_REGEX = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
)

GENERIC_PREFIXES = [
    'info', 'hello', 'contact', 'hi', 'hey', 'support',
    'sales', 'shop', 'orders', 'help', 'team',
]

SKIP_EMAILS = {
    'wix.com', 'sentry.io', 'facebook.com', 'google.com',
    'twitter.com', 'instagram.com', 'example.com', 'email.com',
    'shopify.com', 'myshopify.com', 'cloudflare.com',
}


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


def load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


# ============================================================
# 1. WEBSITE EMAIL SCRAPER
# ============================================================

def scrape_emails_from_url(url):
    """Scrape a website for email addresses."""
    if not url.startswith('http'):
        url = 'https://' + url

    emails = set()
    pages_to_check = [url]

    # Also check common contact pages
    base = url.rstrip('/')
    for path in ['/contact', '/about', '/contact-us', '/pages/contact', '/pages/about']:
        pages_to_check.append(base + path)

    for page_url in pages_to_check:
        try:
            req = urllib.request.Request(page_url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            })
            resp = urllib.request.urlopen(req, timeout=10)
            html = resp.read().decode('utf-8', errors='ignore')

            # Find emails in page
            found = EMAIL_REGEX.findall(html)
            for email in found:
                domain = email.split('@')[1].lower()
                if domain not in SKIP_EMAILS and not email.endswith('.png') and not email.endswith('.jpg'):
                    emails.add(email.lower())

            # Also check mailto: links
            mailto_matches = re.findall(r'mailto:([^"\'?\s]+)', html)
            for m in mailto_matches:
                clean = m.split('?')[0].lower()
                if EMAIL_REGEX.match(clean):
                    domain = clean.split('@')[1]
                    if domain not in SKIP_EMAILS:
                        emails.add(clean)

            time.sleep(1)
        except Exception:
            continue

    return list(emails)


def extract_domain(url):
    """Extract the root domain from a URL."""
    if not url:
        return None
    url = url.replace('https://', '').replace('http://', '').replace('www.', '')
    domain = url.split('/')[0].split('?')[0]
    # Remove myshopify.com suffix
    if '.myshopify.com' in domain:
        domain = domain.replace('.myshopify.com', '') + '.com'
    return domain


# ============================================================
# 2. EMAIL PERMUTATION
# ============================================================

def generate_email_permutations(first_name=None, last_name=None, domain=None):
    """Generate likely email patterns for a person at a company."""
    emails = []

    if domain:
        # Generic addresses (always try these)
        for prefix in GENERIC_PREFIXES:
            emails.append(f"{prefix}@{domain}")

        # Name-based patterns
        if first_name:
            fn = first_name.lower().strip()
            emails.append(f"{fn}@{domain}")
            if last_name:
                ln = last_name.lower().strip()
                emails.extend([
                    f"{fn}.{ln}@{domain}",
                    f"{fn}{ln}@{domain}",
                    f"{fn[0]}{ln}@{domain}",
                    f"{fn[0]}.{ln}@{domain}",
                    f"{fn}{ln[0]}@{domain}",
                    f"{ln}@{domain}",
                    f"{ln}.{fn}@{domain}",
                ])

    return emails


# ============================================================
# 3. SMTP VERIFICATION
# ============================================================

def verify_email_smtp(email):
    """Check if an email address exists via SMTP (basic check)."""
    domain = email.split('@')[1]

    try:
        # Get MX record
        import subprocess
        result = subprocess.run(
            ['dig', '+short', 'MX', domain],
            capture_output=True, text=True, timeout=5
        )
        mx_records = result.stdout.strip().split('\n')
        if not mx_records or not mx_records[0]:
            return 'no_mx'

        # Parse MX host (format: "10 mail.example.com.")
        mx_host = mx_records[0].split()[-1].rstrip('.')

        # Connect and check
        server = smtplib.SMTP(timeout=10)
        server.connect(mx_host, 25)
        server.helo('supplyico.com')
        server.mail('check@supplyico.com')
        code, _ = server.rcpt(email)
        server.quit()

        if code == 250:
            return 'valid'
        elif code == 550:
            return 'invalid'
        else:
            return 'unknown'

    except Exception:
        return 'unknown'


# ============================================================
# 4. HOLEHE VERIFICATION
# ============================================================

def verify_email_holehe(email):
    """Check if email is registered on social platforms."""
    try:
        _activate_venv()
        import subprocess
        result = subprocess.run(
            [str(EMAIL_DIR / "venv" / "bin" / "python3"), '-I', '-m', 'holehe', email],
            capture_output=True, text=True, timeout=30,
            cwd=str(BASE_DIR),
        )
        output = result.stdout
        # Count positive hits
        positives = output.count('[+]')
        return {'registered_on': positives, 'exists': positives > 0}
    except Exception as e:
        return {'registered_on': 0, 'exists': None, 'error': str(e)}


# ============================================================
# 5. SEARCH ENGINE EMAIL FINDING
# ============================================================

def search_email_for_brand(brand_name, domain=None):
    """Search DuckDuckGo for a brand's contact email."""
    queries = [
        f'"{brand_name}" contact email',
        f'"{brand_name}" email address',
    ]
    if domain:
        queries.append(f'site:{domain} email contact')
        queries.append(f'"@{domain}"')

    emails = set()
    for q in queries[:3]:
        try:
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            resp = urllib.request.urlopen(req, timeout=10)
            html = resp.read().decode('utf-8', errors='ignore')

            found = EMAIL_REGEX.findall(html)
            for email in found:
                d = email.split('@')[1].lower()
                if d not in SKIP_EMAILS:
                    emails.add(email.lower())

            time.sleep(2)
        except Exception:
            continue

    return list(emails)


# ============================================================
# PIPELINE INTEGRATION
# ============================================================

def get_sheets_service():
    _activate_venv()
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    token_path = EMAIL_DIR / "token_supplyico.json"
    creds = Credentials.from_authorized_user_file(str(token_path))
    return build('sheets', 'v4', credentials=creds)


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


def update_pipeline_email(row_index, email):
    service = get_sheets_service()
    sheet_row = row_index + 2
    service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'Pipeline'!D{sheet_row}",
        valueInputOption='RAW',
        body={'values': [[email]]}
    ).execute()


def enrich_pipeline():
    """Find emails for all leads that are missing them."""
    leads = get_pipeline()
    cache = load_cache()
    enriched = 0

    leads_needing_email = [
        (i, l) for i, l in enumerate(leads)
        if not l.get('email') and l.get('stage') == 'lead'
    ]

    if not leads_needing_email:
        print("\n  All leads already have emails.")
        return

    print(f"\n  {len(leads_needing_email)} leads need emails. Enriching...\n")

    for idx, lead in leads_needing_email:
        company = lead.get('company', '')
        website = lead.get('website', '')
        contact = lead.get('contact', '')
        domain = extract_domain(website)

        log(f"Enriching: {company} ({website})")

        # Check cache first
        cache_key = f"{company}:{domain}"
        if cache_key in cache and cache[cache_key].get('email'):
            email = cache[cache_key]['email']
            log(f"  Cache hit: {email}")
            update_pipeline_email(idx, email)
            enriched += 1
            continue

        found_emails = []

        # Method 1: Scrape website
        if website:
            log(f"  Scraping {website}...")
            scraped = scrape_emails_from_url(website)
            found_emails.extend(scraped)
            if scraped:
                log(f"  Found on website: {', '.join(scraped)}")

        # Method 2: Search engine
        log(f"  Searching for {company} email...")
        searched = search_email_for_brand(company, domain)
        found_emails.extend(searched)
        if searched:
            log(f"  Found via search: {', '.join(searched)}")

        # Method 3: Generate permutations
        if domain and not found_emails:
            log(f"  Generating permutations for {domain}...")
            first = contact.split()[0] if contact else None
            last = contact.split()[-1] if contact and len(contact.split()) > 1 else None
            perms = generate_email_permutations(first, last, domain)
            found_emails.extend(perms[:5])

        # Deduplicate and pick the best one
        found_emails = list(dict.fromkeys(found_emails))

        if found_emails:
            # Prefer non-generic emails, then info@, then others
            best = None
            for email in found_emails:
                prefix = email.split('@')[0]
                if prefix not in GENERIC_PREFIXES:
                    best = email
                    break
            if not best:
                for pref in ['info', 'hello', 'contact', 'hi', 'sales', 'shop']:
                    for email in found_emails:
                        if email.startswith(pref + '@'):
                            best = email
                            break
                    if best:
                        break
            if not best:
                best = found_emails[0]

            log(f"  Best email: {best}")
            update_pipeline_email(idx, best)
            cache[cache_key] = {
                'email': best,
                'all_found': found_emails,
                'method': 'auto',
                'date': datetime.now().isoformat(),
            }
            enriched += 1
        else:
            log(f"  No email found for {company}")
            cache[cache_key] = {
                'email': None,
                'date': datetime.now().isoformat(),
            }

        save_cache(cache)
        time.sleep(2)

    log(f"\nEnrichment complete: {enriched}/{len(leads_needing_email)} leads got emails")


def find_emails_for_domain(domain):
    """Find all emails associated with a domain."""
    print(f"\n  Finding emails for: {domain}\n")

    # Website scrape
    print(f"  [1] Scraping website...")
    scraped = scrape_emails_from_url(f"https://{domain}")
    for e in scraped:
        print(f"      Found: {e}")

    # Search engine
    print(f"  [2] Searching DuckDuckGo...")
    searched = search_email_for_brand(domain.split('.')[0], domain)
    for e in searched:
        if e not in scraped:
            print(f"      Found: {e}")

    # Permutations
    print(f"  [3] Common patterns...")
    perms = generate_email_permutations(domain=domain)
    for e in perms[:5]:
        if e not in scraped and e not in searched:
            print(f"      Guess: {e}")

    all_found = list(dict.fromkeys(scraped + searched))
    print(f"\n  Total verified: {len(all_found)}")
    print(f"  Guesses: {len(perms)}")

    if all_found:
        print(f"\n  Best bet: {all_found[0]}")

    return all_found


# ============================================================
# MAIN
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1].lower()

    if cmd == "enrich":
        enrich_pipeline()
    elif cmd == "find":
        domain = sys.argv[2] if len(sys.argv) > 2 else input("Domain: ").strip()
        find_emails_for_domain(domain)
    elif cmd == "verify":
        email = sys.argv[2] if len(sys.argv) > 2 else input("Email: ").strip()
        print(f"\n  SMTP check: {verify_email_smtp(email)}")
        print(f"  Holehe check: {verify_email_holehe(email)}")
    elif cmd == "scrape":
        url = sys.argv[2] if len(sys.argv) > 2 else input("URL: ").strip()
        emails = scrape_emails_from_url(url)
        for e in emails:
            print(f"  {e}")
        if not emails:
            print("  No emails found.")
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
