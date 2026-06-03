# Zoe's Jobs Scraper

Scrapes climate tech career pages daily and shows only the **new** jobs since your last run. Canada-only roles, pulled from direct employer pages and Climate Tech List aggregators.

## Why Python + Playwright?

Modern career pages are almost all JavaScript SPAs — Workday, Taleo, iCIMS, BambooHR, Breezy HR, etc. A plain `requests` call only sees the raw HTML before JS runs, which is usually an empty shell. Playwright launches a real headless Chromium browser, lets the page fully render, clicks through pagination and "Load More" buttons, then extracts job titles. Snapshots are plain JSON files — no database, no server.

---

## Setup

**1. Install Python dependencies**

```
pip install -r requirements.txt
```

**2. Install the Chromium browser** (one-time, ~130 MB)

```
playwright install chromium
```

---

## Configure your portals

Edit `jobs_portals_list.txt`. Each line is tab-separated:

```
Company Name	URL
```

The script auto-detects the ATS platform (Workday, iCIMS, BambooHR, Greenhouse, Lever, Taleo, Breezy HR, SmartRecruiters, JobVite, etc.) and picks the right CSS selector automatically.

If auto-detection returns zero jobs for a site, add your own selector as a third tab-separated field:

```
Example Corp	https://example.com/careers	h2.job-title
```

To find the right selector: open the page in Chrome, right-click a job title → Inspect → right-click the element in DevTools → Copy → Copy selector.

Lines starting with `#` are ignored.

### Canada filtering

Every scraped role is automatically filtered to only keep Canadian positions. A role is kept if its location contains "Canada", a province abbreviation (ON, BC, AB, QC, …), or a recognisable Canadian city. Roles with no location listed are kept (benefit of the doubt).

### Climate Tech List aggregators

Lines whose name starts with `Climate Tech List` are treated as aggregator pages. The scraper extracts the actual employer name from each job card and:
- **Discards** jobs from companies already tracked by a direct portal entry (to avoid duplicates)
- **Keeps** jobs from companies not tracked elsewhere, stored under the real company name

The dashboard never shows a "Climate Tech List" section.

---

## Usage

**First run — saves a baseline (no diff yet):**

```
python tracker.py scrape
```

**Every subsequent run:**

```
python tracker.py scrape     # capture today's snapshot
python tracker.py display    # show new jobs since last run in terminal
```

**View the dashboard locally:**

```
python -m http.server 8000
```

Then open `http://localhost:8000/dashboard.html` in your browser.

**Offline embedded dashboard (no server needed):**

```
python tracker.py dashboard
```

Opens `dashboard.html` directly in your browser with all data baked in.

---

## Snapshots

Saved in `snapshots/YYYY-MM-DD_HHMM.json`. Each run creates its own timestamped file. `snapshots/index.json` lists all snapshots and portal metadata for the client-side dashboard.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| A site shows `0 job(s)` | Add a custom CSS selector as the third tab-separated field in `jobs_portals_list.txt` |
| `playwright install` hangs | Run it in a terminal with internet access; it downloads ~130 MB |
| A site shows nav items, not jobs | The fallback selector matched too broadly — add a specific selector |
| `ERROR — Timeout` | The site may block headless browsers; try visiting manually |
| All jobs filtered as non-Canadian | The site lists US locations on Canadian roles — add a 4th field with the loc_filter override, e.g. `	Canada` |

---

## GitHub Deployment (run automatically + view on phone)

The scraper runs on GitHub's servers once daily via GitHub Actions, and the dashboard is served as a static website via GitHub Pages.

---

### Step 1 — Push to GitHub for the first time

Initialize a git repository and push to a new **empty** GitHub repo (no README, no .gitignore):

```
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO-NAME.git
git branch -M main
git push -u origin main
```

Replace `YOUR-USERNAME` and `YOUR-REPO-NAME` with your actual GitHub username and repo name.

---

### Step 2 — Enable GitHub Actions

GitHub Actions is enabled automatically for new repos. To confirm:

1. Open your repo on github.com
2. Click the **Actions** tab
3. If prompted to enable Actions, click **Enable**

---

### Step 3 — Enable GitHub Pages

1. Open your repo on github.com → **Settings** → **Pages** (left sidebar)
2. Under **Source**, choose **Deploy from a branch**
3. Set the branch to **main** and the folder to **/ (root)**
4. Click **Save**

Your dashboard will be live at:

```
https://YOUR-USERNAME.github.io/YOUR-REPO-NAME/dashboard.html
```

---

### Step 4 — Enable the "Run Scraper" button

The dashboard has a **▶ Run Scraper** button that triggers a scrape from any browser. It needs a GitHub Personal Access Token (PAT).

**Create a PAT:**

1. Go to github.com → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
2. Click **Generate new token (classic)**
3. Name it `zoes-job-tracker-run`
4. Under **Select scopes**, check **workflow**
5. Click **Generate token** and copy it (shown only once)

**Use the PAT:**

1. Open your dashboard at the GitHub Pages URL
2. Click **▶ Run Scraper**
3. Paste your PAT when prompted — saved in browser only

To clear a saved PAT:

```js
localStorage.removeItem('nj_gh_pat')
```

---

### Schedule

The scraper runs automatically once per day at 23:00 UTC (7pm EDT / 6pm EST). Each run commits a new snapshot JSON and updated `snapshots/index.json` to the repo.

To change the schedule, edit the `cron` line in `.github/workflows/scrape.yml`.

---

## Local scheduled runs (Windows)

To run automatically on your PC without GitHub:

```
.\setup_schedule.ps1
```

This registers a Windows Task Scheduler job that runs at 8:00 AM and 1:00 PM daily.
