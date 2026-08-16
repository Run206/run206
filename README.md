# Run206

Every race, club run, and shakeout within 40 miles of Seattle — collected
automatically, in one filterable page.

Live at **[run206.com](https://run206.com)**. Deployment and DNS steps are in
[DEPLOY.md](DEPLOY.md).

## How it works

A GitHub Action runs twice a day, rebuilds `public/`, and publishes it to GitHub
Pages. There is no server and no database.

```
GitHub Actions (06:00 + 18:00 Pacific)
  └─ python3 scripts/build.py
       ├─ RunSignUp API      ~190 races within a 40-mile radius of 98101
       ├─ data/clubs.yml     recurrence rules expanded into real dates
       ├─ data/races-manual.yml   races not listed on RunSignUp
       ├─ normalise · dedupe · drop past · tag affiliate links · escape HTML
       └─ public/{index.html, events.json, sitemap.xml, robots.txt, CNAME}
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
| A race not on RunSignUp | `data/races-manual.yml` |
| Hide a bad API race | `data/overrides.yml` (add its `race_id`) |
| Radius, date window, affiliate token | `data/config.yml` |
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

## Money

Race links carry a RunSignUp affiliate token, applied centrally at build time in
`lib/normalize.apply_affiliate` — no link is ever tagged by hand. The token goes
in `data/config.yml`; it is a public tracking parameter, not a secret.

Realistically this pays for the domain. RunSignUp's processing fee is about
6% + $1, so roughly $5.20 on a $70 race, and the affiliate share is 15% of that
— **about $0.78 per registration**.

Note that an affiliate token is *not* the same thing as a `raceRefCode`. A
`raceRefCode` is a per-race referral reward tied to a registrant account and
pays nothing on races whose director hasn't enabled it. `verify.py` fails the
build if a `raceRefCode` reappears in any link.

## Layout

```
data/          content you edit by hand + config
scripts/
  build.py     orchestrator
  verify.py    pre-publish checks
  sources/     one module per data source
  lib/         recurrence, normalisation, rendering, helpers
site/          template, styles, client-side filtering
public/        build output, served by Pages (committed on purpose)
reference/     the original mockups and spreadsheet, kept for reference
```
