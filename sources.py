#!/usr/bin/env python3
"""Fetch and parse Kitchener/Waterloo news sources into plain item dicts.

Every parser is self-contained: a broken source raises, the caller records the
failure and carries on. No third-party libraries - Actions runs this on the
system python3.
"""
import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
BASE = "https://agaruppa.github.io/kw-digest"

LOCAL = ("Kitchener", "Waterloo", "Region", "GRT", "WRPS", "EC")

SOURCES = [
    ("CBC KW", "https://www.cbc.ca/webfeed/rss/rss-canada-kitchenerwaterloo", "rss"),
    ("Global KW", "https://globalnews.ca/kitchener/feed/", "rss"),
    ("Google News", "https://news.google.com/rss/search?q=(Kitchener+OR+%22Waterloo+Region%22+OR+%22Waterloo+Ontario%22)+when:2d&hl=en-CA&gl=CA&ceid=CA:en", "rss"),
    ("Kitchener", "https://www.kitchener.ca/news/rss/", "rss"),
    ("Waterloo", "https://www.waterloo.ca/news/rss/", "rss"),
    ("Region", "https://www.regionofwaterloo.ca/news/rss/", "rss"),
    ("GRT", "https://www.grt.ca/alerts-and-detours/", "grt"),
    ("WRPS", "https://wrps.ca/news/news-release", "wrps"),
]


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)


def clean(text, limit=400):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*(Continue reading|Read more|Read the full story)\s*$", "", text, flags=re.I)
    text = re.sub(r"\s*The post .* appeared first on .*$", "", text, flags=re.I)
    return text[:limit]


def parse_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%A, %B %d, %Y %I:%M %p",
                "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw.replace("a.m.", "AM").replace("p.m.", "PM"), fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def parse_rss(text, source):
    items = []
    root = ET.fromstring(text)
    ns = {"content": "http://purl.org/rss/1.0/modules/content/",
          "dc": "http://purl.org/dc/elements/1.1/"}
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        desc = node.findtext("description") or ""
        enc = node.findtext("content:encoded", default="", namespaces=ns)
        date = parse_date(node.findtext("pubDate") or node.findtext("dc:date", namespaces=ns))
        if not title or not link:
            continue
        items.append({
            "title": clean(title, 200),
            "url": link,
            "summary": clean(enc or desc, 600),
            "source": source,
            "published": date,
        })
    return items


def parse_municipal(text, source):
    """Kitchener / Waterloo / Region share one CMS: gs-feed-list-title + gs-feed-list-date."""
    items = []
    pattern = re.compile(
        r'<a[^>]*class="[^"]*gs-feed-list-title[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
    date_re = re.compile(r'gs-feed-list-date[^>]*>\s*([A-Z][a-z]+ \d{1,2}, \d{4})')
    for m in pattern.finditer(text):
        href, title = m.group(1), clean(m.group(2), 200)
        tail = text[m.end():m.end() + 1200]
        dm = date_re.search(tail)
        items.append({
            "title": title,
            "url": urllib.parse.urljoin("https://" + source.lower() + ".ca/", href) if href.startswith("/") else href,
            "summary": "",
            "source": source,
            "published": parse_date(dm.group(1)) if dm else None,
        })
    return items


def parse_grt(text):
    items, seen = [], set()
    pattern = re.compile(r'href="(/alerts-and-detours/posts/[^"]+)"[^>]*>(.*?)</a>', re.S)
    for m in pattern.finditer(text):
        href, title = m.group(1), clean(m.group(2), 200)
        if not title or href in seen:
            continue
        seen.add(href)
        items.append({"title": title, "url": "https://www.grt.ca" + href, "summary": "",
                      "source": "GRT", "published": None})
    return items


def parse_wrps(text):
    items = []
    pattern = re.compile(
        r'<a[^>]*class="[^"]*mht-card-media__title[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
    date_re = re.compile(r'mht-date[^>]*>\s*([^<]+)<')
    for m in pattern.finditer(text):
        href, title = m.group(1), clean(m.group(2), 200)
        tail = text[m.end():m.end() + 2500]
        dm = date_re.search(tail)
        items.append({"title": title,
                      "url": urllib.parse.urljoin("https://wrps.ca/", href),
                      "summary": "",
                      "source": "WRPS",
                      "published": parse_date(dm.group(1)) if dm else None})
    return items


def parse_weather():
    """Environment Canada alerts inside the Kitchener/Waterloo bounding box."""
    url = ("https://api.weather.gc.ca/collections/weather-alerts/items"
           "?f=json&limit=200&lang=en&bbox=-80.65,43.35,-80.35,43.55")
    data = json.loads(fetch(url))
    items = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        name = props.get("alert_name") or props.get("alert_short_name") or ""
        headline = props.get("headline") or props.get("alert_text") or ""
        if not name:
            continue
        conf = (props.get("confidence") or "").lower()
        items.append({
            "title": clean("%s - %s" % (name.replace("_", " ").title(), headline), 200),
            "url": "https://weather.gc.ca/warnings/index_e.html?prov=on",
            "summary": clean(props.get("alert_text") or headline, 400),
            "source": "EC",
            "published": None,
            "confidence": conf,
        })
    return items


def collect():
    items, status = [], []
    for name, url, kind in SOURCES:
        started = time.time()
        try:
            text = fetch(url)
            if kind == "rss":
                got = parse_rss(text, name)
            elif kind == "municipal":
                got = parse_municipal(text, name)
            elif kind == "grt":
                got = parse_grt(text)
            else:
                got = parse_wrps(text)
            items.extend(got)
            status.append({"source": name, "ok": True, "items": len(got),
                           "ms": int((time.time() - started) * 1000)})
        except Exception as exc:
            status.append({"source": name, "ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
                           "ms": int((time.time() - started) * 1000)})
    try:
        alerts = parse_weather()
        items.extend(alerts)
        status.append({"source": "EC", "ok": True, "items": len(alerts), "ms": 0})
    except Exception as exc:
        status.append({"source": "EC", "ok": False, "error": str(exc)[:120], "ms": 0})
    return items, status


if __name__ == "__main__":
    its, st = collect()
    print(json.dumps(st, ensure_ascii=False, indent=1))
    print("total", len(its))
    for i in its[:5]:
        print("-", i["source"], "|", i["published"], "|", i["title"][:90])
