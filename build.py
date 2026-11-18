#!/usr/bin/env python3
"""Build one hourly Kitchener/Waterloo digest issue: classify, dedupe, publish.

Writes feed.rss + issue pages in site directory, keeps state between runs.
"""
import argparse
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import sources

CATEGORIES = [
    ("alerts", "Предупреждения погоды"),
    ("incidents", "Происшествия и полиция"),
    ("roads", "Дороги, перекрытия, транспорт"),
    ("projects", "Проекты и стройка"),
    ("events", "Мероприятия"),
    ("council", "Совет, бюджет, планирование"),
    ("utilities", "Вода, электричество, вывоз мусора"),
    ("region", "Новости региона"),
]

RULES = [
    ("incidents", r"\b(police|wrps|charged|arrest\w*|collision|crash|assault|theft|fraud|robbery|"
                  r"break[- ]?in|impaired|homicide|shooting|stab\w*|missing (man|woman|person|youth)|"
                  r"fire|blaze|investigat\w*|injur\w*|death|died|fatal|suspect|vandal\w*)\b"),
    ("roads", r"\b(road|street|intersection|lane|detour|closure|closed|construction notice|"
              r"traffic|grt|ion|lrt|bus route|transit|sidewalk|bridge|watermain|water main|paving)\b"),
    ("utilities", r"\b(outage|boil water|advisory|hydro|electricity|garbage|recycling|green bin|"
                  r"waste collection|leaf|collection delay|power)\b"),
    ("council", r"\b(council|committee|budget|zoning|official plan|public meeting|agenda|"
               r"planning application|delegation|by-?law|election|survey)\b"),
    ("projects", r"\b(project|ground[- ]?break\w*|tender|expansion|development|redevelop\w*|"
                r"opens?|opening|completed|construction start|new facility|renovat\w*|retrofit|"
                r"affordable housing|build\w*)\b"),
    ("events", r"\b(event|festival|market|concert|parade|workshop|open house|celebration|"
              r"register\w*|tickets?|free (event|family)|holiday|tree lighting|santa)\b"),
]

MAX_PER_CATEGORY = 6
HISTORY_ISSUES = 48


def norm_url(u):
    u = u.split("#")[0]
    u = re.sub(r"[?&](utm_[^&=]+|fbclid|gclid)=[^&]*", "", u)
    return u.rstrip("?&/")


def tokens(title):
    words = re.findall(r"[a-zа-я0-9]{4,}", title.lower())
    stop = {"with", "from", "that", "this", "will", "your", "have", "been", "after", "over",
            "into", "their", "about", "more", "than", "city", "region", "waterloo"}
    return {w for w in words if w not in stop}


def similar(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    return inter >= 2 and inter / min(len(ta), len(tb)) >= 0.6


LOCALITY = re.compile(
    r"kitchener|waterloo|cambridge|guelph|elmira|wilmot|wellesley|woolwich|"
    r"north dumfries|conestoga|grand river|region of waterloo|wrps|\bgrt\b|\bion\b|\bkw\b", re.I)


ALERTS_RE = re.compile(
    r"\b(warning|watch|advisory|alert|statement|storm|freezing rain|snowfall|"
    r"extreme cold|heat warning|tornado|air quality|flood|fog)\b", re.I)


def is_local(it):
    if it["source"] in sources.LOCAL:
        return True
    return bool(LOCALITY.search(it["title"] + " " + it.get("summary", "")))


def classify(title, summary, source=""):
    text = (title + " " + summary).lower()
    if source == "EC" or (ALERTS_RE.search(title) and re.search(r"warning|watch|advisory|alert|statement", title, re.I)):
        return "alerts"
    for name, pattern in RULES:
        if re.search(pattern, text, re.I):
            return name
    return "region"


def esc(s):
    return html.escape(s or "", quote=True)


def rfc822(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def build_issues(items, state, now):
    seen = state.get("seen", {})
    fresh = []
    window_start = now - timedelta(hours=4)
    for it in items:
        url = norm_url(it["url"])
        if not url or url in seen:
            continue
        pub = it.get("published")
        if pub and pub < window_start:
            seen[url] = now.isoformat()
            continue
        if pub and pub > now + timedelta(minutes=90):
            continue
        if not is_local(it):
            seen[url] = now.isoformat()
            continue
        it["url"] = url
        it["category"] = classify(it["title"], it.get("summary", ""), it["source"])
        fresh.append(it)

    # newest first, dedupe near-identical headlines
    fresh.sort(key=lambda i: i.get("published") or now, reverse=True)
    kept = []
    for it in fresh:
        for k in kept:
            if it["source"] == k["source"] or not similar(it["title"], k["title"]):
                continue
            pa, pb = it.get("published"), k.get("published")
            if pa and pb and abs((pa - pb).total_seconds()) > 4 * 3600:
                continue
            k.setdefault("also", []).append(it["source"])
            seen[norm_url(it["url"])] = now.isoformat()
            break
        else:
            kept.append(it)

    buckets = {}
    for it in kept:
        bucket = buckets.setdefault(it["category"], [])
        if len(bucket) < MAX_PER_CATEGORY:
            bucket.append(it)
        seen[norm_url(it["url"])] = now.isoformat()

    # keep the seen index bounded
    if len(seen) > 6000:
        cut = sorted(seen.items(), key=lambda kv: kv[1])[-4000:]
        seen = dict(cut)
    state["seen"] = seen
    return buckets


CSS = """
:root{color-scheme:light dark}
body{font:16px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
margin:0;padding:20px 16px 48px;max-width:760px;margin-inline:auto;color:#191919;background:#fff}
@media(prefers-color-scheme:dark){body{color:#e8e8e8;background:#141414}a{color:#7fb2ff}}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:26px 0 8px;padding-bottom:6px;
border-bottom:1px solid #8884;text-transform:uppercase;letter-spacing:.04em;color:#666}
@media(prefers-color-scheme:dark){h2{color:#aaa}}
.meta{color:#777;font-size:13px;margin-bottom:18px}
.item{margin:0 0 14px}.item a.t{font-weight:600;text-decoration:none;color:inherit}
.item a.t:hover{text-decoration:underline}.src{color:#777;font-size:12px;margin:2px 0 4px}
.item p{margin:2px 0;color:#444;font-size:14px}
@media(prefers-color-scheme:dark){.item p{color:#bbb}}
footer{margin-top:34px;padding-top:12px;border-top:1px solid #8884;color:#888;font-size:12px}
"""


def render_page(issue, buckets, status):
    parts = []
    for key, label in CATEGORIES:
        rows = buckets.get(key)
        if not rows:
            continue
        parts.append("<h2>%s</h2>" % esc(label))
        for it in rows:
            when = ""
            if it.get("published"):
                when = it["published"].astimezone(timezone.utc).strftime("%H:%M")
            also = ""
            if it.get("also"):
                also = " · also: " + esc(", ".join(sorted(set(it["also"]))))
            summary = it.get("summary") or ""
            parts.append(
                '<div class="item"><a class="t" href="%s">%s</a>'
                '<div class="src">%s%s%s</div>%s</div>' % (
                    esc(it["url"]), esc(it["title"]), esc(it["source"]),
                    (" · " + when) if when else "", also,
                    ('<p>%s</p>' % esc(summary[:300])) if summary else ""))
    bad = [s for s in status if not s["ok"]]
    foot = "Сформировано %s UTC" % issue["time"].strftime("%d.%m.%Y %H:%M")
    if bad:
        foot += " · не ответили: " + esc(", ".join(s["source"] for s in bad))
    return ("<!doctype html><html lang=\"ru\"><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>%s</title><style>%s</style><body><h1>Kitchener / Waterloo</h1>"
            "<div class=\"meta\">Сводка за час · %s</div>%s"
            "<footer>%s</footer></body></html>") % (
                esc(issue["title"]), CSS, issue["time"].strftime("%d.%m.%Y %H:%M UTC"),
                "".join(parts), foot)


def render_feed(history, self_url, site_url):
    items = []
    for h in history:
        items.append(
            "<item><title>%s</title><link>%s</link><guid isPermaLink=\"false\">%s</guid>"
            "<pubDate>%s</pubDate><description>%s</description>"
            "<content:encoded><![CDATA[%s]]></content:encoded></item>" % (
                esc(h["title"]), esc(h["link"]), esc(h["guid"]), h["pubDate"],
                esc(h["description"]), h["content"]))
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<rss version=\"2.0\" xmlns:content=\"http://purl.org/rss/1.0/modules/content/\" "
            "xmlns:atom=\"http://www.w3.org/2005/Atom\"><channel>"
            "<title>KW сводка: Kitchener / Waterloo</title>"
            "<link>%s</link><description>Часовые местные новости Kitchener, Waterloo и региона"
            "</description><language>ru</language>"
            "<atom:link href=\"%s\" rel=\"self\" type=\"application/rss+xml\"/>"
            "%s</channel></rss>") % (esc(site_url), esc(self_url), "\n".join(items))


def prune(site_dir, keep_days=7, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=keep_days)
    d = os.path.join(site_dir, "d")
    if not os.path.isdir(d):
        return 0
    gone = 0
    for name in os.listdir(d):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:-(\d{2}))?\.html$", name)
        if not m:
            continue
        try:
            stamp = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                             int(m.group(4) or 0), tzinfo=timezone.utc)
        except ValueError:
            continue
        if stamp < cutoff:
            os.remove(os.path.join(d, name))
            gone += 1
    return gone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="state")
    ap.add_argument("--out", default=".")
    ap.add_argument("--base", default=sources.BASE)
    ap.add_argument("--force", action="store_true", help="ignore quiet hours")
    ap.add_argument("--keep-days", type=int, default=7, help="issue pages to keep")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        local_hour = now.astimezone(ZoneInfo("America/Toronto")).hour
    except Exception:
        local_hour = (now.hour - 4) % 24
    if not args.force and (local_hour >= 22 or local_hour < 4):
        print("quiet hours (%02d:00 local) - nothing published" % local_hour)
        return 0
    items, status = sources.collect()
    state = load_json(os.path.join(args.state, "state.json"), {})
    buckets = build_issues(items, state, now)

    if not any(buckets.values()):
        save_json(os.path.join(args.state, "state.json"), state)
        gone = prune(args.out, keep_days=args.keep_days, now=now)
        print("no new items - nothing published (pruned %d)" % gone)
        return 0

    issue_id = now.strftime("%Y-%m-%d-%H")
    issue = {"id": issue_id, "time": now,
             "title": "KW сводка: %s UTC" % now.strftime("%d.%m.%Y %H:%M")}
    page = render_page(issue, buckets, status)
    os.makedirs(os.path.join(args.out, "d"), exist_ok=True)
    with open(os.path.join(args.out, "d", issue_id + ".html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page)

    total = sum(len(v) for v in buckets.values())
    heads = []
    for key, label in CATEGORIES:
        if buckets.get(key):
            heads.append("%s: %d" % (label, len(buckets[key])))

    def abs_link(rel):
        return args.base.rstrip("/") + "/" + rel

    entry = {
        "title": "Сводка %s UTC · %d" % (now.strftime("%d.%m %H:%M"), total),
        "link": abs_link("d/%s.html" % issue_id),
        "guid": "kw-digest-" + issue_id,
        "pubDate": rfc822(now),
        "description": "; ".join(heads),
        "content": page.split("<body>", 1)[1].split("<footer>")[0],
    }
    history = load_json(os.path.join(args.state, "feed_items.json"), [])
    history.insert(0, entry)
    save_json(os.path.join(args.state, "feed_items.json"), history[:HISTORY_ISSUES])

    feed = render_feed(history[:HISTORY_ISSUES], abs_link("feed.rss"), abs_link(""))
    with open(os.path.join(args.out, "feed.rss"), "w", encoding="utf-8") as fh:
        fh.write(feed)

    save_json(os.path.join(args.state, "state.json"), state)
    gone = prune(args.out, keep_days=args.keep_days, now=now)
    print("published %s with %d items (%s)" % (issue_id, total, "; ".join(heads)))
    if gone:
        print("pruned %d old issue pages" % gone)
    for s in status:
        if not s["ok"]:
            print("  source failed: %s - %s" % (s["source"], s.get("error", "")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
