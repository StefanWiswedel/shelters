# Amager shelter availability

Scrapes `book.naturstyrelsen.dk` and renders one page showing which of the
9 self-bookable shelters on Amager are free, with Friday and Saturday nights
highlighted.

## Three ways to run it

### 1. On your own machine, with a Refresh button

```
python3 shelters.py serve
```

Opens at `http://localhost:8765`. The Refresh button re-scrapes and reloads,
about 15 seconds. Nothing to install — standard library only, Python 3.9+.

Only reachable from that machine. Fine at a desk, useless on your phone.

### 2. Scheduled on your own machine

Rebuild the file twice a day and just open it whenever:

```
crontab -e
# add:
17 7,19 * * * cd /path/to/shelters && /usr/bin/python3 shelters.py
```

Writes `amager-shelters.html` next to the script. On macOS you may need to
grant cron full disk access; on Windows use Task Scheduler instead.

Still only on that machine, and only updates while it's awake.

### 3. GitHub Actions + Pages (a real site, works on your phone)

Put `shelters.py` in a repo, `build.yml` at `.github/workflows/build.yml`,
then in the repo: **Settings → Pages → Source: GitHub Actions**.

Every run builds into `site/` and publishes. There is no schedule: the
workflow runs on push, and on demand via **Actions → Build shelter page →
Run workflow** — which is your Refresh button from anywhere, including the
GitHub mobile app. A run takes about a minute; reload the page afterwards
and check the `fetched` timestamp in the header has moved.

Public repo means a public URL. Nothing sensitive here, but if you'd rather
it not be indexed, a private repo with Pages requires a paid plan.

## Things worth knowing

- **The page only updates when you ask it to.** There is no schedule, so
  whatever it shows is from the last run — check the `fetched` timestamp in
  the header before trusting it. This is deliberate: a cron would hit their
  booking system twice a day to refresh a page that gets read every few
  weeks, and GitHub disables scheduled workflows after 60 days without repo
  activity, so it would eventually switch itself off and go quietly stale.
- **`amager-places.json` caches the site IDs and booking windows.** Running
  locally, it's re-discovered automatically once the file is 30 days old, so a
  newly added shelter shows up within a month. Delete it to force a re-scan now.
  In Actions that ageing never happens — `actions/checkout` gives every file a
  fresh mtime on each run, so the cache always looks new and the site list is
  never re-scanned on its own. To refresh it there, run the workflow manually
  and tick **Re-scan the site list**; the run re-discovers and commits the
  updated file back.
- **Be reasonable if you ever add a schedule back.** Each build is roughly 20
  requests to their server, or about 40 with **Re-scan the site list** ticked.
  Twice a day is neighbourly; every five minutes is not, and it's their
  booking system for the whole country.
- **The greying of dates past the booking window is computed at build time**,
  so a page that hasn't rebuilt in a week shows a stale boundary.

## What's covered

State-owned (Naturstyrelsen) shelters only, which on Amager is everything you
can actually book yourself. Group camps (`Teltplads` / lejrplads — Sneppen,
Viben, Bjarkebo) are filtered out; set `SKIP_GROUP_CAMPS = False` to bring
them back. Hourly-booked madpakkehuse are excluded because their bookings
live in a different field and would render as permanently free.
