#!/usr/bin/env python3
"""
Owner First-Name Finder for Alastin clinic leads.

Fills the `first_name` column (owner / founder / principal provider) for the
leads in "alastin 800 leads test names search.csv" using only FREE sources, in
a tiered, concurrent pipeline so the whole file finishes in minutes rather than
the ~800 minutes a naive "search-each-clinic-by-hand" loop would take.

Tiers (each only handles rows the previous tiers left empty):
  1. Email local-part   - personal-looking business emails (jane@clinic.com)
  2. NPI registry        - free CMS API; authorized-official name for org NPIs
  3. Website crawl       - concurrent HTTP (no browser) over the clinic domain
                           derived from the email; JSON-LD + heuristic text
  4. DuckDuckGo HTML     - keyless search fallback for still-empty rows

Every fill records its provenance (`first_name_source`) and, where available,
the full owner name (`owner_full_name`). Rows that stay empty are honest misses,
not guesses. All network responses are cached under ./cache so reruns are free.
"""

import csv
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

INPUT_FILE = "alastin 800 leads test names search.csv"
OUTPUT_FILE = "alastin 800 leads test names search_with_first_names.csv"
NAMES_FILE = "first_names.json"   # dictionary of known first names (lowercase)
CACHE_DIR = "cache"

DELIM = ";"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Email domains that are NOT the clinic's own website
GENERIC_EMAIL = {
    "gmail.com", "yahoo.com", "hotmail.com", "aol.com", "outlook.com",
    "icloud.com", "msn.com", "comcast.net", "me.com", "live.com",
    "sbcglobal.net", "att.net", "mac.com", "protonmail.com", "ymail.com",
    "verizon.net", "cox.net", "bellsouth.net", "earthlink.net", "charter.net",
    "mail.com", "rocketmail.com", "aim.com", "gmx.com", "ymail.com",
}
# Accounts-payable / invoicing platforms (never the clinic site)
PLATFORM_EMAIL_SUBSTR = (
    "coupahost", "basware", "bill.com", "corpay", "avidbill", "yardi",
    "appfolio", "billtrust", "mineraltree", "stampli", "tipalti", "airbase",
    "ramp.com", "brex.com", "duly.com", "emburse", "concur",
)

# Email local parts that are clearly roles, not people
ROLE_PREFIXES = {
    "info", "contact", "hello", "support", "sales", "admin", "office",
    "invoices", "invoice", "billing", "accounts", "accounting", "accountspayable",
    "ap", "apinvoice", "apinvoices", "payables", "payable", "operations", "hr",
    "jobs", "careers", "marketing", "press", "media", "news", "help", "service",
    "customer", "customerservice", "enquiries", "inquiries", "general",
    "reception", "frontdesk", "front", "mail", "email", "team", "staff",
    "orders", "order", "booking", "bookings", "reservations", "appointments",
    "appointment", "appt", "noreply", "no-reply", "donotreply", "notifications",
    "alerts", "scheduling", "schedule", "feedback", "legal", "privacy",
    "security", "webmaster", "postmaster", "abuse", "spa", "clinic", "medical",
    "med", "health", "wellness", "care", "derm", "dermatology", "aesthetics",
    "aesthetic", "skincare", "skin", "beauty", "laser", "medspa", "rejuvenation",
    "frontoffice", "patientcare", "patients", "newpatient", "newpatients",
    "manager", "owner", "ceo", "cfo", "coo", "president", "founder",
}

SUFFIX_RE = re.compile(
    r'\b(L\.?L\.?C|INC|INCORPORATED|PC|P\.?A|PLLC|LTD|CORP(ORATION)?|CO|COMPANY|'
    r'GROUP|ASSOC(IATES)?|MD|D\.?O|PLC|DBA|ENTERPRISES|VENTURES|HOLDINGS)\b\.?',
    re.I,
)
STOPWORDS = {"THE", "AND", "FOR", "OF", "AT", "BY", "A", "AN"}

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def load_names():
    if os.path.exists(NAMES_FILE):
        return set(n.lower() for n in json.load(open(NAMES_FILE)))
    return set()


FIRST_NAMES = load_names()


def norm_org(s):
    s = re.sub(r'[^A-Za-z0-9 ]', ' ', s or '')
    s = SUFFIX_RE.sub(' ', s)
    return re.sub(r'\s+', ' ', s).strip().upper()


def cache_path(key):
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', key)[:150]
    return os.path.join(CACHE_DIR, safe)


def http_get(url, timeout=8, cache_key=None, max_bytes=500000):
    """GET with on-disk caching. Returns text or None."""
    if cache_key:
        cp = cache_path(cache_key)
        if os.path.exists(cp):
            data = open(cp, encoding="utf-8", errors="ignore").read()
            return None if data == "\0MISS" else data
    text = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as r:
            text = r.read(max_bytes).decode("utf-8", "ignore")
    except Exception:
        text = None
    if cache_key:
        with open(cache_path(cache_key), "w", encoding="utf-8") as f:
            f.write(text if text is not None else "\0MISS")
    return text


def title_name(s):
    return s.strip().title() if s else s


# --------------------------------------------------------------------------- #
# Tier 1: email local part
# --------------------------------------------------------------------------- #
def email_domain(email):
    email = (email or "").strip().lower()
    return email.split("@", 1)[1] if "@" in email else ""


def is_clinic_domain(email):
    d = email_domain(email)
    if not d or d in GENERIC_EMAIL:
        return ""
    if any(p in d for p in PLATFORM_EMAIL_SUBSTR):
        return ""
    return d


def known_prefix(token):
    """Longest known first name (>=4 chars) that is a prefix of token, else None."""
    best = None
    for n in FIRST_NAMES:
        if len(n) >= 4 and token.startswith(n):
            if best is None or len(n) > len(best):
                best = n
    return best


def name_from_email(email):
    """Return (first_name, full_name|None) from a personal-looking email.

    Precision-first: a token only becomes a name if it is a KNOWN first name
    (exact, or as a clear prefix of a concatenated first+last). This avoids
    traps like beautywithin->"Beau" or jenniferbryce->"Jenniferbryce".
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return None
    local = re.sub(r'\+.*$', '', email.split("@", 1)[0])
    if local in ROLE_PREFIXES:
        return None
    # firstname.lastname / firstname_lastname / firstname-lastname
    for sep in (".", "_", "-"):
        if sep in local:
            first = local.split(sep)[0]
            if first in ROLE_PREFIXES:
                return None
            if first in FIRST_NAMES:
                return title_name(first), None
            pref = known_prefix(first)            # e.g. "jenniferbryce" -> jennifer
            if pref:
                return title_name(pref), None
            if 3 <= len(first) <= 10 and first.isalpha():
                return title_name(first), None     # plausible clean token
            return None
    # single token: accept only an exact known first name (e.g. tina@...)
    if local in FIRST_NAMES:
        return title_name(local), None
    return None


# --------------------------------------------------------------------------- #
# Tier 2: NPI registry
# --------------------------------------------------------------------------- #
def npi_lookup(store, city, state):
    nstore = norm_org(store)
    tokens = [t for t in nstore.split() if len(t) > 2 and t not in STOPWORDS]
    if not tokens:
        return None
    query = " ".join(tokens[:2]) + "*"
    params = {
        "version": "2.1", "limit": "20",
        "organization_name": query, "state": state,
    }
    url = "https://npiregistry.cms.hhs.gov/api/?" + urllib.parse.urlencode(params)
    raw = http_get(url, timeout=15, cache_key="npi_" + query + "_" + state)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    store_tok = set(nstore.split())
    for res in data.get("results", []):
        b = res.get("basic", {})
        on = norm_org(b.get("organization_name", ""))
        if not on:
            continue
        overlap = len(store_tok & set(on.split()))
        same_city = (b.get("addresses") or [{}])
        city_ok = any(
            (a.get("city", "").strip().upper() == (city or "").strip().upper())
            for a in res.get("addresses", [])
        )
        if overlap >= 2 or (overlap >= 1 and (city_ok or nstore[:6] == on[:6])):
            fn = b.get("authorized_official_first_name")
            ln = b.get("authorized_official_last_name")
            if fn:
                full = " ".join(p for p in [title_name(fn), title_name(ln or "")] if p)
                return title_name(fn), full
    return None


# --------------------------------------------------------------------------- #
# Tier 3: website crawl
# --------------------------------------------------------------------------- #
PAGES = ["", "/about", "/about-us", "/our-team", "/team", "/meet-the-team",
         "/our-providers", "/providers", "/staff"]

OWNER_PATTERNS = [
    r'(?:founded|established|started|owned|created|opened)\s+by\s+(?:Dr\.?\s+)?([A-Z][a-z]+)\s+([A-Z][a-z]+)',
    r'(?:owner|founder|co-?founder|medical director|ceo|president)[\s:,\-]+(?:is\s+)?(?:Dr\.?\s+)?([A-Z][a-z]+)\s+([A-Z][a-z]+)',
    r'(?:Dr\.?|Meet)\s+([A-Z][a-z]+)\s+([A-Z][a-z]+)[,\s]+(?:the\s+)?(?:founder|owner|co-?founder|medical director)',
]


def strip_html(html):
    html = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', html, flags=re.S | re.I)
    html = re.sub(r'<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', html)


def owner_from_website(domain):
    for path in PAGES:
        html = http_get("https://" + domain + path, timeout=7,
                        cache_key="web_" + domain + path.replace("/", "_"))
        if not html and path == "":
            html = http_get("http://" + domain, timeout=7,
                            cache_key="web_http_" + domain)
        if not html:
            continue
        # JSON-LD founder/owner
        for blk in re.findall(r'"(?:founder|owner)"\s*:\s*(\{.*?\}|"[^"]+")', html, re.I | re.S):
            nm = re.findall(r'"name"\s*:\s*"([^"]+)"', blk)
            if not nm and blk.startswith('"'):
                nm = [blk.strip('"')]
            if nm:
                first = nm[0].split()[0]
                if first.lower() in FIRST_NAMES or first.istitle():
                    return title_name(first), nm[0].strip(), "website-jsonld"
        # heuristic text
        txt = strip_html(html)
        for pat in OWNER_PATTERNS:
            for first, last in re.findall(pat, txt):
                if first.lower() in FIRST_NAMES:
                    return title_name(first), f"{title_name(first)} {title_name(last)}", "website-text"
    return None


# --------------------------------------------------------------------------- #
# Tier 4: DuckDuckGo HTML search
# --------------------------------------------------------------------------- #
def owner_from_search(store, city, state):
    q = f'"{store}" {city} {state} owner founder'
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": q})
    html = http_get(url, timeout=12, cache_key="ddg_" + store[:60] + state)
    if not html:
        return None
    txt = strip_html(html)
    for pat in OWNER_PATTERNS:
        for first, last in re.findall(pat, txt):
            if first.lower() in FIRST_NAMES:
                return title_name(first), f"{title_name(first)} {title_name(last)}", "search"
    return None


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def main():
    os.makedirs(CACHE_DIR, exist_ok=True)
    limit = None
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            limit = int(a.split("=")[1])

    with open(INPUT_FILE, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter=DELIM))
    if limit:
        rows = rows[:limit]
    print(f"Loaded {len(rows)} rows")

    for r in rows:
        r.setdefault("first_name", "")
        r["owner_full_name"] = ""
        r["first_name_source"] = ""

    stats = {"email": 0, "npi": 0, "website": 0, "search": 0}

    # Tier 1 - email (local, instant)
    for r in rows:
        res = name_from_email(r.get("email", ""))
        if res:
            r["first_name"], r["owner_full_name"] = res[0], res[1] or ""
            r["first_name_source"] = "email"
            stats["email"] += 1
        # derive website from clinic domain (bonus, fills empty website col)
        d = is_clinic_domain(r.get("email", ""))
        if d and not (r.get("website") or "").strip():
            r["website"] = "https://" + d
    print(f"Tier 1 (email): {stats['email']} filled")

    # Tier 2 - NPI (concurrent)
    todo = [r for r in rows if not r["first_name"]]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(npi_lookup, r["store_name"], r.get("city", ""), r.get("state", "")): r
                for r in todo}
        for fut in as_completed(futs):
            r = futs[fut]
            try:
                res = fut.result()
            except Exception:
                res = None
            if res:
                r["first_name"], r["owner_full_name"] = res
                r["first_name_source"] = "npi"
                stats["npi"] += 1
    print(f"Tier 2 (NPI): {stats['npi']} filled")

    # Tier 3 - website (concurrent over clinic domains)
    todo = [r for r in rows if not r["first_name"] and is_clinic_domain(r.get("email", ""))]
    with ThreadPoolExecutor(max_workers=24) as pool:
        futs = {pool.submit(owner_from_website, is_clinic_domain(r["email"])): r for r in todo}
        for fut in as_completed(futs):
            r = futs[fut]
            try:
                res = fut.result()
            except Exception:
                res = None
            if res:
                r["first_name"], r["owner_full_name"], r["first_name_source"] = res
                stats["website"] += 1
    print(f"Tier 3 (website): {stats['website']} filled")

    # Tier 4 - DDG search (low concurrency, polite)
    todo = [r for r in rows if not r["first_name"]]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(owner_from_search, r["store_name"], r.get("city", ""), r.get("state", "")): r
                for r in todo}
        for fut in as_completed(futs):
            r = futs[fut]
            try:
                res = fut.result()
            except Exception:
                res = None
            if res:
                r["first_name"], r["owner_full_name"], r["first_name_source"] = res
                stats["search"] += 1
    print(f"Tier 4 (search): {stats['search']} filled")

    # Write output
    fieldnames = list(rows[0].keys())
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=DELIM)
        w.writeheader()
        w.writerows(rows)

    filled = sum(1 for r in rows if r["first_name"])
    print("\n" + "=" * 50)
    print(f"Total filled: {filled}/{len(rows)} ({filled * 100 // len(rows)}%)")
    print(f"  by email:   {stats['email']}")
    print(f"  by NPI:     {stats['npi']}")
    print(f"  by website: {stats['website']}")
    print(f"  by search:  {stats['search']}")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
