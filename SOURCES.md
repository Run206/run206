# Where the events come from

Checked August 2026. Re-check before assuming any of this still holds.

| Source | Automated? | Notes |
|---|---|---|
| **RunSignUp** | ✅ Live | Free public API, ~190 races in radius. The bulk of the calendar. |
| **Heylo** (CSRD) | ✅ Live | Clean JSON in `__NEXT_DATA__`, permissive robots.txt. Covers one-off collabs. |
| **clubs.yml** | ✍️ By hand | 34 recurring sessions. Changes rarely. |
| **races-manual.yml** | ✍️ By hand | Races not on RunSignUp (Seattle Marathon, Run Super Series). |
| **REI** | ⚠️ Blocked | Renders events server-side but blocks non-browser clients. See below. |
| **Super Jock 'n Jill** | ❌ No data | `/events` is a landing page with no event listings on it. |
| **Strava** | ❌ Disallowed | `robots.txt` blocks AI crawlers outright; API terms forbid redistribution. |

---

## RunSignUp — automated

Free public races API, no key needed. See the gotchas section in the README —
the geo filter, the date format, and the HTTP-200-with-an-error-body behaviour
all cost real time to discover.

## Heylo — automated

`scripts/sources/heylo.py`. Heylo is a Next.js app that embeds its data in
`__NEXT_DATA__`, so events come out as structured JSON rather than needing HTML
parsing. `heylo.com/robots.txt` has no `Disallow` rules at all.

Even so the client is deliberately polite: one request for the group page, one
per upcoming event, 0.6s apart, and it honours each event's own `isDraft` and
`isVisibleToPublic` flags. Private and draft events are never ingested.

### Why this matters more than it looks

CSRD posts one-off collabs — the New Balance fall marathon festival, the 1 Hotel
morning runs — that a weekly recurrence rule fundamentally cannot express. Those
are the events people actually want to hear about, and they only exist on Heylo.

### Suppression

CSRD's Monday run exists twice: as a weekly rule in `clubs.yml` and, when they
post it, as a dated Heylo event usually renamed for the collab. Name matching
can't reconcile "Monday Miles" with "Monday Night Miles", so suppression works by
**organiser and date**: if a Heylo community has any event on a given day, the
generated placeholders for the clubs it posts for are dropped for that day.

The result, from a real build:

```
Aug 17  heylo   Monday Night Miles                          <- real event wins
Aug 22  heylo   Fall Marathon Festival + Saturday Miles     <- real event wins
Aug 24  manual  Monday Miles                                <- placeholder fills the gap
Aug 29  manual  Saturday Morning Miles                      <- placeholder fills the gap
```

### Adding another club

If a club uses Heylo, add its community ID to `data/config.yml`:

```yaml
sources:
  heylo:
    communities:
      - id: <the uuid from the /g/<uuid> URL>
        org: Their Club Name
        suppresses:
          - Their Club Name    # names as they appear in clubs.yml
```

---

## REI — blocked, and mostly redundant anyway

`rei.com/events/a/fitness-running` does render events server-side, and a browser
sees six Seattle running results. But `curl` gets connection status `000` —
REI's edge blocks non-browser clients outright, and `robots.txt` isn't even
served to them.

Automating it would need a headless browser in CI, which is fragile, slow, and
gets blocked the moment their bot detection is tuned.

It also buys less than it appears. Of those six results, three — Iron Horse
Half, Orca Half, Lake Washington Half — are Orca Running races **already in the
RunSignUp feed**. What's genuinely REI-only is two indoor classes (Trail Running
Basics, Road Running Basics) and the Party Pace run club, which is already in
`clubs.yml`.

**Recommendation:** leave it. Add the two classes by hand if you want them. The
better move is asking REI's Seattle events team to send you their schedule — a
local calendar that drives signups is something they want to exist.

## Super Jock 'n Jill — nothing to automate

`superjocknjill.com/events` has no event listings on it. It's a Squarespace
landing page with three links: "Medical Night", "Fun Group Runs", "Upcoming
Races". No JSON-LD, no event collection, no dates.

Their Squarespace `robots.txt` also explicitly disallows `?format=json` and
`?format=ical`, which are the two endpoints that would otherwise expose event
data on a Squarespace site. So even the usual back door is off-limits.

Their Monday group run is already in `clubs.yml`. Anything more needs a human
relationship, not a scraper — which is the right move regardless, since local
retailers are also your most likely first sponsors.

## Strava — do not scrape

`strava.com/robots.txt`:

```
User-agent: ClaudeBot
User-agent: Google-Extended
User-agent: GPTBot
User-agent: Meta-ExternalAgent
Disallow: /
```

That's explicit and unambiguous. Separately, club group events aren't fully
visible without authentication, and Strava's API Agreement prohibits using their
data to build a competing or aggregating service and requires specific
attribution.

**Recommendation:** don't. Clubs that post to Strava almost always post the same
run somewhere else — their Instagram, Meetup, Heylo, or their own site. Get it
from there, or ask the club to submit it.

---

## The pattern worth noticing

Two of the three sources that can't be automated fail for the same reason: the
data isn't really *published*, it's posted by a person to an audience that
already follows them.

Scraping is the wrong tool for that. A submission form is the right one — it
turns coverage from a technical problem into a community one, and clubs are
generally glad to be listed. See the "What to build next" notes in the README.
