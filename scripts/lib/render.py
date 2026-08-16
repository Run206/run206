"""Render index.html, sitemap.xml, robots.txt and CNAME into public/.

Every event is written into the HTML at build time. The page therefore renders
with no JavaScript and no network fetch — app.js only hides rows. That also
means search engines see the full event list in the initial response.
"""

import json
import os
from datetime import date

from lib import ics
from lib.util import esc, slugify

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
        "{{SUBMIT_URL}}": esc(site.get("submit_url") or "mailto:hello@" + domain),
        "{{YEAR}}": str(today.year),
        "{{ANALYTICS}}": _analytics(config),
        "{{NEWSLETTER}}": _newsletter(config),
    }

    html = template
    for token, value in replacements.items():
        html = html.replace(token, value)

    _write(os.path.join(out_dir, "index.html"), html)
    _write(os.path.join(out_dir, "CNAME"), domain + "\n")
    _write(os.path.join(out_dir, "robots.txt"),
           "User-agent: *\nAllow: /\n\nSitemap: https://{}/sitemap.xml\n".format(domain))

    _write_calendars(events, domain, out_dir)
    slugs = _write_event_pages(config, events, today, out_dir, styles)
    _write_map(config, events, today, out_dir, root, styles)
    _write_sitemap(domain, today, slugs, out_dir)


def _write_map(config, events, today, out_dir, root, styles):
    """Render /map/ from the events that carry coordinates."""
    site = config.get("site", {})
    domain = site.get("domain", "run206.com")

    located = [e for e in events if e.get("coords") and e.get("date")]
    # Compact positional rows, not objects: at ~400 events the repeated JSON
    # keys would cost more than the values.
    rows = [[e["name"], e["date"], e["type"], e.get("location", ""),
             e.get("url", ""), e["coords"][0], e["coords"][1],
             e.get("distances", ""), e.get("time", "")] for e in located]

    with open(os.path.join(root, "site", "map.html")) as handle:
        template = handle.read()
    with open(os.path.join(root, "site", "map.js")) as handle:
        map_js = handle.read()
    with open(os.path.join(root, "site", "vendor", "leaflet.js")) as handle:
        leaflet_js = handle.read()
    with open(os.path.join(root, "site", "vendor", "leaflet.css")) as handle:
        leaflet_css = handle.read()

    payload = "var EVENTS=" + json.dumps(rows, ensure_ascii=False,
                                         separators=(",", ":")) + ";\n"

    replacements = {
        "{{TITLE}}": esc("Map of Seattle running events — {}".format(
            site.get("name", "Run206"))),
        "{{DESCRIPTION}}": esc(
            "Every race and club run within 40 miles of Seattle, plotted on a "
            "map and filterable by type and date."),
        "{{DOMAIN}}": esc(domain),
        "{{COUNT}}": str(len(rows)),
        "{{STYLES}}": styles,
        "{{LEAFLET_CSS}}": leaflet_css,
        "{{LEAFLET_JS}}": leaflet_js,
        "{{MAP_JS}}": payload + map_js,
        "{{UPDATED}}": "Updated {}".format(today.strftime("%-d %B %Y")),
        "{{DISCLOSURE}}": esc(
            "Some race links are affiliate links. Run206 earns a small share of "
            "the booking fee at no extra cost to you, and it never affects which "
            "events are listed."),
    }

    html = template
    for token, value in replacements.items():
        html = html.replace(token, value)

    directory = os.path.join(out_dir, "map")
    if not os.path.isdir(directory):
        os.makedirs(directory)
    _write(os.path.join(directory, "index.html"), html)


CAL_FEEDS = [
    ("calendar.ics", None, "Run206 — all Seattle running events"),
    ("races.ics", "Race", "Run206 — Seattle races"),
    ("club-runs.ics", "Club Run", "Run206 — Seattle club runs"),
]


def _write_calendars(events, domain, out_dir):
    for filename, event_type, title in CAL_FEEDS:
        subset = ([e for e in events if e["type"] == event_type]
                  if event_type else events)
        _write(os.path.join(out_dir, filename),
               ics.build(subset, domain, name=title))


def _write_sitemap(domain, today, slugs, out_dir):
    urls = ['  <url>\n    <loc>https://{}/</loc>\n    <lastmod>{}</lastmod>\n'
            "    <changefreq>daily</changefreq>\n    <priority>1.0</priority>\n  </url>"
            .format(domain, today.isoformat())]
    urls.append('  <url>\n    <loc>https://{}/map/</loc>\n    <lastmod>{}</lastmod>\n'
                "    <changefreq>daily</changefreq>\n  </url>".format(domain, today.isoformat()))
    for slug in slugs:
        urls.append(
            '  <url>\n    <loc>https://{}/e/{}/</loc>\n    <lastmod>{}</lastmod>\n'
            "    <changefreq>weekly</changefreq>\n  </url>"
            .format(domain, slug, today.isoformat()))
    _write(os.path.join(out_dir, "sitemap.xml"),
           '<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join(urls) + "\n</urlset>\n")


def _analytics(config):
    """Cloudflare Web Analytics, only if a token is configured.

    This is the one thing that adds a third-party request to the page, so it is
    opt-in and off by default. Cloudflare's is cookie-free, which means no
    consent banner is required — unlike Google Analytics.
    """
    token = ((config.get("analytics") or {}).get("cloudflare_token") or "").strip()
    if not token:
        return ""
    return ('<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
            "data-cf-beacon='{{\"token\": \"%s\"}}'></script>" % esc(token))


def _newsletter(config):
    """Weekly-digest signup form, only if a provider is configured."""
    settings = config.get("newsletter") or {}
    username = (settings.get("buttondown_username") or "").strip()
    if not username:
        return ""
    action = "https://buttondown.email/api/emails/embed-subscribe/" + esc(username)
    return (
        '<div class="prompt prompt-news">\n'
        "  <h2>{}</h2>\n"
        "  <p>{}</p>\n"
        '  <form class="news-form" action="{}" method="post" target="_blank">\n'
        '    <label class="sr-only" for="news-email">Email address</label>\n'
        '    <input id="news-email" type="email" name="email" required '
        'placeholder="you@example.com" autocomplete="email">\n'
        '    <button class="button" type="submit">Subscribe</button>\n'
        "  </form>\n"
        '  <p class="prompt-note">{}</p>\n'
        "</div>"
    ).format(
        esc(settings.get("heading") or "The week ahead, by email"),
        esc(settings.get("blurb") or
            "One email on Thursday with everything worth running that weekend. "
            "No spam, unsubscribe in one click."),
        action,
        esc(settings.get("note") or "Sent weekly. Your address is never shared."),
    )


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


# ---------------------------------------------------------------- event pages

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday"]
MONTHS_FULL = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]

# One page per dated event. Undated recurring runs get no page — there'd be no
# canonical date to rank for, and near-duplicate thin pages hurt more than they
# help.
EVENT_PAGE_LIMIT = 400


def _write_event_pages(config, events, today, out_dir, styles):
    """Write /e/<slug>/index.html for each dated event.

    These exist for the long tail: nobody searches "Run206", they search
    "seattle half marathon october". The homepage can't rank for every one of
    those, but a page per event can.
    """
    site = config.get("site", {})
    domain = site.get("domain", "run206.com")

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "site", "event.html")) as handle:
        template = handle.read()

    dated = [e for e in events if e.get("date")][:EVENT_PAGE_LIMIT]
    by_month = {}
    for event in dated:
        by_month.setdefault(event["date"][:7], []).append(event)

    slugs = []
    for event in dated:
        slug = event["id"]
        directory = os.path.join(out_dir, "e", slug)
        if not os.path.isdir(directory):
            os.makedirs(directory)

        html = template
        for token, value in _event_replacements(
                event, by_month, domain, today, styles).items():
            html = html.replace(token, value)
        _write(os.path.join(directory, "index.html"), html)
        slugs.append(slug)

    _prune_event_pages(out_dir, set(slugs))
    return slugs


def _prune_event_pages(out_dir, current):
    """Delete pages for events that no longer exist.

    public/ is committed, so without this every past or withdrawn event leaves
    a page behind forever — still reachable, still crawlable, still ranking for
    a race that isn't happening.
    """
    directory = os.path.join(out_dir, "e")
    if not os.path.isdir(directory):
        return

    removed = 0
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if not os.path.isdir(path) or name in current:
            continue
        page = os.path.join(path, "index.html")
        if os.path.exists(page):
            os.remove(page)
        try:
            os.rmdir(path)
            removed += 1
        except OSError:
            pass   # something unexpected inside; leave it alone

    if removed:
        print("  pruned {} stale event page(s)".format(removed))


def _event_replacements(event, by_month, domain, today, styles):
    parsed = date.fromisoformat(event["date"])
    when = "{}, {} {} {}".format(
        WEEKDAYS[parsed.weekday()], parsed.day,
        MONTHS_FULL[parsed.month - 1], parsed.year)
    if event.get("time"):
        when += " at " + event["time"]

    title = "{} — {} {} {}, Seattle running".format(
        event["name"], parsed.day, MONTHS_FULL[parsed.month - 1], parsed.year)

    summary = event.get("desc") or "{} in {}.".format(
        event["name"], event.get("location") or "the Seattle area")
    description = "{} {}. {}".format(event["name"], when, summary)[:300]

    facts = []
    for label, value in [
        ("Date", when),
        ("Location", event.get("location")),
        ("Distances", event.get("distances")),
        ("Organiser", event.get("org")),
        ("Price", event.get("price")),
        ("Type", event.get("type")),
    ]:
        if value:
            facts.append("<dt>{}</dt><dd>{}</dd>".format(esc(label), esc(value)))

    body = ('<p class="detail-body">{}</p>'.format(esc(event["desc"]))
            if event.get("desc") else "")

    if event.get("url"):
        label = "Register" if event["type"] == "Race" else "Event details"
        cta = ('<p class="detail-cta"><a class="button" href="{}" target="_blank" '
               'rel="noopener nofollow sponsored">{} &rarr;</a>{}</p>').format(
                   esc(event["url"]), esc(label),
                   ' <span class="aff">affiliate link</span>'
                   if event.get("affiliate") else "")
    else:
        cta = ""

    if event.get("affiliate"):
        disclosure = ("This page contains an affiliate link. If you register "
                      "through it, Run206 earns a small share of the booking fee "
                      "at no extra cost to you.")
    else:
        disclosure = ("Run206 earns nothing from this listing — it's here "
                      "because it's a Seattle running event.")

    return {
        "{{TITLE}}": esc(title),
        "{{DESCRIPTION}}": esc(" ".join(description.split())),
        "{{DOMAIN}}": esc(domain),
        "{{SLUG}}": esc(event["id"]),
        "{{STYLES}}": styles,
        "{{NAME}}": esc(event["name"]),
        "{{WHEN}}": esc(when),
        "{{TYPE}}": esc(event.get("type", "Race")),
        "{{FACTS}}": "\n    ".join(facts),
        "{{BODY}}": body,
        "{{CTA}}": cta,
        "{{DISCLOSURE}}": esc(disclosure),
        "{{RELATED}}": _related(event, by_month, parsed),
        "{{UPDATED}}": "Updated {}".format(today.strftime("%-d %B %Y")),
        "{{JSONLD}}": _event_jsonld(event, domain),
    }


def _related(event, by_month, parsed):
    """Internal links to other events that month.

    Cheap and genuinely useful: it gives crawlers a path to every event page
    and gives a reader the obvious next question — what else is on around then.
    """
    siblings = [e for e in by_month.get(event["date"][:7], [])
                if e["id"] != event["id"]][:8]
    if not siblings:
        return ""

    items = "\n".join(
        '    <li><a href="/e/{}/">{}</a> <span>{}</span></li>'.format(
            esc(e["id"]), esc(e["name"]),
            esc("{} {}".format(date.fromisoformat(e["date"]).day,
                               MON[date.fromisoformat(e["date"]).month - 1])))
        for e in siblings)
    return ('<section class="related">\n'
            '  <h2>Also in {} {}</h2>\n  <ul>\n{}\n  </ul>\n</section>'.format(
                MONTHS_FULL[parsed.month - 1], parsed.year, items))


def _event_jsonld(event, domain):
    node = {
        "@context": "https://schema.org",
        "@type": "SportsEvent",
        "name": event["name"],
        "startDate": event["date"],
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "eventStatus": "https://schema.org/EventScheduled",
        "url": "https://{}/e/{}/".format(domain, event["id"]),
        "location": {
            "@type": "Place",
            "name": event.get("location") or "Seattle, WA",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": (event.get("location") or "Seattle").split(",")[0].strip(),
                "addressRegion": "WA",
                "addressCountry": "US",
            },
        },
    }
    if event.get("desc"):
        node["description"] = event["desc"]
    if event.get("org"):
        node["organizer"] = {"@type": "Organization", "name": event["org"]}
    if event.get("url"):
        node["offers"] = {
            "@type": "Offer",
            "url": event["url"],
            "availability": "https://schema.org/InStock",
        }
    return '<script type="application/ld+json">{}</script>'.format(
        json.dumps(node, ensure_ascii=False, separators=(",", ":")))
