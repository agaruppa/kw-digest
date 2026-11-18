# kw-digest

Hourly local news digest for Kitchener / Waterloo, Ontario.

- Feed: https://agaruppa.github.io/kw-digest/feed.rss
- Pages: `index.html` (latest issue), `d/YYYY-MM-DD-HH.html` (one per issue)

## Sources

| Source | What it gives | How |
|---|---|---|
| CBC Kitchener-Waterloo | regional news | RSS |
| Global News Kitchener | regional news | RSS |
| City of Kitchener | council, projects, service notices | RSS |
| City of Waterloo | council, projects, service notices | RSS |
| Region of Waterloo | regional projects, notices | RSS |
| GRT | alerts, detours, closures | HTML list |
| WRPS | police releases (short) | HTML list |
| Google News | local outlets incl. The Record, CTV, KitchenerToday | RSS query |
| Environment Canada | weather alerts in KW bbox | api.weather.gc.ca JSON |

## Rules

- Quiet hours: no issues between 22:00 and 04:00 America/Toronto.
- No new material - no issue (an empty hourly feed is noise).
- Non-municipal items must mention Kitchener/Waterloo/region, otherwise dropped (wire copy).
- Near-identical headlines are merged; the first source shown, others listed as "also".
- Item text is a short quote plus a link; paywalled pages are not fetched.
- English source text on purpose: the reader's app translates on the fly.

## Local run

    python3 build.py --force --out /tmp/out

State lives in `state/state.json` (seen URLs) and `state/feed_items.json`
(feed history, last 48 issues).
