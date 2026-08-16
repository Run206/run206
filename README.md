# Run206

Every race, club run, and shakeout within 40 miles of Seattle — collected
automatically, in one filterable page.

Live at **[run206.com](https://run206.com)**. Deployment and DNS steps are in
[DEPLOY.md](DEPLOY.md); what's still outstanding is in
[NEXT-STEPS.md](NEXT-STEPS.md).

## How it works

A GitHub Action runs twice a day, rebuilds `public/`, and publishes it to GitHub
Pages. There is no server and no database.

```
GitHub Actions (06:00 + 18:00 Pacific)
  └─ python3 scripts/build.py
       ├─ RunSignUp API      ~190 races within a 40-mile radius of 98101
       ├─ Race Roster        local events found via their published sitemap
       ├─ Heylo              CSRD's posted events, incl. brand collabs
       ├─ data/clubs.yml     recurrence rules expanded into real dates
       ├─ data/races-manual.yml   races on neither platform
       ├─ normalise · dedupe · drop past · tag affiliate links · escape HTML
       ├─ geocode (cached)   coordinates for the map
       └─ public/
            index.html          the list
            e/<slug>/           one page per event, for search
            map/                filterable map
            calendar.ics        subscribable feed (+ races.ics, club-runs.ics)
            events.json         raw data
            sitemap.xml, robots.txt, CNAME
  └─ python3 scripts/verify.py     refuses to publish a broken build
  └─ actions/deploy-pages
```

Every event is written into `index.html` at build time, so the page renders with
no JavaScript and fetches nothing at load. `app.js` only hides rows when you
filter. The whole page is ~48 KB gzipped with zero third-party requests.

## Working on it locally

Requires Python 3.8+ and PyYAML (`pip install pyyaml`). Nothing else.

```bash
python3 scripts/build.py            # fetch live data and rebuild
python3 scripts/build.py --offline  # rebuild templates using cached race data
python3 scripts/verify.py           # run the pre-publish checks
python3 -m http.server 4206 --directory public
```

`--offline` is the one to use when iterating on HTML or CSS — it skips the API
call and reuses the races already in `public/events.json`.

## Editing content

| To change | Edit |
|---|---|
| A club or brand run | `data/clubs.yml` |
| Add a Heylo club | `data/config.yml` under `sources.heylo` |
| A race not on RunSignUp | `data/races-manual.yml` |
| Hide a bad API race | `data/overrides.yml` (add its `race_id`) |
| Radius, date window, affiliate tokens | `data/config.yml` |
| Page copy, layout, styling | `site/template.html`, `site/styles.css` |

Push to `main` and the site rebuilds and redeploys.

### Club run schedules

`data/clubs.yml` entries come in two shapes:

```yaml
- name: Monday Miles
  cadence: weekly          # expanded into real dates for the next 8 weeks
  days: [monday]
  time: "18:30"
```

```yaml
- name: Sunday Trail Run
  cadence: irregular       # no dates invented
  schedule: Twice a month on Sundays, 9-10 AM
```

Only `weekly` entries get concrete dates. Anything biweekly, monthly, or vague
stays in the "Ongoing & irregular" group with its schedule text shown as-is.
Guessing which Sunday a twice-monthly run lands on would send people to a park
on the wrong day, which is worse than showing no date at all.

Which sources can and can't be automated — and why REI, Super Jock 'n Jill
and Strava are *not* scraped — is documented in [SOURCES.md](SOURCES.md).

## Things worth knowing about the RunSignUp API

These cost time to discover, so they're documented rather than rediscovered:

- **`zipcode` + `radius` is the only geo filter that works.** Passing
  `latitude`/`longitude` is silently ignored and returns nationwide results.
- **Dates must be ISO (`YYYY-MM-DD`)**, despite the published docs saying
  `MM/DD/YYYY`. The documented format is rejected with `error_code 3`.
- **Errors come back as HTTP 200** with an `error` key in the body. Code that
  only checks the status code sees an empty race list and cheerfully publishes
  an empty site. `lib/util.get_json` raises on this.
- **The per-event `distance` field is unreliable** — it reports a 10K as
  "7.5 Miles" and leaves Half Marathon `null`. Distances are parsed out of event
  *names* instead, in `lib/normalize.summarize_distances`.
- **Prices live in `registration_periods`**, not `registration_fee`.

## Submissions

The footer links to a GitHub issue form. A submission is parsed by
`scripts/submission.py`, validated (required fields, plain-http links, no markup,
no duplicates), and opened as a pull request against `data/clubs.yml`. Nothing
reaches the site without review.

Point `site.submit_url` in `data/config.yml` at:
`https://github.com/<you>/run206/issues/new?template=submit-event.yml`

## Calendar feeds

`/calendar.ics`, `/races.ics` and `/club-runs.ics`. UIDs are stable across
rebuilds, so a subscriber's calendar updates in place instead of accumulating
duplicates. `verify.py` checks the folding, block balance and UID uniqueness,
because a malformed `.ics` fails silently in calendar apps.

## Money

Outbound links are tagged per platform by `lib/normalize.apply_affiliate`, driven
by the `affiliate.platforms` list in `data/config.yml` — no link is ever tagged
by hand, and adding a partner is configuration rather than code. Tokens are
public tracking parameters, not secrets.

A link is only labelled "affiliate" on the page when it actually carries a tag,
so the disclosure never over-claims.

Realistically this pays for the domain. RunSignUp's processing fee is about
6% + $1, so roughly $5.20 on a $70 race, and the affiliate share is 15% of that
— **about $0.78 per registration**.

Note that an affiliate token is *not* the same thing as a `raceRefCode`. A
`raceRefCode` is a per-race referral reward tied to a registrant account and
pays nothing on races whose director hasn't enabled it. `verify.py` fails the
build if a `raceRefCode` reappears in any link.

## Layout

```
data/            content you edit by hand + config + caches
scripts/
  build.py       orchestrator
  verify.py      pre-publish checks
  digest.py      weekly newsletter, as markdown and paste-ready HTML
  linkcheck.py   dead-link check over hand-maintained URLs only
  submission.py  issue form -> validated clubs.yml entry
  sources/       one module per data source
  lib/           recurrence, normalisation, rendering, ics, geocoding, helpers
site/            templates, styles, client-side filtering, vendored Leaflet
public/          build output, served by Pages (committed on purpose)
reference/       the original mockups and spreadsheet, kept for reference
```

## Scheduled work

| When | Workflow | What happens |
|---|---|---|
| 06:00 + 18:00 PT | `build.yml` | Refresh all sources, verify, deploy. A failure opens an issue and leaves the last good site up. |
| Thursday 07:00 PT | `weekly.yml` | Write the digest, open it as a draft issue, report dead links. |
| On submission | `submission.yml` | Validate an issue-form submission and open a PR. |
