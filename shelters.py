#!/usr/bin/env python3
"""
Amager shelter availability -> one HTML page.

Two ways to run:

  python3 shelters.py              build amager-shelters.html and exit
  python3 shelters.py serve        local server at http://localhost:8765
                                   with a working Refresh button

Data comes from two undocumented JSON endpoints behind book.naturstyrelsen.dk:
  inc_ajaxbookingplaces.asp             all bookable places (lat/lng/slug)
  inc_ajaxgetbookingsforsingleplace.asp BOOKED dates for one place, ~3 months

Availability is inferred: a date inside the place's own booking window that is
not in BookingDates is free. Hourly-booked places (madpakkehuse, baalhytter)
are skipped -- their bookings live in a different field, so this page would
show them as permanently free.

Site IDs and booking windows are cached in amager-places.json next to this
script. Delete that file to re-discover places.
"""

import json
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE = "https://book.naturstyrelsen.dk"
LIST = BASE + "/includes/branding_files/shelterbooking/includes/inc_ajaxbookingplaces.asp"
BOOK = BASE + "/includes/branding_files/shelterbooking/includes/inc_ajaxgetbookingsforsingleplace.asp"

HERE = Path(__file__).resolve().parent
CACHE = HERE / "amager-places.json"
OUT = HERE / "amager-shelters.html"

# Amager bounding box: Kalvebod Faelled, Pinseskoven, Kongelunden, Dragoer
BBOX = (55.50, 55.70, 12.50, 12.80)  # lat_min, lat_max, lng_min, lng_max

# Group camps (FType "Teltplads" / lejrplads) are meant for organised groups of
# 15+ -- schools, scouts, clubs -- and book up to 12 months ahead. Set this to
# False if you ever want them back on the page.
SKIP_GROUP_CAMPS = True

DAYS = 100          # columns to draw; anything past a site's window is greyed
PORT = 8765
POLITE = 0.4        # seconds between requests to their server
UA = {"User-Agent": "amager-shelter-check/2.0 (personal use)"}

# Set by GitHub Actions. Empty for a local build, which leaves the rebuild
# link and its status polling out of the page entirely -- so `python3
# shelters.py` on your own machine produces exactly what it always did.
REPO = os.environ.get("GITHUB_REPOSITORY", "")
RUN_ID = os.environ.get("GITHUB_RUN_ID", "")
# "owner/repo/.github/workflows/build.yml@refs/heads/main" -> "build.yml"
WORKFLOW = (os.environ.get("GITHUB_WORKFLOW_REF", "").split("@")[0]
            .rsplit("/", 1)[-1]) or "build.yml"


# ---------------------------------------------------------------- fetching

def get(url, decode="iso-8859-1"):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode(decode, "replace")


def window_length(html):
    """How many days ahead this place can be booked, from its own dStart/dEnd."""
    s = re.search(r"dStart\s*=\s*new Date\((\d+),\s*(\d+),\s*(\d+)\)", html)
    e = re.search(r"dEnd\s*=\s*new Date\((\d+),\s*(\d+),\s*(\d+)\)", html)
    if not (s and e):
        return 90
    ds = date(int(s.group(1)), int(s.group(2)) + 1, int(s.group(3)))  # JS months 0-based
    de = date(int(e.group(1)), int(e.group(2)) + 1, int(e.group(3)))
    return max((de - ds).days, 1)


def discover():
    """Find Amager places, their numeric IDs, booking type and window."""
    data = json.loads(get(f"{LIST}?pid=0&p=1&r=100&ps=5000&t=1"))
    lo_lat, hi_lat, lo_lng, hi_lng = BBOX
    hits = [p for p in data["BookingPlacesList"]
            if lo_lat < p["DoubleLat"] < hi_lat and lo_lng < p["DoubleLng"] < hi_lng]

    out = []
    for p in sorted(hits, key=lambda x: x["Title"]):
        html = get(f"{BASE}/sted/{p['Uri']}/")
        m = re.search(r"iPlaceID\s*=\s*(\d+)", html)
        if not m:
            print("  no place id:", p["Title"], file=sys.stderr)
            continue
        kind = re.search(r'data-settingstype="(\w+)"', html)
        kind = kind.group(1) if kind else "daily"
        if kind != "daily":
            print(f"  skipping {p['Title']} ({kind} booking)")
            time.sleep(POLITE)
            continue
        if SKIP_GROUP_CAMPS and p["FType"] == "Teltplads":
            print(f"  skipping {p['Title']} (group camp)")
            time.sleep(POLITE)
            continue
        out.append({
            "id": int(m.group(1)),
            "title": p["Title"],
            "type": p["FType"],
            "uri": p["Uri"],
            "lat": p["DoubleLat"],
            "lng": p["DoubleLng"],
            "window_days": window_length(html),
        })
        time.sleep(POLITE)

    CACHE.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


CACHE_MAX_AGE = 30 * 86400   # re-discover sites monthly


def cache_fresh():
    if not CACHE.exists():
        return False
    return (time.time() - CACHE.stat().st_mtime) < CACHE_MAX_AGE


def places():
    ps = json.loads(CACHE.read_text()) if cache_fresh() else discover()
    if SKIP_GROUP_CAMPS:
        ps = [p for p in ps if p["type"] != "Teltplads"]
    return ps


def booked_dates(place_id):
    """Booked dates. Two probes because one call only returns ~3 months."""
    got = set()
    for offset in (0, 60):
        d = (date.today() + timedelta(days=offset)).strftime("%Y%m%d")
        try:
            j = json.loads(get(f"{BOOK}?i={place_id}&d={d}"))
        except Exception as exc:
            print(f"  fetch failed ({place_id}, {d}): {exc}", file=sys.stderr)
            continue
        got.update(j.get("BookingDates") or [])
        time.sleep(POLITE)
    return got


def scrape(log=print):
    ps = places()
    log(f"{len(ps)} bookable daily sites on Amager")
    avail = {}
    for p in ps:
        avail[p["id"]] = sorted(booked_dates(p["id"]))
        log(f"  {p['title']}: {len(avail[p['id']])} booked")
    return ps, avail


# ---------------------------------------------------------------- rendering

CSS = """
:root{
  --ink:#e8e4d9; --dim:#8b8778; --line:#2e332c;
  --bg:#12150f; --panel:#191d15;
  --free:#4f7a41; --freewe:#a3d95f; --busy:#33382f; --busywe:#4a3f30;
  --out:#1b1e18; --accent:#d98c3f;
  --cell:22px;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  font-size:15px;line-height:1.5}
header{padding:20px 16px 14px;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:21px;font-weight:600}
.sub{color:var(--dim);font-size:12px;margin-top:5px;
  font-family:ui-monospace,"SF Mono",Menlo,monospace}
.bar{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;margin-top:13px;
  font-size:11.5px;color:var(--dim);
  font-family:ui-monospace,"SF Mono",Menlo,monospace}
.sw{display:inline-block;width:11px;height:11px;border-radius:2px;
  vertical-align:-1px;margin-right:5px}
button#refresh,a#rebuild{font:inherit;font-size:11.5px;letter-spacing:.06em;
  text-transform:uppercase;background:var(--panel);color:var(--ink);
  border:1px solid var(--line);border-radius:3px;padding:8px 15px;
  cursor:pointer;-webkit-tap-highlight-color:transparent;
  text-decoration:none;display:inline-block}
button#refresh:hover,a#rebuild:hover{border-color:var(--free);color:var(--free)}
button#refresh[disabled]{opacity:.5;cursor:progress}
#age{color:var(--dim)}
#age.stale{color:var(--accent)}
#status:not(:empty){color:var(--accent)}
#status.live::before{content:"";display:inline-block;width:7px;height:7px;
  border-radius:50%;background:var(--accent);margin-right:6px;
  vertical-align:1px;animation:pulse 1.4s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
@media (prefers-reduced-motion:reduce){
  #status.live::before{animation:none}
}

.wrap{overflow:auto;-webkit-overflow-scrolling:touch;padding-bottom:20px}
table{border-collapse:separate;border-spacing:0;font-size:12px}
th,td{padding:0;white-space:nowrap}
td.cell{width:var(--cell);height:26px;border-bottom:1px solid var(--line);
  border-right:1px solid rgba(0,0,0,.4)}
td.cell a{display:block;width:100%;height:100%;
  -webkit-tap-highlight-color:transparent}
td.free{background:var(--free)}
td.busy{background:var(--busy)}
td.out{background:var(--out)}
td.we{box-shadow:inset 0 0 0 1px rgba(217,140,63,.30)}
td.free.we{background:var(--freewe)}
td.busy.we{background:var(--busywe)}
td.cell:hover{outline:2px solid var(--accent);outline-offset:-2px}
.hint{padding:8px 16px 0;color:var(--dim);font-size:11.5px;
  font-family:ui-monospace,monospace}

/* ---- wide grid: sites down, days across ---- */
.wide th.site{position:sticky;left:0;z-index:3;background:var(--panel);
  text-align:left;font-weight:500;padding:7px 14px 7px 16px;
  border-right:1px solid var(--line);border-bottom:1px solid var(--line);
  font-size:13px;min-width:250px}
.wide th.site a{color:var(--ink);text-decoration:none;
  border-bottom:1px dotted var(--dim)}
.wide th.site a:hover{color:var(--free)}
.wide th.site small{display:block;color:var(--dim);font-size:11px;
  font-family:ui-monospace,monospace}
.wide thead th.site{top:0;z-index:4}
.wide thead th{position:sticky;top:0;background:var(--bg);z-index:2;
  border-bottom:1px solid var(--line);width:var(--cell);
  font-family:ui-monospace,"SF Mono",Menlo,monospace;font-weight:400;
  font-size:10px;color:var(--dim);padding:6px 0 5px}
.wide thead th.we{color:var(--accent);font-weight:600}
.wide thead th b{display:block;font-weight:600;font-size:11px}
.mstrip th{text-align:left;font-size:10.5px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--dim);padding:9px 0 4px 3px;
  background:var(--bg)}

/* ---- tall grid: days down, sites across (phones) ---- */
.tall{width:100%;table-layout:fixed}
.tall th.day{position:sticky;left:0;z-index:2;background:var(--bg);
  width:56px;text-align:left;padding:0 6px 0 14px;
  font-family:ui-monospace,"SF Mono",Menlo,monospace;font-weight:400;
  font-size:10.5px;color:var(--dim);
  border-bottom:1px solid var(--line);border-right:1px solid var(--line)}
.tall tr.we th.day{color:var(--ink)}
.tall tr.mrow th{background:var(--bg);text-align:left;
  padding:16px 14px 6px;font-size:10.5px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--dim);
  font-family:ui-monospace,monospace;border:0}
.tall thead th{position:sticky;top:0;background:var(--bg);z-index:3;
  font-family:ui-monospace,monospace;font-weight:400;font-size:11px;
  padding:8px 0 7px;border-bottom:1px solid var(--line)}
.tall thead th a{color:var(--accent);text-decoration:none;
  display:block;padding:2px 0}
.tall tr.we th.day{color:var(--accent)}
.tall thead th.day{z-index:4;color:var(--dim);font-size:9.5px}
.tall td.cell{width:auto}
.key{padding:22px 14px 0;font-size:13px}
.key ol{padding:0;margin:9px 0 0}
.key li{margin:0 0 8px;color:var(--dim);list-style:none;line-height:1.35}
.key b{display:inline-block;min-width:19px;color:var(--accent);
  font-family:ui-monospace,monospace;font-size:11px}
.key a{color:var(--ink);text-decoration:none;
  border-bottom:1px dotted var(--dim)}
.key .wefree{color:var(--freewe)}
.key h2{font-size:11px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--dim);font-family:ui-monospace,monospace;font-weight:400;margin:0}

.tall,.key{display:none}
@media (max-width:760px){
  .wide,.hint{display:none}
  .tall{display:table}
  .key{display:block}
  body{font-size:14px}
  .wrap{overflow:visible}
  header{padding:16px 14px 12px}
  h1{font-size:19px}
}
footer{margin-top:28px;padding:16px;color:var(--dim);font-size:11.5px;
  font-family:ui-monospace,monospace;border-top:1px solid var(--line)}
"""

REFRESH_JS = """
document.getElementById('refresh').addEventListener('click', async function(){
  const b = this, old = b.textContent;
  b.disabled = true; b.textContent = 'Henter\\u2026';
  try { await fetch('/refresh', {method:'POST'}); location.reload(); }
  catch(e){ b.disabled = false; b.textContent = old; alert('Kunne ikke hente data'); }
});
"""

STATUS_JS = """
(function(){
  var cfg = window.__BUILD__ || {};
  var age = document.getElementById('age');
  var box = document.getElementById('status');

  // How old the data is. The page has no schedule behind it, so this is the
  // number that decides whether to trust what you are looking at.
  if (age && cfg.built) {
    var mins = Math.round((Date.now() - new Date(cfg.built)) / 60000);
    var t = mins < 2 ? 'just now'
          : mins < 60 ? mins + ' minutes ago'
          : mins < 120 ? 'an hour ago'
          : mins < 2880 ? Math.round(mins / 60) + ' hours ago'
          : Math.round(mins / 1440) + ' days ago';
    age.textContent = '\\u00b7 ' + t;
    if (mins > 4320) age.className = 'stale';   // older than three days
  }

  if (!cfg.repo || !box) return;
  var api = 'https://api.github.com/repos/' + cfg.repo + '/actions/runs?per_page=1';
  var timer = null, until = 0;

  function show(text, live){
    box.textContent = text;
    box.className = live ? 'live' : '';
  }
  function watch(mins){
    until = Date.now() + mins * 60000;
    if (!timer) timer = setInterval(check, 15000);
  }
  function stop(){
    if (timer) { clearInterval(timer); timer = null; }
  }

  function check(){
    if (timer && Date.now() > until) { stop(); show('', false); return; }
    // Public endpoint, no token: this only ever reads run status on a public
    // repo. Unauthenticated calls are capped at 60/hour per IP, hence the
    // 15s interval and the hard stop above.
    fetch(api, {headers: {Accept: 'application/vnd.github+json'}, cache: 'no-store'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(j){
        var run = j && j.workflow_runs && j.workflow_runs[0];
        if (!run) return;
        if (run.status !== 'completed') {
          show('rebuilding\\u2026', true);
          watch(10);
        } else if (String(run.id) !== String(cfg.run)) {
          // A newer run than the one that built this page has finished, so
          // what we are showing is out of date. Pages needs a moment to
          // serve the new deploy.
          show('updated \\u2014 reloading\\u2026', true);
          stop();
          setTimeout(function(){ location.reload(); }, 3000);
        }
      })
      .catch(function(){ /* offline or rate-limited: say nothing */ });
  }

  var link = document.getElementById('rebuild');
  if (link) link.addEventListener('click', function(){
    show('waiting for the run\\u2026', true);
    watch(10);
  });

  // One call on load, so a rebuild started elsewhere -- the GitHub mobile
  // app, another tab -- is picked up without touching anything here.
  check();
})();
"""

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def short(title):
    """Trim the long official names down for the mobile key."""
    t = title.replace("Kalvebod F\u00e6lled, ", "").replace("Kongelunden, ", "Kongelund. ")
    return t.replace("Pinseskoven, ", "Pinsesk. ").replace("Fasanskoven, ", "Fasansk. ")


def is_weekend_night(d):
    """Friday and Saturday nights -- the ones worth grabbing."""
    return d.weekday() in (4, 5)


def status(p, d, booked, today):
    """free | busy | out (beyond this site's booking window)."""
    if (d - today).days > p.get("window_days", 90):
        return "out"
    return "busy" if d.isoformat() in booked else "free"


def render(ps, avail, fetched_at, serve_mode):
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(DAYS)]
    booked = {p["id"]: set(avail[p["id"]]) for p in ps}
    horizon = today + timedelta(days=min(p.get("window_days", 90) for p in ps))
    link = {p["id"]: f'{BASE}/sted/{p["uri"]}/' for p in ps}

    def cell(p, d):
        st = status(p, d, booked[p["id"]], today)
        we = " we" if is_weekend_night(d) else ""
        tip = f'{esc(p["title"])} \u00b7 {d.isoformat()} \u00b7 {st}'
        return (f'<td class="cell {st}{we}">'
                f'<a href="{link[p["id"]]}" target="_blank" title="{tip}"></a></td>')

    h = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>Shelters on Amager</title><style>', CSS, '</style></head><body>']

    h.append('<header><h1>Shelters on Amager</h1>')
    h.append(f'<div class="sub">{len(ps)} sites \u00b7 fetched {esc(fetched_at)} '
             f'<span id="age"></span> '
             f'\u00b7 shelters bookable to {horizon.isoformat()}</div>')
    h.append('<div class="bar">'
             '<span><span class="sw" style="background:var(--freewe)"></span>'
             'free Fri/Sat</span>'
             '<span><span class="sw" style="background:var(--free)"></span>free</span>'
             '<span><span class="sw" style="background:var(--busy)"></span>booked</span>'
             '<span><span class="sw" style="background:var(--out);'
             'border:1px solid var(--line)"></span>not open yet</span>')
    if serve_mode:
        h.append('<button id="refresh">Refresh</button>')
    elif REPO:
        # A published page is static and cannot scrape anything itself, so
        # "rebuild" means: go and start the workflow. The page then watches
        # for that run to finish and reloads itself.
        h.append(f'<a id="rebuild" target="_blank" rel="noopener" '
                 f'href="https://github.com/{REPO}/actions/workflows/{WORKFLOW}">'
                 f'Rebuild</a><span id="status"></span>')
    h.append('</div></header>')

    # ---------- wide (desktop): sites down, days across ----------
    h.append('<div class="wrap"><table class="wide">')
    strip, i = [], 0
    while i < len(dates):
        m, y = dates[i].month, dates[i].year
        n = sum(1 for d in dates[i:] if d.month == m and d.year == y)
        strip.append((f"{MONTHS[m-1]} {y}", n))
        i += n
    h.append('<tr class="mstrip"><th class="site" style="background:var(--bg)"></th>')
    for label, n in strip:
        h.append(f'<th colspan="{n}">{label}</th>')
    h.append('</tr><thead><tr><th class="site">Site</th>')
    for d in dates:
        we = "we" if is_weekend_night(d) else ""
        h.append(f'<th class="{we}"><b>{d.day}</b>{DOW[d.weekday()][:2]}</th>')
    h.append('</tr></thead><tbody>')

    for p in ps:
        b = booked[p["id"]]
        free = sum(1 for d in dates if status(p, d, b, today) == "free")
        we_free = sum(1 for d in dates
                      if is_weekend_night(d) and status(p, d, b, today) == "free")
        h.append('<tr><th class="site">'
                 f'<a href="{link[p["id"]]}" target="_blank" translate="no">'
                 f'{esc(p["title"])}</a>'
                 f'<small>{esc(p["type"])} \u2014 {free} free, '
                 f'{we_free} on Fri/Sat</small></th>')
        for d in dates:
            h.append(cell(p, d))
        h.append('</tr>')
    h.append('</tbody></table></div>')
    h.append('<div class="hint">Scroll sideways for more days. '
             'Click any square to open that site\u2019s booking page.</div>')

    # ---------- tall (phone): days down, sites across ----------
    h.append('<div class="wrap"><table class="tall"><thead><tr>'
             '<th class="day">day</th>')
    for n, p in enumerate(ps, 1):
        h.append(f'<th><a href="{link[p["id"]]}" target="_blank" '
                 f'title="{esc(p["title"])}">{n}</a></th>')
    h.append('</tr></thead><tbody>')
    seen = None
    for d in dates:
        if (d.year, d.month) != seen:
            seen = (d.year, d.month)
            h.append(f'<tr class="mrow"><th colspan="{len(ps)+1}">'
                     f'{MONTHS[d.month-1]} {d.year}</th></tr>')
        we = " we" if is_weekend_night(d) else ""
        h.append(f'<tr class="{we.strip()}"><th class="day">'
                 f'{d.day} {DOW[d.weekday()]}</th>')
        for p in ps:
            h.append(cell(p, d))
        h.append('</tr>')
    h.append('</tbody></table></div>')

    h.append('<div class="key"><h2>Sites</h2><ol>')
    for n, p in enumerate(ps, 1):
        b = booked[p["id"]]
        free = sum(1 for d in dates if status(p, d, b, today) == "free")
        we_free = sum(1 for d in dates
                      if is_weekend_night(d) and status(p, d, b, today) == "free")
        h.append(f'<li><b>{n}</b> <a href="{link[p["id"]]}" target="_blank" '
                 f'translate="no">{esc(short(p["title"]))}</a> '
                 f'\u2014 {free} free, <span class="wefree">{we_free} Fri/Sat</span></li>')
    h.append('</ol></div>')

    h.append('<footer>Data: book.naturstyrelsen.dk (state land only) \u00b7 '
             '\u201cfree\u201d = not booked in the system \u00b7 '
             'daily-booking sites only.</footer>')
    if serve_mode:
        h.append('<script>' + REFRESH_JS + '</script>')
    else:
        cfg = {"repo": REPO, "run": RUN_ID,
               "built": datetime.now(timezone.utc).isoformat()}
        h.append('<script>window.__BUILD__=' + json.dumps(cfg) + ';'
                 + STATUS_JS + '</script>')
    h.append('</body></html>')
    return "".join(h)


# ---------------------------------------------------------------- modes

def build_static(dest=None):
    ps, avail = scrape()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = render(ps, avail, stamp, serve_mode=False)
    target = Path(dest) if dest else OUT
    if target.suffix != ".html":          # treat a bare name as a directory
        target.mkdir(parents=True, exist_ok=True)
        target = target / "index.html"
    target.write_text(html, encoding="utf-8")
    print("wrote", target)


class State:
    html = None


def serve():
    def refresh():
        ps, avail = scrape()
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        State.html = render(ps, avail, stamp, serve_mode=True)
        OUT.write_text(State.html, encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, body, ctype="text/html; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if State.html is None:
                refresh()
            self.send(State.html)

        def do_POST(self):
            if self.path != "/refresh":
                self.send_response(404)
                self.end_headers()
                return
            print("refreshing...")
            try:
                refresh()
                self.send('{"ok":true}', "application/json")
            except Exception as exc:
                print("refresh failed:", exc, file=sys.stderr)
                self.send_response(500)
                self.end_headers()

    print(f"http://localhost:{PORT}   (ctrl-c to stop)")
    try:
        HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "serve":
        serve()
    else:
        build_static(args[0] if args else None)
