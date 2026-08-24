# naukri-updater

Appends a `.` to the Naukri resume headline, and strips it again next run. The text ends where it
started; the profile's "last updated" date moves every run, which is what recruiter search filters
key off.

## Setup

```bash
cp .env.example .env    # fill in NAUKRI_EMAIL / NAUKRI_PASSWORD
chmod 600 .env
```

## Run

Locally:

```bash
venv/bin/pip install -r requirements.txt && venv/bin/python naukri.py
```

Docker:

```bash
docker compose run --rm naukri-updater
```

`HEADLESS=0` shows the browser if you want to watch it.

## Schedule (twice a day)

The container is one-shot — schedule it from outside. Host crontab:

```bash
30 9,21 * * * docker compose run --rm naukri-updater >> /tmp/naukri.log 2>&1
```

## State

The `/data` volume holds `cookies.pkl` (so it isn't logging in every run) and `state.json`, which
stores your real headline. That matters here: yours genuinely ends in a period, and without it a
blind strip-or-append would eat your punctuation. Losing the volume is survivable — the script falls
back to toggling between one and two trailing dots.

## When it breaks

Naukri ships markup changes without warning. The four selectors are at the top of `naukri.py`:
`lazyResumeHead` (the card, lazy-rendered so it's waited for), `span.edit`, `resumeHeadlineTxt`, and
the save button scoped to `form[name='resumeHeadlineForm']` — that scope is deliberate, the page has
another visible submit button ("Become a Pro").

On a failed save it writes `failure.png` to the data dir. Naukri runs Akamai Bot Manager, so if it
ever works locally but fails from a hosted runner, that screenshot is where the challenge shows up.

## Note

Automating this isn't something Naukri's terms contemplate; the realistic downside is an account
flag. Twice a day looks like someone editing their headline morning and night.
