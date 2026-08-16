"""Render index.html, sitemap.xml, robots.txt and CNAME into public/.

Every event is written into the HTML at build time. The page therefore renders
with no JavaScript and no network fetch — app.js only hides rows. That also
means search engines see the full event list in the initial response.
"""

import json
import os
from datetime import date

from lib.util import esc

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

DISTANCE_CHIPS = ["All", "5K", "10K", "Half", "Marathon", "Ultra", "Trail", "Free"]

TAG_CLASS = {"Race": "tag-race", "Club Run": "tag-club", "Brand Event": "tag-brand"}
# Google only surfaces near-term events in rich results, and every extra entry
# is dead weight in the HTML. The soonest 60 is plenty.
JSONLD_LIMIT = 60


def render_site(config, events, today, out_dir, root):
    site = config.get("site", {})
    domain = site.get("domain", "run206.com")

    with open(os.path.join(root, "site", "template.html")) as handle:
        template = handle.read()
    with open(os.path.join(root, "site", "styles.css")) as handle:
        styles = handle.read()
    with open(os.path.join(root, "site", "app.js")) as handle:
        app_js = handle.read()

    replacements = {
        "{{TITLE}}": esc("{} — Seattle running events, all in one place".format(
            site.get("name", "Run206"))),
        "{{DESCRIPTION}}": esc(" ".join((site.get("description") or "").split())),
        "{{TAGLINE}}": esc(site.get("tagline", "")),
        "{{DOMAIN}}": esc(domain),
        "{{STYLES}}": styles,
        "{{APP_JS}}": app_js,
        "{{STATS}}": _stats(events),
        "{{DIST_CHIPS}}": _distance_chips(events),
        "{{LIST}}": _list(events, today),
        "{{JSONLD}}": _jsonld(events, domain),
        "{{UPDATED}}": "Updated {}".format(today.strftime("%-d %B %Y")),
        "{{SUBMIT_URL}}": esc(site.get("submit_url", "mailto:hello@" + domain)),
        "{{YEAR}}": str(today.year),
    }

    html = template
    for token, value in replacements.items():
        html = html.replace(token, value)

    _write(os.path.join(out_dir, "index.html"), html)
    _write(os.path.join(out_dir, "CNAME"), domain + "\n")
    _write(os.path.join(out_dir, "robots.txt"),
           "User-agent: *\nAllow: /\n\nSitemap: https://{}/sitemap.xml\n".format(domain))
    _write(os.path.join(out_dir, "sitemap.xml"),
           '<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           "  <url>\n    <loc>https://{}/</loc>\n    <lastmod>{}</lastmod>\n"
           "    <changefreq>daily</changefreq>\n  </url>\n</urlset>\n"
           .format(domain, today.isoformat()))


def _write(path, content):
    with open(path, "w") as handle:
        handle.write(content)


def _stats(events):
    """Headline counts.

    Recurring runs are counted as distinct sessions, not occurrences — a weekly
    Monday run expanded over 8 weeks is one session, not eight. Counting
    occurrences inflated this to "222 free sessions", which was meaningless.
    """
    races = sum(1 for e in events if e["type"] == "Race")
    clubs = len({e["org"] for e in events
                 if e["type"] in ("Club Run", "Brand Event") and e["org"]})
    sessions = len({(e["name"], e["org"]) for e in events if e["recurring"]})
    return ("<b>{}</b> races &middot; <b>{}</b> weekly runs &middot; "
            "<b>{}</b> clubs &amp; brands").format(races, sessions, clubs)


def _distance_chips(events):
    present = set()
    for event in events:
        present.update(event.get("distance_tags") or [])
    parts = []
    for label in DISTANCE_CHIPS:
        if label not in ("All", "Free") and label not in present:
            continue
        pressed = "true" if label == "All" else "false"
        text = "Any distance" if label == "All" else (
            "Free only" if label == "Free" else label)
        parts.append(
            '<button class="chip" type="button" data-value="{}" aria-pressed="{}">{}</button>'
            .format(esc(label), pressed, esc(text))
        )
    return "\n      ".join(parts)


def _list(events, today):
    """Wrap consecutive same-group events in a <section>.

    Events arrive already sorted by group_order, so a single pass over runs of
    equal group keys is enough.
    """
    chunks = []
    index = 0
    total = len(events)

    while index < total:
        key = (events[index]["group"], events[index]["group_label"])
        rows = []
        while index < total and (events[index]["group"],
                                 events[index]["group_label"]) == key:
            rows.append(_row(events[index], today))
            index += 1
        chunks.append(
            '<section class="group" data-group="{key}">\n'
            '  <h2 class="group-head">{label}'
            '<span class="group-count">{count}</span></h2>\n'
            "{rows}\n</section>".format(
                key=esc(key[0]), label=esc(key[1]), count=len(rows),
                rows="\n".join(rows),
            )
        )
    return "\n".join(chunks)


def _row(event, today):
    tags = ",".join(event.get("distance_tags") or [])

    if event["date"]:
        parsed = date.fromisoformat(event["date"])
        date_html = (
            '<div class="date-dow">{}</div>'
            '<div class="date-day">{}</div>'
            '<div class="date-mon">{}</div>'
        ).format(DOW[parsed.weekday()], parsed.day, MON[parsed.month - 1])
        datetime_attr = ' datetime="{}"'.format(event["date"])
    else:
        date_html = '<div class="date-rep" aria-hidden="true">↻</div>'
        datetime_attr = ""

    # Organiser leads the meta line for club and brand events — "Monday Morning
    # On Track" is meaningless without "Seattle Green Lake Running Group"
    # attached, and since search reads the row's own text, an unrendered field
    # is also an unsearchable one. Races carry no organiser, so nothing shows.
    meta_bits = [b for b in [event["org"], event["distances"],
                             event["location"], event["time"]] if b]
    meta = '<span class="sep">·</span>'.join(
        "<span>{}</span>".format(esc(b)) for b in meta_bits
    )

    badges = ['<span class="tag {}">{}</span>'.format(
        TAG_CLASS.get(event["type"], "tag-race"), esc(event["type"]))]
    if event.get("schedule"):
        badges.append('<span class="tag tag-rep">{}</span>'.format(esc(event["schedule"])))

    title = esc(event["name"])
    if event["url"]:
        title = '<a href="{}" target="_blank" rel="noopener nofollow sponsored">{}</a>'.format(
            esc(event["url"]), title)

    aside = []
    if event["price"]:
        aside.append('<div class="price{}">{}</div>'.format(
            " is-free" if event["free"] else "", esc(event["price"])))
    if event["url"]:
        aside.append('<a class="cta" href="{}" target="_blank" '
                     'rel="noopener nofollow sponsored">{} &rarr;</a>'.format(
                         esc(event["url"]),
                         "Register" if event["type"] == "Race" else "Details"))
    if event.get("affiliate"):
        aside.append('<span class="aff">affiliate</span>')

    desc = ('<div class="desc">{}</div>'.format(esc(event["desc"]))
            if event["desc"] else "")

    # No data-text attribute: the search haystack is derived from the row's own
    # textContent in app.js, which is the same content and saves ~80 KB of
    # duplicated markup across the page.
    return (
        '  <article class="row" data-type="{type}" data-tags="{tags}" '
        'data-free="{free}">\n'
        '    <time class="date"{dt}>{date_html}</time>\n'
        '    <div class="body">\n'
        '      <div class="title-line"><span class="title">{title}</span>{badges}</div>\n'
        '      <div class="meta">{meta}</div>\n'
        "      {desc}\n"
        "    </div>\n"
        '    <div class="aside">{aside}</div>\n'
        "  </article>"
    ).format(
        type=esc(event["type"]), tags=esc(tags), free="1" if event["free"] else "0",
        dt=datetime_attr, date_html=date_html,
        title=title, badges="".join(badges), meta=meta, desc=desc,
        aside="".join(aside),
    )


def _jsonld(events, domain):
    """Emit schema.org Event objects so races can appear as Google rich results.

    Only dated events qualify — startDate is required, and an undated recurring
    club run has nothing valid to put there.
    """
    items = []
    for event in events:
        if not event["date"] or len(items) >= JSONLD_LIMIT:
            continue
        node = {
            "@context": "https://schema.org",
            "@type": "SportsEvent",
            "name": event["name"],
            "startDate": event["date"],
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "eventStatus": "https://schema.org/EventScheduled",
            "location": {
                "@type": "Place",
                "name": event["location"] or "Seattle, WA",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": (event["location"] or "Seattle").split(",")[0].strip(),
                    "addressRegion": "WA",
                    "addressCountry": "US",
                },
            },
        }
        if event["desc"]:
            node["description"] = event["desc"]
        if event["url"]:
            node["url"] = event["url"]
        if event["org"]:
            node["organizer"] = {"@type": "Organization", "name": event["org"]}
        items.append(node)

    if not items:
        return ""
    return '<script type="application/ld+json">{}</script>'.format(
        json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    )
