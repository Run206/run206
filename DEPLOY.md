# Deploying Run206

One-time setup. About 40 minutes, most of it waiting for DNS.

Do these in order — step 4 depends on the repo existing, and step 5 depends on
DNS having propagated.

---

## 1. Sign up for the RunSignUp affiliate programme

Do this first, because approval can take a day or two and everything else works
without it.

1. Go to **[runsignup.com/affiliate](https://runsignup.com/affiliate)** and apply.
   The programme is explicitly aimed at race directories, which is what this is.
2. When approved you get an **affiliate token** and an API key.
3. Put the token in `data/config.yml`:

   ```yaml
   affiliate:
     runsignup_token: "your-token-here"
   ```

4. Rebuild and confirm it took:

   ```bash
   python3 scripts/build.py && python3 scripts/verify.py
   ```

   The "no affiliate token configured" warning should disappear. Until then the
   site works fine, the links just earn nothing.

> The old `raceRefCode=wc7B47h8…` pasted onto every race URL in the original
> spreadsheet is **not** an affiliate code — it's a per-race referral reward tied
> to a registrant account, and it pays nothing on races whose director hasn't
> enabled it. `verify.py` now fails the build if one reappears.

---

## 2. Create the GitHub repository

The repo must be **public** — GitHub Pages on a private repo requires a paid
plan.

```bash
cd ~/Projects/run206
git add -A
git commit -m "Run206: auto-updating Seattle running events aggregator"
```

Create an empty repo named `run206` at
[github.com/new](https://github.com/new) (public, no README, no .gitignore),
then:

```bash
git remote add origin https://github.com/YOUR-USERNAME/run206.git
git branch -M main
git push -u origin main
```

---

## 3. Turn on GitHub Pages

1. Repo → **Settings** → **Pages**
2. **Source**: select **GitHub Actions** (not "Deploy from a branch")
3. Repo → **Settings** → **Actions** → **General** → under *Workflow
   permissions* select **Read and write permissions**, and save

   The build commits refreshed data back to the repo, so it needs write access.

4. Repo → **Actions** → **Build and deploy** → **Run workflow**

The first run takes a couple of minutes. When it's green, the site is live at
`https://YOUR-USERNAME.github.io/run206/`. Check it before touching DNS.

---

## 4. Point run206.com at GitHub

You already own `run206.com` — it was registered on 11 April 2026 through
Squarespace Domains and is currently showing a Squarespace "Coming Soon" page.
No purchase is needed; it just needs repointing.

### 4a. Disconnect the parking page

In [account.squarespace.com](https://account.squarespace.com) → **Domains** →
`run206.com`, make sure the domain is **not** connected to a Squarespace site or
parking page. While it is, Squarespace overrides the DNS records below.

### 4b. Replace the DNS records

Still in the Squarespace domain panel, open **DNS Settings** and set:

| Type | Host | Value |
|---|---|---|
| A | `@` | `185.199.108.153` |
| A | `@` | `185.199.109.153` |
| A | `@` | `185.199.110.153` |
| A | `@` | `185.199.111.153` |
| AAAA | `@` | `2606:50c0:8000::153` |
| AAAA | `@` | `2606:50c0:8001::153` |
| AAAA | `@` | `2606:50c0:8002::153` |
| AAAA | `@` | `2606:50c0:8003::153` |
| CNAME | `www` | `YOUR-USERNAME.github.io` |

Delete any pre-existing A, AAAA, or CNAME records for `@` and `www` that point
at Squarespace. Leave MX and TXT records alone.

The AAAA records are optional but worth adding — without them the site is
unreachable on IPv6-only mobile networks.

### 4c. Tell GitHub about the domain

Repo → **Settings** → **Pages** → **Custom domain** → enter `run206.com` → Save.

`public/CNAME` already contains the domain, so this should verify quickly.

### 4d. Wait, then enforce HTTPS

DNS usually propagates in 10–30 minutes. Check:

```bash
dig +short run206.com
```

You want the four `185.199.*` addresses. Once they appear, go back to
**Settings → Pages** and tick **Enforce HTTPS**. The certificate is issued
automatically and can take another few minutes.

---

## 5. Verify it's actually working

```bash
curl -sI https://run206.com | head -3
curl -s https://run206.com/robots.txt
curl -s https://run206.com/events.json | head -c 200
```

Then in a browser:

- The event list renders and the filters work
- `run206.com/?type=race&d=half` loads with those filters already applied
- The dark mode toggle persists across a reload
- Paste the URL into the
  [Rich Results Test](https://search.google.com/test/rich-results) — it should
  detect events

**Confirm the affiliate link actually tracks.** This is the only real proof:
click a race link from the live site, go through to the RunSignUp registration
page, and check that the click shows up in your affiliate dashboard. A token
that's present in the HTML but not registering is the failure mode to catch.

Finally, submit the sitemap in
[Google Search Console](https://search.google.com/search-console) so races start
getting indexed.

---

## Running it from here

Nothing needs doing day to day. The site refreshes at 06:00 and 18:00 Pacific.

- **A race is wrong or shouldn't be listed** → add its `race_id` to
  `data/overrides.yml`, push.
- **A club changed its schedule** → edit `data/clubs.yml`, push.
- **A build failed** → the workflow opens a GitHub issue and the live site keeps
  showing the last good data. Nothing breaks in public.

If `verify.py` fails, nothing is published — that's deliberate. The most likely
causes are a malformed hand-edit in `data/`, or RunSignUp changing their API
response shape.
