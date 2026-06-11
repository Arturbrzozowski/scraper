#!/usr/bin/env python3
"""
Owner First-Name Finder for Alastin clinic leads — website-crawl-first.

Fills the `first_name` column (owner / founder / principal provider) for the
leads in "alastin 800 leads test names search.csv" using only FREE sources,
concurrently, so the full 838-row file finishes in minutes.

Strategy (website crawl is the primary engine, per results so far):

  Phase 1  WEBSITE CRAWL of every lead that has a website — taken from the
           `website` column, or derived from a clinic-domain email.
           The crawler fetches the homepage, discovers the site's real
           About/Team/Meet-the-doctor links from its navigation (rather than
           guessing fixed paths), and extracts owner candidates with
           context-scored patterns validated against a 5,200-name dictionary.

  Phase 2  WEBSITE DISCOVERY for leads with no website: Bing RSS search
           ("store name" city state), directory/social domains filtered out,
           candidate site validated by the lead's phone number or name+city
           appearing on the page — then crawled as in Phase 1.

  Phase 3  NPI registry fallback (free CMS API, authorized-official name).
  Phase 4  Email local-part fallback (dictionary-verified names only).

Every fill records provenance (`first_name_source`) and `owner_full_name`.
Rows that stay empty are honest misses. All responses cached under ./cache.
"""

import csv
import html as html_mod
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

INPUT_FILE = "alastin 800 leads test names search.csv"
OUTPUT_FILE = "alastin 800 leads test names search_with_first_names.csv"
NAMES_FILE = "first_names.json"
CACHE_DIR = "cache"

DELIM = ";"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

GENERIC_EMAIL = {
    "gmail.com", "yahoo.com", "hotmail.com", "aol.com", "outlook.com",
    "icloud.com", "msn.com", "comcast.net", "me.com", "live.com",
    "sbcglobal.net", "att.net", "mac.com", "protonmail.com", "ymail.com",
    "verizon.net", "cox.net", "bellsouth.net", "earthlink.net", "charter.net",
    "mail.com", "rocketmail.com", "aim.com", "gmx.com",
}
PLATFORM_EMAIL_SUBSTR = (
    "coupahost", "basware", "bill.com", "corpay", "avidbill", "yardi",
    "appfolio", "billtrust", "mineraltree", "stampli", "tipalti", "airbase",
    "ramp.com", "brex.com", "duly.com", "emburse", "concur",
)
# Never the clinic's own site (directories, socials, boards, aggregators)
DIRECTORY_DOMAINS = (
    "yelp.", "facebook.", "instagram.", "linkedin.", "twitter.", "x.com",
    "tiktok.", "youtube.", "pinterest.", "healthgrades.", "zocdoc.", "vagaro.",
    "groupon.", "yellowpages.", "mapquest.", "booksy.", "bbb.org", "doctor.",
    "webmd.", "vitals.", "realself.", "ratemds.", "wellness.com", "google.",
    "bing.", "yahoo.", "wikipedia.", "indeed.", "glassdoor.", "tripadvisor.",
    "foursquare.", "nextdoor.", "angi.", "thumbtack.", "porch.", "manta.",
    "chamberofcommerce.", "birdeye.", "podium.", "boulevard.", "joinblvd.",
    "squareup.", "square.site", "booker.", "mindbodyonline.", "styleseat.",
    "schedulicity.", "fresha.", "glossgenius.", "alastin.", "npino.",
    "npidb.", "npiprofile.", "hipaaspace.", "zoominfo.", "dnb.com", "buzzfile.",
    "yextpages.", "merchantcircle.", "citysearch.", "superpages.", "cylex.",
    "find-us-here.", "us-info.", "opencorporates.", "bizapedia.", "dandb.",
)

ROLE_PREFIXES = {
    "info", "contact", "hello", "support", "sales", "admin", "office",
    "invoices", "invoice", "billing", "accounts", "accounting",
    "accountspayable", "ap", "apinvoice", "apinvoices", "payables", "payable",
    "operations", "hr", "jobs", "careers", "marketing", "press", "media",
    "news", "help", "service", "customer", "customerservice", "enquiries",
    "inquiries", "general", "reception", "frontdesk", "front", "mail",
    "email", "team", "staff", "orders", "order", "booking", "bookings",
    "reservations", "appointments", "appointment", "appt", "noreply",
    "no-reply", "donotreply", "notifications", "alerts", "scheduling",
    "schedule", "feedback", "legal", "privacy", "security", "webmaster",
    "postmaster", "abuse", "spa", "clinic", "medical", "med", "health",
    "wellness", "care", "derm", "dermatology", "aesthetics", "aesthetic",
    "skincare", "skin", "beauty", "laser", "medspa", "rejuvenation",
    "frontoffice", "patientcare", "patients", "newpatient", "newpatients",
    "manager", "owner", "ceo", "cfo", "coo", "president", "founder",
}

# A surname must not be one of these (kills "Dr. Skin Care"-style matches)
SURNAME_BLOCKLIST = {
    "skin", "care", "skincare", "beauty", "aesthetics", "aesthetic", "medical",
    "med", "spa", "medspa", "health", "wellness", "laser", "center", "centre",
    "clinic", "dermatology", "derm", "institute", "boutique", "studio",
    "salon", "surgery", "plastic", "cosmetic", "facial", "body", "glow",
    "team", "staff", "group", "associates", "office", "services", "treatment",
    "treatments", "injector", "owner", "founder", "director", "today", "here",
    "and", "the", "our", "your", "with", "was", "has", "is", "who", "will",
    # function words / credentials that slip through as "surnames"
    "by", "of", "at", "in", "on", "to", "for", "from", "are", "you", "she",
    "he", "his", "her", "md", "do", "np", "pa", "rn", "llc", "inc",
}

SUFFIX_RE = re.compile(
    r'\b(L\.?L\.?C|INC|INCORPORATED|PC|P\.?A|PLLC|LTD|CORP(ORATION)?|CO|'
    r'COMPANY|GROUP|ASSOC(IATES)?|MD|D\.?O|PLC|DBA|ENTERPRISES|VENTURES|'
    r'HOLDINGS)\b\.?', re.I)
STOPWORDS = {"THE", "AND", "FOR", "OF", "AT", "BY", "A", "AN"}

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

FIRST_NAMES = set()
if os.path.exists(NAMES_FILE):
    FIRST_NAMES = {n.lower() for n in json.load(open(NAMES_FILE))}


# --------------------------------------------------------------------------- #
# HTTP with on-disk cache
# --------------------------------------------------------------------------- #
def cache_path(key):
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', key)[:150]
    return os.path.join(CACHE_DIR, safe)


def http_get(url, timeout=8, cache_key=None, max_bytes=900000):
    if cache_key:
        cp = cache_path(cache_key)
        if os.path.exists(cp):
            data = open(cp, encoding="utf-8", errors="ignore").read()
            return None if data == "\0MISS" else data
    text = None
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
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


def norm_org(s):
    s = re.sub(r'[^A-Za-z0-9 ]', ' ', s or '')
    s = SUFFIX_RE.sub(' ', s)
    return re.sub(r'\s+', ' ', s).strip().upper()


def strip_html(html):
    html = re.sub(r'<(script|style|noscript).*?</\1>', ' ', html, flags=re.S | re.I)
    html = re.sub(r'<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', html_mod.unescape(html))


# --------------------------------------------------------------------------- #
# Website crawl (primary engine)
# --------------------------------------------------------------------------- #
LINK_KEYWORDS = re.compile(
    r'about|team|staff|meet|provider|founder|owner|our-?story|story|bio|'
    r'doctor|physician|injector|who-we-are|dr-', re.I)
FALLBACK_PAGES = ["/about", "/about-us", "/our-team", "/team", "/meet-the-team"]

CRED = r'(?:MD|DO|NP|PA-?C|RN|BSN|FNP(?:-C|-BC)?|APRN|DNP|ARNP|CRNA|LE|LME|MSN)'

# (pattern, score) — each must capture (first, last)
CONTEXT_PATTERNS = [
    (re.compile(r'(?:founded|owned|established|started|opened|created)\s+(?:in\s+\d{4}\s+)?by\s+(?:Dr\.?\s+)?([A-Z][a-z]+)\s+(?:[A-Z]\.?\s+)?([A-Z][a-zA-Z\'-]+)'), 100),
    (re.compile(r'(?:owner|founder|co-?founder)\s*(?:and|&|,)?\s*(?:[a-z ]{0,20})?[:,\s\-–]+(?:Dr\.?\s+)?([A-Z][a-z]+)\s+(?:[A-Z]\.?\s+)?([A-Z][a-zA-Z\'-]+)'), 90),
    (re.compile(r'(?:Dr\.?\s+)?([A-Z][a-z]+)\s+(?:[A-Z]\.?\s+)?([A-Z][a-zA-Z\'-]+)\s*(?:,\s*' + CRED + r')?\s*(?:,|\s)\s*(?:is\s+)?(?:the\s+)?(?:owner|founder|co-?founder)'), 90),
    (re.compile(r'(?:medical\s+director)[:,\s\-–]+(?:Dr\.?\s+)?([A-Z][a-z]+)\s+(?:[A-Z]\.?\s+)?([A-Z][a-zA-Z\'-]+)'), 70),
    (re.compile(r'(?:Dr\.?\s+)?([A-Z][a-z]+)\s+(?:[A-Z]\.?\s+)?([A-Z][a-zA-Z\'-]+)\s*(?:,\s*' + CRED + r')?\s*(?:,|\s)\s*(?:is\s+)?(?:our|the)\s+medical\s+director'), 70),
    (re.compile(r'(?:Meet|About)\s+(?:Dr\.?\s+)?([A-Z][a-z]+)\s+(?:[A-Z]\.?\s+)?([A-Z][a-zA-Z\'-]+)'), 55),
    (re.compile(r'Dr\.?\s+([A-Z][a-z]+)\s+(?:[A-Z]\.?\s+)?([A-Z][a-zA-Z\'-]+)'), 35),
    (re.compile(r'([A-Z][a-z]+)\s+(?:[A-Z]\.?\s+)?([A-Z][a-zA-Z\'-]+)\s*,\s*' + CRED + r'\b'), 35),
]


def valid_person(first, last):
    f, l = first.lower(), last.lower()
    if f not in FIRST_NAMES:
        return False
    if l in SURNAME_BLOCKLIST or l in FIRST_NAMES and l == f:
        return False
    if not (2 <= len(last) <= 24):
        return False
    return True


def extract_candidates(html, page_weight=1.0):
    """Yield (score, first, full_name) candidates from one page's HTML."""
    out = []
    # JSON-LD founder/owner
    for blk in re.findall(r'"(?:founder|owner)s?"\s*:\s*(\{.*?\}|\[.*?\]|"[^"]+")',
                          html, re.I | re.S):
        nms = re.findall(r'"name"\s*:\s*"([^"]+)"', blk)
        if not nms and blk.startswith('"'):
            nms = [blk.strip('"')]
        for nm in nms:
            full = re.sub(r'^(dr|mr|mrs|ms|miss|prof)\.?\s+', '', nm.strip(), flags=re.I)
            parts = full.split()
            if len(parts) >= 2 and valid_person(parts[0], parts[-1]):
                out.append((95 * page_weight, title_name(parts[0]), full))
    txt = strip_html(html)
    for pat, score in CONTEXT_PATTERNS:
        for first, last in pat.findall(txt):
            if valid_person(first, last):
                out.append((score * page_weight,
                            title_name(first),
                            f"{title_name(first)} {title_name(last)}"))
    return out


def site_pages(domain_or_url):
    """Fetch homepage, discover nav links to about/team pages. Returns
    list of (url, html). Cheap: at most ~7 fetches per site."""
    if domain_or_url.startswith("http"):
        base = domain_or_url.rstrip("/")
        domain = urllib.parse.urlparse(base).netloc
    else:
        domain = domain_or_url
        base = "https://" + domain
    pages = []
    home = None
    for attempt in (base, f"https://www.{domain}", f"http://{domain}"):
        home = http_get(attempt, timeout=8,
                        cache_key="web_" + re.sub(r'https?://', '', attempt))
        if home:
            base = attempt
            break
    if not home:
        return pages
    pages.append((base, home))
    # discover internal links that look like about/team pages
    seen, targets = set(), []
    for href, text in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.{0,80}?)</a>',
                                 home, re.I | re.S):
        if not (LINK_KEYWORDS.search(href) or LINK_KEYWORDS.search(strip_html(text))):
            continue
        url = urllib.parse.urljoin(base + "/", href)
        p = urllib.parse.urlparse(url)
        if p.netloc.replace("www.", "") != domain.replace("www.", ""):
            continue
        url = p.scheme + "://" + p.netloc + p.path
        if url not in seen and not url.lower().endswith((".pdf", ".jpg", ".png")):
            seen.add(url)
            targets.append(url)
    if not targets:
        targets = [base + p for p in FALLBACK_PAGES]
    for url in targets[:6]:
        h = http_get(url, timeout=8, cache_key="web_" + re.sub(r'https?://', '', url))
        if h:
            pages.append((url, h))
    return pages


def owner_from_website(domain_or_url):
    """Crawl one site; return (first, full, source_url) or None."""
    cands = []
    for url, html in site_pages(domain_or_url):
        weight = 1.0 if url.rstrip("/").count("/") > 2 else 0.9  # subpages slightly preferred
        for score, first, full in extract_candidates(html, weight):
            cands.append((score, first, full, url))
    if not cands:
        return None
    # combine: best score + frequency bonus across the site
    freq = Counter(c[1] for c in cands)
    best = max(cands, key=lambda c: c[0] + 6 * freq[c[1]])
    if best[0] < 35:
        return None
    return best[1], best[2], best[3]


# --------------------------------------------------------------------------- #
# Website discovery via domain guessing (for rows with no site)
#
# Search engines (Bing/DDG/Qwant) block or mangle automated queries from this
# environment, so instead we generate likely domains from the business name
# (e.g. "Mon Amie Aesthetics LLC" -> monamieaesthetics.com) and accept one only
# if the page proves it belongs to the lead: its phone number appears on the
# homepage, or the business name + city do.
# --------------------------------------------------------------------------- #
def guess_domains(store):
    base = re.sub(r'[^a-z0-9& ]', '', (store or '').lower())
    base = re.sub(r'\b(llc|inc|pc|pa|pllc|ltd|corp|co|dba|the)\b', ' ', base)
    base = base.replace('&', ' and ')
    words = base.split()
    if not words:
        return []
    cands = []
    joined = ''.join(words)
    hyphen = '-'.join(words)
    cands.append(joined + '.com')
    if len(words) > 2:
        cands.append(''.join(words[:3]) + '.com')
        cands.append(''.join(words[:2]) + '.com')
    elif len(words) == 2:
        cands.append(''.join(words[:1]) + words[1] + '.com')
    if 1 < len(words) <= 4:
        cands.append(hyphen + '.com')
    # drop the word "and" variants too
    nowords = [w for w in words if w != 'and']
    if nowords != words:
        cands.append(''.join(nowords) + '.com')
    out, seen = [], set()
    for c in cands:
        if 5 <= len(c) <= 40 and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:5]


def page_matches_lead(html, store, city, phone):
    txt = strip_html(html).lower()
    digits = re.sub(r'\D', '', phone or '')[-10:]
    if digits and digits in re.sub(r'\D', '', txt):
        return True
    store_tokens = {t.lower() for t in norm_org(store).split()
                    if len(t) > 3 and t not in STOPWORDS}
    name_hits = sum(1 for t in store_tokens if t in txt)
    return (store_tokens and name_hits >= max(1, len(store_tokens) // 2)
            and (city or "").lower() in txt)


def discover_website(store, city, state, phone):
    for domain in guess_domains(store):
        home = http_get("https://" + domain, timeout=7, cache_key="web_" + domain)
        if not home:
            continue
        if page_matches_lead(home, store, city, phone):
            return "https://" + domain
    return None


# --------------------------------------------------------------------------- #
# NPI fallback
# --------------------------------------------------------------------------- #
def npi_lookup(store, city, state):
    nstore = norm_org(store)
    tokens = [t for t in nstore.split() if len(t) > 2 and t not in STOPWORDS]
    if not tokens:
        return None
    query = " ".join(tokens[:2]) + "*"
    params = {"version": "2.1", "limit": "20",
              "organization_name": query, "state": state}
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
        city_ok = any((a.get("city", "").strip().upper() ==
                       (city or "").strip().upper())
                      for a in res.get("addresses", []))
        if overlap >= 2 or (overlap >= 1 and (city_ok or nstore[:6] == on[:6])):
            fn = b.get("authorized_official_first_name")
            ln = b.get("authorized_official_last_name")
            if fn:
                full = " ".join(p for p in [title_name(fn), title_name(ln or "")] if p)
                return title_name(fn), full
    return None


# --------------------------------------------------------------------------- #
# Email fallback
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
    best = None
    for n in FIRST_NAMES:
        if len(n) >= 4 and token.startswith(n):
            if best is None or len(n) > len(best):
                best = n
    return best


def name_from_email(email):
    email = (email or "").strip().lower()
    if "@" not in email:
        return None
    local = re.sub(r'\+.*$', '', email.split("@", 1)[0])
    if local in ROLE_PREFIXES:
        return None
    for sep in (".", "_", "-"):
        if sep in local:
            first = local.split(sep)[0]
            if first in ROLE_PREFIXES:
                return None
            if first in FIRST_NAMES:
                return title_name(first), None
            pref = known_prefix(first)
            if pref:
                return title_name(pref), None
            return None
    if local in FIRST_NAMES:
        return title_name(local), None
    return None


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_pool(items, fn, workers, on_result):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fn, *args): r for r, args in items}
        done = 0
        for fut in as_completed(futs):
            r = futs[fut]
            try:
                res = fut.result()
            except Exception:
                res = None
            on_result(r, res)
            done += 1
            if done % 100 == 0:
                print(f"    ...{done}/{len(items)}")


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
        r["first_name"] = ""
        r["owner_full_name"] = ""
        r["first_name_source"] = ""
        site = (r.get("website") or "").strip()
        if not site:
            d = is_clinic_domain(r.get("email", ""))
            if d:
                site = "https://" + d
        r["website"] = site

    stats = Counter()

    # ---- Phase 1: crawl rows that already have a website -------------------
    have_site = [r for r in rows if r["website"]]
    print(f"\nPhase 1: website crawl ({len(have_site)} rows with a site)")

    def apply_site(r, res):
        if res and not r["first_name"]:
            r["first_name"], r["owner_full_name"], src = res
            r["first_name_source"] = "website"
            stats["website"] += 1

    run_pool([(r, (r["website"],)) for r in have_site],
             owner_from_website, 24, apply_site)
    print(f"  filled: {stats['website']}")

    # ---- Phase 2: discover sites for the rest, then crawl ------------------
    no_site = [r for r in rows if not r["website"]]
    print(f"\nPhase 2: website discovery via domain guessing ({len(no_site)} rows)")
    found = []

    def apply_discovery(r, res):
        if res:
            r["website"] = res
            found.append(r)

    run_pool([(r, (r["store_name"], r.get("city", ""), r.get("state", ""),
                   r.get("phone_number", ""))) for r in no_site],
             discover_website, 6, apply_discovery)
    print(f"  websites discovered: {len(found)}; crawling them...")

    before = stats["website"]
    run_pool([(r, (r["website"],)) for r in found],
             owner_from_website, 24, apply_site)
    stats["website-discovered"] = stats["website"] - before
    print(f"  filled from discovered sites: {stats['website-discovered']}")

    # ---- Phase 3: NPI fallback ---------------------------------------------
    todo = [r for r in rows if not r["first_name"]]
    print(f"\nPhase 3: NPI fallback ({len(todo)} rows)")

    def apply_npi(r, res):
        if res and not r["first_name"]:
            r["first_name"], r["owner_full_name"] = res
            r["first_name_source"] = "npi"
            stats["npi"] += 1

    run_pool([(r, (r["store_name"], r.get("city", ""), r.get("state", "")))
              for r in todo], npi_lookup, 6, apply_npi)
    print(f"  filled: {stats['npi']}")

    # ---- Phase 4: email fallback -------------------------------------------
    for r in rows:
        if r["first_name"]:
            continue
        res = name_from_email(r.get("email", ""))
        if res:
            r["first_name"], r["owner_full_name"] = res[0], res[1] or ""
            r["first_name_source"] = "email"
            stats["email"] += 1
    print(f"\nPhase 4: email fallback filled: {stats['email']}")

    # ---- Write --------------------------------------------------------------
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=DELIM)
        w.writeheader()
        w.writerows(rows)

    filled = sum(1 for r in rows if r["first_name"])
    print("\n" + "=" * 50)
    print(f"Total filled: {filled}/{len(rows)} ({filled * 100 // len(rows)}%)")
    for k in ("website", "website-discovered", "npi", "email"):
        print(f"  {k:20} {stats.get(k, 0)}")
    print(f"  (website total includes {stats.get('website-discovered', 0)} from discovered sites)")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
