#!/usr/bin/env python3
"""
Zoe's Jobs Scraper.

  python tracker.py scrape      — visit every portal, save snapshot, update dashboard
  python tracker.py display     — print new jobs to terminal
  python tracker.py dashboard   — regenerate dashboard.html without scraping
"""

import json
import random
import re
import sys
from datetime import datetime, date as _date, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

SNAPSHOTS_DIR  = Path("snapshots")
PORTALS_FILE   = Path("jobs_portals_list.txt")
DASHBOARD_FILE = Path("dashboard.html")

_CTL_PREFIX = "Climate Tech List"

# Tried in order; first selector that yields >= 1 result wins.
SELECTORS = [
    # Workday
    "[data-automation-id='jobTitle']",
    # Greenhouse.io
    ".opening a",
    # Lever
    "h5.posting-name",
    ".posting-title h5",
    # iCIMS
    ".iCIMS_JobTitle a",
    ".iCIMS_JobTitle",
    # BambooHR
    ".BambooHR-ATS-board-item-title",
    "a.job-listing-title",
    # Breezy HR
    ".position h2",
    "h2.position-title",
    # SmartRecruiters
    ".jobTitle",
    # SAP SuccessFactors
    ".jobResultItem .jobTitle a",
    ".sfdc-jobtitle",
    # Taleo
    ".oracleATSResultsTable td a",
    "table.reqListTable td a",
    # Njoyn
    "td.col-title a",
    "td.jobtitle a",
    # Workable
    "li.job-list-item h2",
    "li.job-list-item a",
    # JobVite
    ".jv-job-list-name",
    # Generic class-name patterns
    "[class*='job-title']",
    "[class*='job_title']",
    "[class*='jobtitle']",
    "[class*='posting-title']",
    "[class*='position-title']",
    "[class*='role-title']",
    "[class*='vacancy-title']",
    "[class*='career-title']",
    "[class*='opening-title']",
    "[class*='requisition-title']",
    # Scoped list headings
    "li h3",
    "li h4",
]

_SKIP_PREFIXES = (
    "showing ",
    "filter results",
    "search results",
    "no jobs",
    "no positions",
    "no openings",
    "candidate menu",
    "set a job alert",
    "let's keep in touch",
    "lets keep in touch",
    "register your interest",
    "join our talent",
    "create a job alert",
)

_SKIP_EXACT = {"title", "location", "date", "department", "company", "category", "type", "how to apply"}

_LOC_LABEL_RE = re.compile(r"^(locations?|city|region|area|office|site)\s+", re.I)

MIN_LEN = 4
MAX_LEN = 120

# ── Canada filtering ──────────────────────────────────────────────────────────

_CA_PROVINCES = (
    "ON", "BC", "AB", "QC", "MB", "SK", "NS", "NB", "NL", "PE", "NT", "NU", "YT",
)

_CA_CITIES = frozenset([
    "toronto", "vancouver", "calgary", "edmonton", "ottawa", "montreal", "montréal",
    "winnipeg", "québec city", "quebec city", "halifax", "saskatoon", "regina",
    "victoria", "kelowna", "burnaby", "surrey", "mississauga", "brampton", "markham",
    "waterloo", "kitchener", "hamilton", "london", "windsor", "sudbury",
    "thunder bay", "moncton", "fredericton", "charlottetown", "st. john's", "saint john",
    "whitehorse", "yellowknife", "iqaluit", "richmond", "richmond hill",
    "oakville", "burlington", "oshawa", "barrie", "kingston", "guelph",
    "st. catharines", "niagara falls", "lethbridge", "red deer", "medicine hat",
    "kamloops", "nanaimo", "abbotsford", "coquitlam", "langley", "delta",
    "new westminster", "north vancouver", "west vancouver",
    "laval", "longueuil", "gatineau", "trois-rivières", "sherbrooke",
    "saguenay", "lévis", "terrebonne", "repentigny",
    "tiverton", "chalk river", "deep river", "pickering", "ajax", "whitby",
    "north bay", "sault ste. marie", "vaughan", "aurora", "newmarket",
    "greater toronto", "greater toronto area", "gta", "lower mainland",
    "scarborough", "etobicoke", "north york", "downtown toronto",
    "cambridge", "waterloo region", "kitchener-waterloo",
])


def _is_canada(loc: str | None) -> bool:
    """True if location is Canadian or unknown (None = can't tell, keep it)."""
    if not loc:
        return True
    stripped = loc.strip()
    # "2 Locations" / "3 Locations" etc. are JobVite multi-location badges —
    # we can't determine the countries, so keep the job rather than lose it.
    if re.match(r'^\d+\s+[Ll]ocations?$', stripped):
        return True
    up = stripped.upper()
    if "CANADA" in up:
        return True
    for prov in _CA_PROVINCES:
        if re.search(r"(?<![A-Z])" + prov + r"(?![A-Z])", up):
            return True
    lo = stripped.lower()
    for city in _CA_CITIES:
        if city in lo:
            return True
    return False


# ── JS extractors ─────────────────────────────────────────────────────────────

_EXTRACT_JS = """
(elements) => {
    const LOC_SELS = [
        '[data-automation-id="primaryLocation"]',
        '[data-automation-id="locations"]',
        '.location',
        '.sort-by-location',
        '.posting-categories .sort-by-location',
        '[class*="location"i]',
        '[class*="city"i]',
        '[class*="region"i]',
        '.job-location',
        '.jobLocation',
        'span[class*="Location"]'
    ];

    function getUrl(el) {
        if (el.tagName === 'A' && el.href) return el.href;
        const inner = el.querySelector('a[href]');
        if (inner) return inner.href;
        for (let p = el.parentElement, i = 0; p && i < 6; p = p.parentElement, i++)
            if (p.tagName === 'A' && p.href) return p.href;
        return null;
    }

    function getLocation(el) {
        for (let c = el.parentElement, level = 0; c && level < 6; c = c.parentElement, level++) {
            for (const sel of LOC_SELS) {
                try {
                    const loc = c.querySelector(sel);
                    if (loc && !el.contains(loc)) {
                        const t = (loc.innerText || '').replace(/\\s+/g, ' ').trim();
                        if (t.length >= 2 && t.length < 80) return t;
                    }
                } catch (e) {}
            }
        }
        return null;
    }

    function getTitle(el) {
        const h = el.querySelector('h1,h2,h3,h4,h5,h6');
        return ((h || el).innerText || '').replace(/\\s+/g, ' ').trim();
    }

    return elements.map(el => ({
        title: getTitle(el),
        url:   getUrl(el),
        loc:   getLocation(el)
    }));
}
"""

# JS to extract jobs + company names from Climate Tech List aggregator pages.
# climatetechlist.com renders job cards as React components; we try several
# class-name patterns and fall back to generic card detection.
_CTL_EXTRACT_JS = """
() => {
    const cardSelectors = [
        '[class*="JobCard"]', '[class*="job-card"]', '[class*="jobCard"]',
        '[class*="job-item"]', '[class*="jobItem"]', '[class*="listing-item"]',
        'article[class*="job"]', 'li[class*="job"]',
        '[data-testid*="job"]', '[class*="position-card"]',
        'table tbody tr',
    ];

    let cards = [];
    for (const sel of cardSelectors) {
        try {
            const found = document.querySelectorAll(sel);
            if (found.length > 0) { cards = Array.from(found); break; }
        } catch (e) {}
    }

    const results = [];
    for (const card of cards) {
        const titleEl = card.querySelector(
            'h2, h3, h4, [class*="title"i]:not([class*="company"i]), [class*="role"i], [class*="position"i]'
        );
        const title = titleEl ? (titleEl.innerText || '').replace(/\\s+/g, ' ').trim() : '';

        const compEl = card.querySelector(
            '[class*="company"i], [class*="employer"i], [class*="org"i]'
        );
        const company = compEl ? (compEl.innerText || '').replace(/\\s+/g, ' ').trim() : '';

        const linkEl = card.querySelector('a[href]') || (card.tagName === 'A' ? card : null);
        const url = linkEl ? linkEl.href : null;

        const locEl = card.querySelector('[class*="location"i], [class*="city"i], [class*="place"i]');
        const loc = locEl ? (locEl.innerText || '').replace(/\\s+/g, ' ').trim() : '';

        if (title.length >= 4 && company.length >= 2) {
            results.push({ title, company, url, location: loc || null });
        }
    }
    return results;
}
"""


# ── snapshot helpers ──────────────────────────────────────────────────────────

def _snap_date(p: Path) -> str:
    return p.stem[:10]


def _snap_dt(p: Path) -> datetime:
    stem = p.stem
    suffix = stem[11:] if len(stem) > 10 and stem[10] == "_" else ""
    if suffix.isdigit() and len(suffix) == 4:
        return datetime.strptime(stem, "%Y-%m-%d_%H%M")
    return datetime.strptime(stem[:10], "%Y-%m-%d")


def _all_snapshots() -> list[Path]:
    return sorted(SNAPSHOTS_DIR.glob("[0-9]*.json"), key=_snap_dt)


# ── job normalisation helpers ─────────────────────────────────────────────────

def _job_title(job) -> str:
    return job if isinstance(job, str) else job.get("title", "")


def _job_key(job) -> str:
    return _job_title(job).lower().strip()


def _to_dict(job) -> dict:
    if isinstance(job, str):
        return {"title": job, "url": None, "location": None}
    return {"title": job.get("title", ""),
            "url":   job.get("url"),
            "location": job.get("location")}


# ── text / job extraction ─────────────────────────────────────────────────────

def _clean(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()


def load_portals():
    entries = []
    for raw in PORTALS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Support tab-separated (this project) and pipe-separated (legacy)
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t")]
        else:
            parts = [p.strip() for p in line.split("|")]
        name       = parts[0]
        url        = parts[1] if len(parts) > 1 else parts[0]
        sel        = parts[2] if len(parts) > 2 else None
        loc_filter = parts[3] if len(parts) > 3 else None
        entries.append((name, url, sel, loc_filter))
    return entries


def _loc_matches(loc: str | None, pattern: str) -> bool:
    if not loc:
        return False
    up = loc.upper()
    pat = pattern.upper()
    return f", {pat}," in up or f", {pat} " in up or pat in up.split(",")[0].split()


def _extract_from_selector(page, selector: str) -> list[dict]:
    try:
        raw = page.eval_on_selector_all(selector, _EXTRACT_JS)
    except Exception:
        return []

    results = []
    seen: set[str] = set()
    for item in raw:
        title = _clean(item.get("title", ""))
        if not title or not (MIN_LEN <= len(title) <= MAX_LEN):
            continue
        if any(title.lower().startswith(p) for p in _SKIP_PREFIXES):
            continue
        if title.lower() in _SKIP_EXACT:
            continue

        url = item.get("url")
        if url and (url.startswith("about:") or url.startswith("javascript:")):
            url = None

        loc = item.get("loc")
        if loc:
            loc = _LOC_LABEL_RE.sub("", _clean(loc)).strip()
            if not loc or len(loc) > 60:
                loc = None
            # Strip GE Vernova-style "+N More Locations" UI badges
            elif re.match(r'^\+\d+\s*[Mm]ore\s+[Ll]ocations?', loc):
                loc = None

        # Prefer URL as dedup key so two jobs with identical titles but
        # different postings (e.g. one US, one Canada) are both kept.
        key = url if url else _job_key({"title": title})
        if key not in seen:
            seen.add(key)
            results.append({"title": title, "url": url, "location": loc})

    return results


def _exhaust_show_more(page) -> int:
    """Click 'show more / load more' style buttons until none remain. Returns click count."""
    patterns = [
        re.compile(r"show\s+more", re.I),
        re.compile(r"load\s+more", re.I),
        re.compile(r"see\s+more\s+jobs?", re.I),
        re.compile(r"view\s+more\s+jobs?", re.I),
        re.compile(r"more\s+jobs", re.I),
        re.compile(r"more\s+results", re.I),
        re.compile(r"show\s+all\s+jobs?", re.I),
    ]
    clicks = 0
    for _ in range(30):
        clicked = False
        for pat in patterns:
            for role in ("button", "link"):
                try:
                    loc = page.get_by_role(role, name=pat)
                    if loc.count() > 0:
                        first = loc.first
                        if first.is_visible(timeout=500):
                            first.scroll_into_view_if_needed()
                            first.click()
                            page.wait_for_timeout(2_500)
                            clicks += 1
                            clicked = True
                            break
                except Exception:
                    pass
            if clicked:
                break
        if not clicked:
            break
    return clicks


def _dismiss_cookie_banners(page) -> None:
    """Try common cookie consent selectors and click accept if visible."""
    for sel in [
        "button.cky-btn-accept",
        "button[data-cky-tag='accept-button']",
        "a#zc-manage",
        "a.cookiesButtonAccept",
        "a.cookiesButton.cookiesButtonAccept",
        ".cc-btn.cc-accept-all",
        "button.accept-all",
        "button#onetrust-accept-btn-handler",
        "[aria-label='Accept All']",
        "[aria-label='Accept all cookies']",
        "[aria-label='Accept cookies']",
        # WorkWolf (CookieConsent library)
        "button:has-text('Allow all cookies')",
        "[data-cc='accept-all']",
    ]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=600):
                loc.click()
                page.wait_for_timeout(1_200)
                return
        except Exception:
            pass


# JS extractor for the new-style Greenhouse job board (job-boards.greenhouse.io).
# Each row is <tr class="job-post"> containing <td class="cell"><a>Title\nLocation</a></td>.
# We split on the first newline to separate title from location.
_GH_BOARD_EXTRACT_JS = """
() => {
    const rows = document.querySelectorAll('tr.job-post');
    const results = [];
    const seen = new Set();
    for (const row of rows) {
        const a = row.querySelector('a[href]');
        if (!a) continue;
        const url = a.href;

        // Try child elements first (title in first child, location in last child)
        const children = Array.from(a.children).filter(c => (c.innerText||'').trim());
        let title, location;
        if (children.length >= 2) {
            title    = (children[0].innerText || '').replace(/\\s+/g,' ').trim();
            location = (children[children.length-1].innerText || '').replace(/\\s+/g,' ').trim();
        } else {
            // Fall back: split on newline in textContent
            const lines = (a.textContent || '')
                .split('\\n')
                .map(s => s.replace(/\\s+/g,' ').trim())
                .filter(s => s.length > 0);
            title    = lines[0] || '';
            location = lines.length > 1 ? lines[lines.length - 1] : null;
        }

        if (!title || title.length < 4 || title.length > 120) continue;
        const key = title.toLowerCase().trim();
        if (seen.has(key)) continue;
        seen.add(key);
        results.push({ title, url, location: location || null });
    }
    return results;
}
"""


def _extract_gh_board_jobs(page) -> list[dict]:
    """Extract jobs from a new-style Greenhouse board (job-boards.greenhouse.io)."""
    try:
        raw = page.evaluate(_GH_BOARD_EXTRACT_JS)
    except Exception:
        return []

    # Regex to strip "New" / "New!" badge text that some Greenhouse boards append to titles
    _badge_re = re.compile(r"\s*\bNew!?\s*$", re.I)

    results = []
    seen: set[str] = set()
    for item in raw:
        title = _clean(item.get("title", ""))
        title = _badge_re.sub("", title).strip()
        if not title or not (MIN_LEN <= len(title) <= MAX_LEN):
            continue
        if any(title.lower().startswith(p) for p in _SKIP_PREFIXES):
            continue
        if title.lower() in _SKIP_EXACT:
            continue

        url = item.get("url")
        if url and (url.startswith("about:") or url.startswith("javascript:")):
            url = None

        loc = item.get("location")
        if loc:
            loc = _clean(loc)
            if not loc or len(loc) > 80:
                loc = None

        key = title.lower().strip()
        if key not in seen:
            seen.add(key)
            results.append({"title": title, "url": url, "location": loc})

    return results


# WorkWolf embed extractor.
# The outer clickable card is a Tailwind hover:cursor-pointer div with 2 children
# (title-block and metadata-block). The title-block itself is a div whose first child
# is the plain job title and whose second child is "Company | City, Province, Country".
# We scan all divs for this inner pattern: ch[0]=plain title, ch[1]="Company | Location".
_WORKWOLF_EXTRACT_JS = """
() => {
    const results = [];
    const seen = new Set();

    for (const div of document.querySelectorAll('div')) {
        const ch = div.children;
        if (ch.length < 2 || ch.length > 6) continue;
        const title = (ch[0].innerText || '').replace(/\\s+/g, ' ').trim();
        const meta  = (ch[1].innerText || '').replace(/\\s+/g, ' ').trim();
        // Title must be a clean job name (no pipe, reasonable length)
        if (!title || title.length < 4 || title.length > 120) continue;
        if (title.includes('|')) continue;
        // Meta must be "Company | Location"
        if (!meta.includes('|')) continue;
        // Ignore filter/header rows (meta that looks like a dropdown label)
        if (/^All\b/i.test(meta) || meta.length < 5) continue;
        const parts = meta.split('|');
        const location = parts.length > 1 ? parts[parts.length - 1].trim() : null;
        const key = title.toLowerCase();
        if (!seen.has(key)) {
            seen.add(key);
            results.push({ title, location: location || null, url: null });
        }
    }
    return results;
}
"""


def _extract_workwolf_jobs(page, url: str) -> list[dict]:
    """Extract jobs from a WorkWolf embed page."""
    try:
        page.goto(url, wait_until="load", timeout=60_000)
    except Exception:
        pass

    _dismiss_cookie_banners(page)
    page.wait_for_timeout(4_000)

    # Scroll to trigger lazy-loading of the full job list
    for _ in range(5):
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(800)
    page.wait_for_timeout(1_000)

    _exhaust_show_more(page)

    try:
        raw = page.evaluate(_WORKWOLF_EXTRACT_JS)
    except Exception:
        raw = []

    results = []
    seen: set[str] = set()
    for item in raw:
        title = _clean(item.get("title", ""))
        if not title or not (MIN_LEN <= len(title) <= MAX_LEN):
            continue
        if any(title.lower().startswith(p) for p in _SKIP_PREFIXES):
            continue
        if title.lower() in _SKIP_EXACT:
            continue

        loc = item.get("location")
        if loc:
            loc = _clean(loc)
            if not loc or len(loc) > 80:
                loc = None

        key = title.lower().strip()
        if key not in seen:
            seen.add(key)
            results.append({"title": title, "url": None, "location": loc})

    return results


def extract_jobs(page, url: str, custom_selector=None) -> list[dict]:
    """Navigate to url, exhaust show-more buttons, paginate through all pages, return all jobs."""
    # WorkWolf embed: dedicated extractor handles cookie consent and lazy loading
    if "app.workwolf.com/embed" in url:
        return _extract_workwolf_jobs(page, url)

    try:
        page.goto(url, wait_until="load", timeout=60_000)
    except Exception:
        pass

    # Dismiss cookie banners before waiting for content
    _dismiss_cookie_banners(page)

    # New-style Greenhouse board: use dedicated extractor that splits title+location
    if "job-boards.greenhouse.io" in url and custom_selector == "tr.job-post a":
        try:
            page.wait_for_selector("tr.job-post", timeout=30_000)
        except Exception:
            page.wait_for_timeout(5_000)
        _exhaust_show_more(page)
        return _extract_gh_board_jobs(page)

    selectors_to_try = [custom_selector] if custom_selector else SELECTORS
    combined = ", ".join([custom_selector] if custom_selector else SELECTORS[:25])
    try:
        page.wait_for_selector(combined, timeout=60_000)
    except Exception:
        page.wait_for_timeout(6_000)

    all_jobs: list[dict] = []
    seen_keys: set[str] = set()

    def _collect() -> int:
        for sel in selectors_to_try:
            results = _extract_from_selector(page, sel)
            if results:
                added = 0
                for j in results:
                    # Prefer URL as key so same-titled jobs with different URLs
                    # (different postings) are both captured.
                    k = j.get("url") or _job_key(j)
                    if k not in seen_keys:
                        seen_keys.add(k)
                        all_jobs.append(j)
                        added += 1
                return added
        return 0

    # Click through all show-more / load-more buttons first
    _exhaust_show_more(page)
    _collect()

    # Then walk pagination (Next page links)
    for _ in range(25):
        next_found = False
        for next_sel in [
            "a[rel='next']",
            "a[aria-label='Next']",
            "a[aria-label='Next page']",
            "[aria-label='Next page']",
            ".pagination a.next",
            ".pagination__next a",
            "li.next a",
            "li.pager__item--next a",
            "button[aria-label='Next page']",
            ".next a",
        ]:
            try:
                loc = page.locator(next_sel).first
                if loc.is_visible(timeout=500):
                    cls = loc.get_attribute("class") or ""
                    if ("disabled" not in cls
                            and loc.get_attribute("aria-disabled") != "true"
                            and loc.get_attribute("disabled") is None):
                        loc.click()
                        page.wait_for_load_state("load", timeout=30_000)
                        page.wait_for_timeout(2_000)
                        _exhaust_show_more(page)
                        _collect()
                        next_found = True
                        break
            except Exception:
                continue
        if not next_found:
            break

    return all_jobs


def _extract_ctl_jobs(page, url: str) -> list[dict]:
    """Extract jobs + company names from a Climate Tech List aggregator page."""
    try:
        page.goto(url, wait_until="load", timeout=60_000)
    except Exception:
        pass

    # CTL pages are heavy React SPAs; give them extra time to render
    page.wait_for_timeout(6_000)
    _exhaust_show_more(page)

    try:
        results = page.evaluate(_CTL_EXTRACT_JS)
    except Exception:
        results = []

    cleaned = []
    seen: set[str] = set()
    for item in results:
        title   = _clean(item.get("title", ""))
        company = _clean(item.get("company", ""))
        if not title or not (MIN_LEN <= len(title) <= MAX_LEN):
            continue
        if any(title.lower().startswith(p) for p in _SKIP_PREFIXES):
            continue
        if title.lower() in _SKIP_EXACT:
            continue

        url_val = item.get("url")
        if url_val and (url_val.startswith("about:") or url_val.startswith("javascript:")):
            url_val = None

        loc = item.get("location")
        if loc:
            loc = _clean(loc)
            if not loc or len(loc) > 80:
                loc = None

        key = f"{company.lower()}|{title.lower()}"
        if key not in seen:
            seen.add(key)
            cleaned.append({"title": title, "company": company, "url": url_val, "location": loc})

    return cleaned


# ── diff logic ────────────────────────────────────────────────────────────────

def _daily_new() -> list[tuple[str, dict[str, list[dict]]]]:
    snaps = _all_snapshots()
    if len(snaps) < 2:
        return []

    result = []
    for i in range(len(snaps) - 1, 0, -1):
        cur  = json.loads(snaps[i].read_text(encoding="utf-8"))
        prev = json.loads(snaps[i - 1].read_text(encoding="utf-8"))

        new: dict[str, list[dict]] = {}
        for company, jobs in cur.items():
            prev_keys = {_job_key(j) for j in prev.get(company, [])}
            added = [_to_dict(j) for j in jobs if _job_key(j) not in prev_keys]
            if added:
                new[company] = added

        if new:
            result.append((_snap_date(snaps[i]), new))

    return result


def _scrape_regressions() -> list[str]:
    snaps = _all_snapshots()
    if len(snaps) < 2:
        return []
    latest = json.loads(snaps[-1].read_text(encoding="utf-8"))
    prev   = json.loads(snaps[-2].read_text(encoding="utf-8"))
    return sorted(
        company
        for company, jobs in latest.items()
        if len(jobs) == 0 and len(prev.get(company, [])) > 0
    )


def _zero_result_portals() -> list[tuple[str, str]]:
    snaps = _all_snapshots()
    if not snaps:
        return []
    latest = json.loads(snaps[-1].read_text(encoding="utf-8"))
    portal_urls = {name: url for name, url, *_ in load_portals()}
    return sorted(
        (company, portal_urls.get(company, "#"))
        for company, jobs in latest.items()
        if len(jobs) == 0
    )


def _write_snapshot_index() -> None:
    """Writes snapshots/index.json consumed by the browser-side dashboard."""
    snaps = _all_snapshots()
    seen_names: set[str] = set()
    portals: list[dict] = []
    for name, url, *_ in load_portals():
        if name.startswith(_CTL_PREFIX):
            continue  # aggregators are not shown as tracked portals
        if name not in seen_names:
            seen_names.add(name)
            portals.append({"name": name, "url": url})
    (SNAPSHOTS_DIR / "index.json").write_text(
        json.dumps({"snapshots": [p.name for p in snaps], "portals": portals},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── dashboard HTML (embedded / offline version) ───────────────────────────────

def _esc(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


_CSS = """
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
      background: #eef2f7;
      color: #1e293b;
      line-height: 1.55;
      min-height: 100vh;
    }

    .header {
      background: #0f2044;
      color: #fff;
      padding: 16px 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 10;
      box-shadow: 0 2px 10px rgba(0,0,0,.4);
    }
    .header-title { font-size: 1.1rem; font-weight: 700; letter-spacing: .01em; }
    .header-meta  { font-size: .78rem; color: #94a3b8; }

    .main { max-width: 860px; margin: 0 auto; padding: 28px 16px 64px; }

    .day { margin-bottom: 36px; }
    .day-header {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 14px;
      padding-bottom: 10px;
      border-bottom: 2px solid #0f2044;
    }
    .day-name   { font-size: 1rem; font-weight: 700; color: #0f2044; }
    .today-pill {
      font-size: .68rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: .06em; background: #059669; color: #fff;
      padding: 2px 7px; border-radius: 4px;
    }
    .day-badge {
      font-size: .72rem; font-weight: 700;
      background: #2563eb; color: #fff;
      padding: 2px 9px; border-radius: 20px;
      margin-left: auto;
    }

    .company {
      background: #fff;
      border-radius: 8px;
      margin-bottom: 10px;
      box-shadow: 0 1px 4px rgba(0,0,0,.08);
      overflow: hidden;
    }
    .company-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 9px 16px;
      background: #f8fafc;
      border-bottom: 1px solid #f1f5f9;
    }
    .company-name  { font-size: .875rem; font-weight: 600; color: #1e3a8a; }
    .company-count {
      font-size: .7rem; font-weight: 600;
      color: #2563eb; background: #eff6ff;
      padding: 2px 8px; border-radius: 20px;
      white-space: nowrap;
    }

    .job-list { list-style: none; padding: 4px 0; }
    .job-list li {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 7px 16px 7px 28px;
      position: relative;
      border-bottom: 1px solid #f8fafc;
    }
    .job-list li:last-child { border-bottom: none; }
    .job-list li.job-new {
      background: #f0fdf4;
      border-left: 3px solid #22c55e;
    }
    .job-list li::before {
      content: "›";
      position: absolute;
      left: 14px;
      color: #2563eb;
      font-weight: 700;
      font-size: 1.05em;
    }
    .job-title {
      font-size: .86rem;
      color: #374151;
      flex: 1;
      min-width: 0;
    }
    a.job-title {
      color: #1d4ed8;
      text-decoration: none;
    }
    a.job-title:hover {
      text-decoration: underline;
      color: #1e40af;
    }
    .job-loc {
      font-size: .76rem;
      color: #64748b;
      white-space: nowrap;
      flex-shrink: 0;
    }

    .scrape-warning {
      background: #fff7ed;
      border: 1px solid #fed7aa;
      border-left: 4px solid #ea580c;
      border-radius: 6px;
      padding: 10px 16px;
      margin-bottom: 24px;
      font-size: .82rem;
      color: #7c2d12;
      line-height: 1.5;
    }
    .scrape-warning strong { color: #9f1239; }

    .empty { text-align: center; padding: 72px 24px; color: #64748b; }
    .empty h2 {
      font-size: 1.05rem; font-weight: 600;
      color: #334155; margin-bottom: 8px;
    }
    .empty p { font-size: .875rem; }

    .footer { text-align: center; padding: 20px; font-size: .73rem; color: #94a3b8; }

    .controls {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }
    .filter-select {
      flex: 1;
      min-width: 160px;
      padding: 8px 12px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      font-size: .875rem;
      color: #1e293b;
      background: #fff;
      cursor: pointer;
    }
    .run-btn {
      padding: 8px 18px;
      background: #2563eb;
      color: #fff;
      border: none;
      border-radius: 6px;
      font-size: .875rem;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
    }
    .run-btn:hover:not(:disabled) { background: #1d4ed8; }
    .run-btn:disabled { background: #94a3b8; cursor: not-allowed; }

    .progress-panel {
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 6px;
      padding: 10px 16px;
      margin-bottom: 16px;
      font-size: .84rem;
      color: #1e40af;
      align-items: center;
      gap: 10px;
    }
    .spinner {
      width: 16px; height: 16px;
      border: 2px solid #bfdbfe;
      border-top-color: #2563eb;
      border-radius: 50%;
      animation: spin .7s linear infinite;
      flex-shrink: 0;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    #pinned-section {
      background: #fff;
      border: 1px solid #e2e8f0;
      border-left: 4px solid #7c3aed;
      border-radius: 8px;
      margin-bottom: 24px;
      box-shadow: 0 1px 4px rgba(0,0,0,.08);
      overflow: hidden;
    }
    .pinned-header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 9px 16px;
      background: #faf5ff;
      border-bottom: 1px solid #ede9fe;
    }
    .pinned-title {
      font-size: .84rem;
      font-weight: 700;
      color: #5b21b6;
      flex: 1;
    }
    .pinned-badge {
      font-size: .7rem;
      font-weight: 700;
      background: #7c3aed;
      color: #fff;
      padding: 2px 9px;
      border-radius: 20px;
    }
    .pinned-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px 8px 14px;
      border-bottom: 1px solid #f8fafc;
    }
    .pinned-item:last-child { border-bottom: none; }
    .pinned-item.drag-over  { background: #f5f3ff; }
    .pinned-item.dragging   { opacity: .35; }
    .drag-handle {
      color: #d1d5db;
      cursor: grab;
      font-size: .78rem;
      letter-spacing: -1px;
      user-select: none;
      flex-shrink: 0;
      line-height: 1;
    }
    .drag-handle:active { cursor: grabbing; }
    .pinned-info { flex: 1; min-width: 0; }
    .pinned-job-title {
      font-size: .86rem;
      color: #1d4ed8;
      text-decoration: none;
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .pinned-job-title:hover { text-decoration: underline; }
    span.pinned-job-title   { color: #374151; }
    .pinned-meta {
      font-size: .72rem;
      color: #64748b;
      margin-top: 2px;
    }
    .unpin-btn {
      background: none;
      border: none;
      color: #94a3b8;
      cursor: pointer;
      font-size: 1rem;
      padding: 2px 7px;
      border-radius: 4px;
      flex-shrink: 0;
      line-height: 1;
    }
    .unpin-btn:hover { color: #ef4444; background: #fef2f2; }

    .job-right {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
    .pin-btn {
      background: none;
      border: none;
      cursor: pointer;
      padding: 0 2px;
      font-size: .8rem;
      line-height: 1;
      opacity: .18;
      transition: opacity .12s;
      flex-shrink: 0;
    }
    .job-list li:hover .pin-btn { opacity: .55; }
    .pin-btn:hover              { opacity: 1 !important; }
    .pin-btn.is-pinned          { opacity: 1; }

    @media (max-width: 600px) {
      .header { flex-wrap: wrap; padding: 12px 14px; gap: 6px; }
      .header-meta { font-size: .72rem; }
      .main { padding: 14px 10px 60px; }
      .day-header { flex-wrap: wrap; gap: 6px; }
      .day-badge { margin-left: 0; }
      .job-list li {
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        padding: 8px 14px 8px 26px;
      }
      .job-title { word-break: break-word; }
      .job-loc { white-space: normal; }
      .company-head { padding: 9px 12px; }
      .company-name { font-size: .82rem; }
      .controls { gap: 8px; }
      .filter-select { min-width: 0; }
      .pin-btn { opacity: .55; }
      .drag-handle { display: none; }
    }

    .zero-results { margin-bottom: 16px; }
    .zero-results > summary {
      cursor: pointer;
      list-style: none;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: .74rem;
      color: #94a3b8;
      user-select: none;
      padding: 2px 0;
    }
    .zero-results > summary::-webkit-details-marker { display: none; }
    .zero-results > summary::marker { content: none; }
    .zero-results > summary:focus-visible { outline: 1px dotted #cbd5e1; border-radius: 2px; }
    .zr-arrow {
      font-size: .6rem;
      display: inline-block;
      transition: transform .15s;
      color: #cbd5e1;
    }
    .zero-results[open] > summary .zr-arrow { transform: rotate(90deg); }
    .zr-body {
      margin-top: 6px;
      padding: 8px 12px;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
    }
    .zr-list { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 3px 18px; }
    .zr-list li { font-size: .77rem; }
    .zr-list a { color: #94a3b8; text-decoration: none; }
    .zr-list a:hover { color: #64748b; text-decoration: underline; }
"""


_JS_TEMPLATE = """\
(function () {
  function githubCtx() {
    var m = location.hostname.match(/^([^.]+)\\.github\\.io$/);
    if (!m) return null;
    var parts = location.pathname.replace(/^\\//, '').split('/');
    return parts[0] ? { owner: m[1], repo: parts[0] } : null;
  }

  var ctx = githubCtx();
  var runBtn = document.getElementById('run-btn');
  var progressPanel = document.getElementById('progress-panel');
  var progressText  = document.getElementById('progress-text');
  var spinner       = document.getElementById('spinner');
  var PORTAL_COUNT  = __N_PORTALS__;

  var filterSelect = document.getElementById('company-filter');

  (function buildFilter() {
    var seen = {}, names = [];
    document.querySelectorAll('.company-name').forEach(function (el) {
      var n = el.textContent;
      if (!seen[n]) { seen[n] = true; names.push(n); }
    });
    names.sort().forEach(function (n) {
      var opt = document.createElement('option');
      opt.value = n; opt.textContent = n;
      filterSelect.appendChild(opt);
    });
  })();

  filterSelect.addEventListener('change', function () {
    var val = filterSelect.value;
    document.querySelectorAll('.company').forEach(function (card) {
      var name = card.querySelector('.company-name').textContent;
      card.style.display = (!val || name === val) ? '' : 'none';
    });
    document.querySelectorAll('.day').forEach(function (day) {
      var anyVisible = [].slice.call(day.querySelectorAll('.company'))
        .some(function (c) { return c.style.display !== 'none'; });
      day.style.display = anyVisible ? '' : 'none';
    });
  });

  if (!ctx) {
    runBtn.disabled = true;
    runBtn.title = 'Only works when viewed on GitHub Pages';
    runBtn.style.opacity = '0.45';
  }

  runBtn.addEventListener('click', function () {
    triggerScrape().catch(function (e) {
      setStatus('Error: ' + e.message, false);
      runBtn.disabled = !ctx;
    });
  });

  function getPAT() {
    var pat = localStorage.getItem('nj_gh_pat');
    if (!pat) {
      pat = prompt(
        'Enter a GitHub Personal Access Token with "workflow" scope.\\n' +
        'Required to trigger the scrape workflow.\\n' +
        'Saved in this browser only.'
      );
      if (pat && pat.trim()) localStorage.setItem('nj_gh_pat', pat.trim());
    }
    return pat ? pat.trim() : null;
  }

  function setStatus(msg, showSpinner) {
    progressText.textContent = msg;
    spinner.style.display = showSpinner ? '' : 'none';
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  async function triggerScrape() {
    var pat = getPAT();
    if (!pat) return;

    runBtn.disabled = true;
    progressPanel.style.display = 'flex';
    setStatus('Triggering workflow…', true);

    var startTime = Date.now();
    var apiBase = 'https://api.github.com/repos/' + ctx.owner + '/' + ctx.repo;
    var headers  = {
      'Authorization': 'Bearer ' + pat,
      'Accept': 'application/vnd.github+json',
      'Content-Type': 'application/json'
    };

    var resp = await fetch(apiBase + '/actions/workflows/scrape.yml/dispatches', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ ref: 'main' })
    });

    if (resp.status === 401 || resp.status === 403) {
      localStorage.removeItem('nj_gh_pat');
      setStatus('PAT invalid or expired — try again.', false);
      runBtn.disabled = false;
      return;
    }
    if (!resp.ok) {
      setStatus('Could not trigger workflow (HTTP ' + resp.status + '). Check PAT scope.', false);
      runBtn.disabled = false;
      return;
    }

    var run = null, attempts = 0;
    setStatus('Workflow queued, waiting for it to start…', true);
    while (!run && attempts < 20) {
      await sleep(4000);
      attempts++;
      try {
        var r = await fetch(
          apiBase + '/actions/runs?event=workflow_dispatch&per_page=5',
          { headers: headers }
        );
        var data = await r.json();
        var runs = data.workflow_runs || [];
        for (var i = 0; i < runs.length; i++) {
          if (new Date(runs[i].created_at).getTime() >= startTime - 20000) {
            run = runs[i]; break;
          }
        }
      } catch (_) {}
    }

    if (!run) {
      setStatus('Could not locate the workflow run. Check the Actions tab on GitHub.', false);
      runBtn.disabled = false;
      return;
    }

    while (true) {
      var elapsed   = Math.round((Date.now() - startTime) / 1000);
      var estimated = Math.min(Math.floor(elapsed / 30), PORTAL_COUNT);

      if (run.status === 'completed') {
        if (run.conclusion === 'success') {
          setStatus('Done! Refreshing…', false);
          await sleep(1500);
          location.reload();
        } else {
          setStatus('Workflow ended: ' + run.conclusion + '. Check the Actions tab for details.', false);
          runBtn.disabled = false;
        }
        return;
      }

      setStatus(estimated + '/' + PORTAL_COUNT + ' employers checked (est.) — ' + elapsed + 's elapsed', true);
      await sleep(15000);

      try {
        var upd = await fetch(run.url, { headers: headers });
        run = await upd.json();
      } catch (_) {}
    }
  }
})();
"""


_PINNING_JS = """\
(function () {
  var LS_KEY = 'nj_pinned_v1';
  var cache  = [];

  function lsLoad() {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || '[]'); }
    catch (_) { return []; }
  }
  function persist() { localStorage.setItem(LS_KEY, JSON.stringify(cache)); }

  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function fmtDate(s) {
    var p = s.split('-');
    if (p.length < 3) return s;
    var mon = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return +p[2] + ' ' + (mon[+p[1] - 1] || '') + ' ' + p[0];
  }

  function render() {
    var section = document.getElementById('pinned-section');
    var list    = document.getElementById('pinned-list');
    var badge   = document.getElementById('pinned-count');
    if (!section) return;
    if (!cache.length) { section.style.display = 'none'; return; }
    section.style.display = '';
    badge.textContent = cache.length;
    list.innerHTML = cache.map(function (p, i) {
      var t = p.url
        ? '<a href="' + esc(p.url) + '" target="_blank" rel="noopener" class="pinned-job-title">' + esc(p.title) + '</a>'
        : '<span class="pinned-job-title">' + esc(p.title) + '</span>';
      return (
        '<div class="pinned-item" draggable="true" data-idx="' + i + '">' +
        '<span class="drag-handle" aria-hidden="true">⋮⋮</span>' +
        '<div class="pinned-info">' + t +
        '<div class="pinned-meta">' + esc(p.company) + ' · ' + fmtDate(p.date) + '</div>' +
        '</div>' +
        '<button class="unpin-btn" data-idx="' + i + '" title="Unpin (applied)" aria-label="Unpin">×</button>' +
        '</div>'
      );
    }).join('');
    list.querySelectorAll('.unpin-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        cache.splice(+btn.dataset.idx, 1);
        render();
        syncButtons();
        persist();
      });
    });
    initDrag();
  }

  function syncButtons() {
    var set = {};
    cache.forEach(function (p) { set[p.id] = true; });
    document.querySelectorAll('li[data-pin-id]').forEach(function (li) {
      var btn = li.querySelector('.pin-btn');
      if (!btn) return;
      var pinned = !!set[li.dataset.pinId];
      btn.classList.toggle('is-pinned', pinned);
      btn.setAttribute('aria-pressed', String(pinned));
    });
  }

  function togglePin(li) {
    var id  = li.dataset.pinId;
    var idx = cache.findIndex(function (p) { return p.id === id; });
    if (idx >= 0) {
      cache.splice(idx, 1);
    } else {
      cache.push({
        id:      id,
        title:   li.dataset.title,
        url:     li.dataset.url || null,
        company: li.dataset.company,
        date:    li.dataset.date
      });
    }
    render();
    syncButtons();
    persist();
  }

  document.querySelectorAll('.pin-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var li = btn.closest('li[data-pin-id]');
      if (!li) return;
      togglePin(li);
    });
  });

  function initDrag() {
    var list    = document.getElementById('pinned-list');
    var dragged = null;
    list.querySelectorAll('.pinned-item').forEach(function (item) {
      item.addEventListener('dragstart', function (e) {
        dragged = item;
        e.dataTransfer.effectAllowed = 'move';
        setTimeout(function () { item.classList.add('dragging'); }, 0);
      });
      item.addEventListener('dragend', function () {
        item.classList.remove('dragging');
        list.querySelectorAll('.pinned-item').forEach(function (i) { i.classList.remove('drag-over'); });
        dragged = null;
      });
      item.addEventListener('dragover', function (e) {
        e.preventDefault();
        if (item !== dragged) {
          list.querySelectorAll('.pinned-item').forEach(function (i) { i.classList.remove('drag-over'); });
          item.classList.add('drag-over');
        }
      });
      item.addEventListener('dragleave', function () { item.classList.remove('drag-over'); });
      item.addEventListener('drop', function (e) {
        e.preventDefault();
        if (!dragged || item === dragged) return;
        cache.splice(+item.dataset.idx, 0, cache.splice(+dragged.dataset.idx, 1)[0]);
        render();
        syncButtons();
        persist();
      });
    });
  }

  cache = lsLoad();
  syncButtons();
  render();
})();
"""


def generate_dashboard():
    snaps = _all_snapshots()

    if snaps:
        last_utc = _snap_dt(snaps[-1]).replace(tzinfo=timezone.utc)
        last_et  = last_utc.astimezone(ZoneInfo("America/Toronto"))
        last_str = (
            f"{last_et.day} {last_et.strftime('%B %Y')} "
            f"at {last_et.strftime('%H:%M')} {last_et.strftime('%Z')}"
        )
    else:
        last_str = "never"

    n_portals = len([name for name, *_ in load_portals() if not name.startswith(_CTL_PREFIX)])
    n_snaps   = len(snaps)
    today_str = _date.today().isoformat()
    result    = _daily_new()

    if not result:
        content = (
            '    <div class="empty">\n'
            '      <h2>Baseline captured — no comparisons yet</h2>\n'
            '      <p>New jobs will appear here once a second snapshot has been collected.</p>\n'
            '    </div>'
        )
    else:
        sections = []
        for idx, (date_str, companies) in enumerate(result):
            dt         = datetime.strptime(date_str, "%Y-%m-%d")
            date_label = f"{dt.day} {dt.strftime('%B %Y')}"
            total      = sum(len(j) for j in companies.values())
            today_pill = '<span class="today-pill">today</span>' if date_str == today_str else ""

            cards = []
            for company, jobs in sorted(companies.items()):
                count = f"{len(jobs)} job" + ("s" if len(jobs) != 1 else "")
                items = []
                for job in jobs:
                    j     = _to_dict(job)
                    title = _esc(j["title"])
                    url   = j.get("url")
                    loc   = j.get("location")

                    title_html = (
                        f'<a href="{_esc(url)}" target="_blank" rel="noopener" class="job-title">{title}</a>'
                        if url else
                        f'<span class="job-title">{title}</span>'
                    )
                    loc_html = (
                        f'<span class="job-loc">{_esc(loc)}</span>'
                        if loc else ""
                    )
                    is_new     = (idx == 0)
                    li_class   = ' class="job-new"' if is_new else ""
                    pin_id     = _esc(f"{company}|{j['title']}".lower())
                    data_attrs = (
                        f' data-pin-id="{pin_id}"'
                        f' data-title="{_esc(j["title"])}"'
                        f' data-url="{_esc(j.get("url") or "")}"'
                        f' data-company="{_esc(company)}"'
                        f' data-date="{date_str}"'
                    )
                    pin_btn    = '<button class="pin-btn" aria-pressed="false" aria-label="Pin this job">\U0001f4cc</button>'
                    right_html = f'<span class="job-right">{loc_html}{pin_btn}</span>'
                    items.append(f'          <li{li_class}{data_attrs}>{title_html}{right_html}</li>')

                cards.append(
                    f'        <div class="company">\n'
                    f'          <div class="company-head">'
                    f'<span class="company-name">{_esc(company)}</span>'
                    f'<span class="company-count">{count}</span>'
                    f'</div>\n'
                    f'          <ul class="job-list">\n'
                    + "\n".join(items) + "\n"
                    f'          </ul>\n'
                    f'        </div>'
                )

            sections.append(
                f'    <section class="day">\n'
                f'      <div class="day-header">\n'
                f'        <h2 class="day-name">{_esc(date_label)}</h2>\n'
                f'        {today_pill}\n'
                f'        <span class="day-badge">{total} new</span>\n'
                f'      </div>\n'
                f'      <div class="companies">\n'
                + "\n".join(cards) + "\n"
                f'      </div>\n'
                f'    </section>'
            )

        content = "\n".join(sections)

    footer = (
        f'{n_portals} companies tracked'
        f' &nbsp;·&nbsp; {n_snaps} snapshot{"s" if n_snaps != 1 else ""}'
    )

    regressions = _scrape_regressions()
    if regressions:
        reg_names = ", ".join(_esc(c) for c in regressions)
        warning_block = (
            f'    <div class="scrape-warning">\n'
            f'      <strong>Scraping may have failed:</strong> {reg_names} returned 0 jobs '
            f'this run but had results last time. Your IP may be blocked — check these portals manually.\n'
            f'    </div>\n'
        )
    else:
        warning_block = ""

    zero_portals = _zero_result_portals()
    if zero_portals:
        items_html = "\n".join(
            f'          <li><a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(name)}</a></li>'
            for name, url in zero_portals
        )
        zero_results_html = (
            f'    <details class="zero-results">\n'
            f'      <summary>'
            f'<span class="zr-arrow">&#9658;</span>'
            f' Sites returning 0 jobs ({len(zero_portals)})'
            f'</summary>\n'
            f'      <div class="zr-body"><ul class="zr-list">\n'
            f'{items_html}\n'
            f'      </ul></div>\n'
            f'    </details>\n'
        )
    else:
        zero_results_html = ""

    js = _JS_TEMPLATE.replace("__N_PORTALS__", str(n_portals))

    controls_html = (
        '    <div class="controls">\n'
        '      <select id="company-filter" class="filter-select">'
        '<option value="">All companies</option>'
        '</select>\n'
        '      <button id="run-btn" class="run-btn">&#9654; Run Scraper</button>\n'
        '    </div>\n'
        '    <div id="progress-panel" class="progress-panel" style="display:none">\n'
        '      <div id="spinner" class="spinner"></div>\n'
        '      <span id="progress-text"></span>\n'
        '    </div>\n'
    )

    html = (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "  <title>Zoe's Jobs Scraper</title>\n"
        f'  <style>{_CSS}  </style>\n'
        '</head>\n'
        '<body>\n'
        '  <header class="header">\n'
        "    <span class=\"header-title\">Zoe's Jobs Scraper</span>\n"
        f'    <span class="header-meta">Last scraped: {_esc(last_str)}</span>\n'
        '  </header>\n'
        '  <main class="main">\n'
        '    <section id="pinned-section" style="display:none">\n'
        '      <div class="pinned-header">\n'
        '        <span class="pinned-title">\U0001f4cc Pinned</span>\n'
        '        <span id="pinned-count" class="pinned-badge">0</span>\n'
        '      </div>\n'
        '      <div id="pinned-list"></div>\n'
        '    </section>\n'
        f'{zero_results_html}'
        f'{controls_html}'
        f'{warning_block}'
        f'{content}\n'
        '  </main>\n'
        f'  <footer class="footer">{footer}</footer>\n'
        f'  <script>\n{js}\n  </script>\n'
        f'  <script>\n{_PINNING_JS}\n  </script>\n'
        '</body>\n'
        '</html>\n'
    )

    DASHBOARD_FILE.write_text(html, encoding="utf-8")


# ── scrape ────────────────────────────────────────────────────────────────────

def scrape():
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    now   = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d_%H%M")
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    snapshot_path = SNAPSHOTS_DIR / f"{stamp}.json"

    if snapshot_path.exists():
        print(f"Snapshot for {stamp} already exists. Delete it to re-scrape.")
        return

    portals  = load_portals()
    snapshot = {}

    # Names of companies tracked by direct (non-CTL) portals — for CTL dedup
    non_ctl_names = {name.lower() for name, url, *_ in portals
                     if not name.startswith(_CTL_PREFIX)}

    # Accumulated jobs from Climate Tech List pages, keyed by actual company name
    ctl_accumulated: dict[str, list[dict]] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
            locale="en-CA",
            timezone_id="America/Toronto",
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.new_page()

        for name, url, selector, loc_filter in portals:
            print(f"  {name} ... ", end="", flush=True)
            try:
                if name.startswith(_CTL_PREFIX):
                    raw = _extract_ctl_jobs(page, url)
                    added = 0
                    skipped = 0
                    for job in raw:
                        co = job.get("company", "").strip()
                        if not co:
                            continue
                        if co.lower() in non_ctl_names:
                            skipped += 1
                            continue
                        if not _is_canada(job.get("location")):
                            continue
                        j = _to_dict(job)
                        k = _job_key(j)
                        bucket = ctl_accumulated.setdefault(co, [])
                        if not any(_job_key(x) == k for x in bucket):
                            bucket.append(j)
                            added += 1
                    print(f"{len(raw)} raw, {skipped} already tracked, {added} new")
                    page.wait_for_timeout(random.randint(2_000, 4_000))
                    continue

                jobs = extract_jobs(page, url, selector)

                # Deduplicate by title
                seen: set[str] = set()
                unique: list[dict] = []
                for j in jobs:
                    k = _job_key(j)
                    if k not in seen:
                        seen.add(k)
                        unique.append(j)

                # Per-portal location filter (legacy support for explicit loc_filter field)
                if loc_filter:
                    before = len(unique)
                    unique = [j for j in unique if _loc_matches(j.get("location"), loc_filter)]
                    print(f"({before} total, {before - len(unique)} filtered by loc={loc_filter!r}) ", end="", flush=True)

                # Canada-only filter
                before_ca = len(unique)
                unique = [j for j in unique if _is_canada(j.get("location"))]
                filtered_ca = before_ca - len(unique)

                if name in snapshot:
                    existing_keys = {_job_key(j) for j in snapshot[name]}
                    added = [j for j in unique if _job_key(j) not in existing_keys]
                    snapshot[name].extend(added)
                    snapshot[name].sort(key=lambda j: _job_title(j).lower())
                    note = f"  ({filtered_ca} non-CA filtered)" if filtered_ca else ""
                    print(f"{len(unique)} job(s) → {len(snapshot[name])} total{note}")
                else:
                    unique.sort(key=lambda j: _job_title(j).lower())
                    snapshot[name] = unique
                    note = f"  ({filtered_ca} non-CA filtered)" if filtered_ca else ""
                    print(f"{len(unique)} job(s){note}")

            except Exception as exc:
                print(f"ERROR — {exc}")
                if name not in snapshot:
                    snapshot[name] = []

            page.wait_for_timeout(random.randint(2_000, 4_000))

        # Merge Climate Tech List results under their real company names
        if ctl_accumulated:
            total_ctl = sum(len(v) for v in ctl_accumulated.values())
            print(f"\n  CTL merge: {total_ctl} jobs across {len(ctl_accumulated)} companies")
            for company, jobs in ctl_accumulated.items():
                jobs.sort(key=lambda j: _job_title(j).lower())
                if company in snapshot:
                    existing_keys = {_job_key(j) for j in snapshot[company]}
                    new_jobs = [j for j in jobs if _job_key(j) not in existing_keys]
                    snapshot[company].extend(new_jobs)
                    snapshot[company].sort(key=lambda j: _job_title(j).lower())
                else:
                    snapshot[company] = jobs

        browser.close()

    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    _write_snapshot_index()
    generate_dashboard()

    existing_snaps = _all_snapshots()
    if len(existing_snaps) == 1:
        print(f"\nBaseline saved ({snapshot_path}).")
        print("Run again any time — new jobs will appear after your second scrape.")
    else:
        print(f"\nSnapshot saved ({snapshot_path.name}).")
        print("To view: python -m http.server 8000  then open http://localhost:8000/dashboard.html")


# ── display (terminal) ────────────────────────────────────────────────────────

def display():
    result = _daily_new()
    if not result:
        print("No new jobs yet — need at least 2 snapshots.")
        return
    for date_str, companies in result:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        print(f"\n{dt.day} {dt.strftime('%B %Y')}")
        for company, jobs in sorted(companies.items()):
            print(f"  {company}:")
            for job in jobs:
                j   = _to_dict(job)
                loc = f"  —  {j['location']}" if j.get("location") else ""
                print(f"    {j['title']}{loc}")
                if j.get("url"):
                    print(f"      {j['url']}")
    print()


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "scrape":
        scrape()
    elif cmd == "display":
        display()
    elif cmd == "dashboard":
        generate_dashboard()
        print(f"Dashboard written to {DASHBOARD_FILE.resolve()}")
    else:
        print("Usage:  python tracker.py  scrape | display | dashboard")
        sys.exit(1)


if __name__ == "__main__":
    main()
