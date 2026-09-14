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

Every run builds into `site/` and publishes. The workflow triggers on a
schedule, on push, and via **Actions → Build shelter page → Run workflow**
for a manual rebuild — which is your Refresh button from anywhere, including
the GitHub mobile app.

Public repo means a public URL. Nothing sensitive here, but if you'd rather
it not be indexed, a private repo with Pages requires a paid plan.

## Things worth knowing

- **GitHub's cron is best-effort.** Scheduled runs are frequently delayed by
  10–30 minutes and occasionally skipped entirely under load. Fine for this;
  don't build anything time-critical on it.
- **Scheduled workflows get disabled after 60 days without repo activity.**
  GitHub emails you first. A push or a manual run resets the clock.
- **`amager-places.json` caches the site IDs and booking windows.** It's
  re-discovered automatically once it's 30 days old, so a newly added shelter
  shows up within a month. Delete it to force a re-scan now.
- **Be reasonable with the scheduling.** Each build is roughly 20 requests to
  their server. Twice a day is neighbourly; every five minutes is not, and
  it's their booking system for the whole country.
- **The greying of dates past the booking window is computed at build time**,
  so a page that hasn't rebuilt in a week shows a stale boundary.

## What's covered

State-owned (Naturstyrelsen) shelters only, which on Amager is everything you
can actually book yourself. Group camps (`Teltplads` / lejrplads — Sneppen,
Viben, Bjarkebo) are filtered out; set `SKIP_GROUP_CAMPS = False` to bring
them back. Hourly-booked madpakkehuse are excluded because their bookings
live in a different field and would render as permanently free.
