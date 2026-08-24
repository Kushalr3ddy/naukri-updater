# naukri-updater

Keeps a Naukri profile marked as recently updated. Each run appends a `.` to the resume headline; the next
run strips it again. The text ends up where it started, but the profile's "last updated" date moves every
time — which is what recruiter search filters key off.

Runs twice a day, morning and night.

## How it works

```
cookies.pkl ──restore──► profile page ──logged in?──yes──► toggle headline ──verify──► re-save cookies
                              │                 │
                              │                 no
                              │                 ▼
                              └────────── password login from .env ─┘
```

Session handling is pickle-based with a password login as the fallback. A dead or missing `cookies.pkl` is
not an error — that run just takes the login path and writes a fresh one.

## Setup

```bash
venv/bin/pip install -r requirements.txt
cp .env.example .env    # fill in NAUKRI_EMAIL / NAUKRI_PASSWORD
chmod 600 .env
```

Chrome must be installed. The driver is resolved by Selenium Manager — nothing to download or keep in sync.

## Running it

```bash
venv/bin/python main.py             # headless, the scheduled path
venv/bin/python main.py --headful   # same, visible browser
venv/bin/python main.py --discover  # dump the live headline DOM, change nothing
venv/bin/python main.py --reset-base
```

### Docker

```bash
docker compose run --rm naukri-updater
```

The container is one-shot: it runs the toggle and exits, so schedule it from outside. It ships its own
Chromium and driver from apt, so it needs no network access to resolve a driver at run time. The named
volume at `/data` holds `cookies.pkl` and `state.json` between runs — without it every run does a fresh
password login, which is a noisier pattern than reusing a session.

## Scheduling

Pick one.

**systemd user timer, native** — morning and night, with a randomised delay so it never fires at the same
second twice:

```bash
cp systemd/naukri-updater.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now naukri-updater.timer
loginctl enable-linger "$USER"     # so it fires when you are not logged in
```

**systemd user timer, containerised** — same timer, but pointed at the compose service:

```bash
cp systemd/naukri-updater-docker.service ~/.config/systemd/user/naukri-updater.service
cp systemd/naukri-updater.timer ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now naukri-updater.timer
```

Check either with:

```bash
systemctl --user list-timers naukri-updater.timer
journalctl --user -u naukri-updater -n 50
```

**GitHub Actions** — `.github/workflows/naukri.yml`, free, no machine of your own to keep running. Set
`NAUKRI_EMAIL` and `NAUKRI_PASSWORD` as repository secrets. Worth knowing before you rely on it:

- Naukri runs Akamai Bot Manager (the `ak_bmsc` / `bm_sv` cookies). CI runners have datacenter IPs that
  rotate every run, which is a far more challengeable pattern than a residential IP. This may work fine or
  may start hitting challenges; the failure artifacts will tell you which.
- The session token is not cached, so every run logs in fresh — more login events from more IPs.
- GitHub delays scheduled runs under load and disables schedules entirely after 60 days of repo inactivity.
- **Keep the repo private.** Credentials are secrets, and failure artifacts capture a logged-in page.

The local paths are the safer bet; Actions is the convenient one.

## State, and why the toggle needs it

`state.json` holds the canonical headline:

```json
{"base": "Data Engineer ... eJPT Certifications.", "last_applied": "Data Engineer ... eJPT Certifications.."}
```

The direction is derived from what is actually on the page, not from a stored flag, so a failed save cannot
desync anything — the next run reads reality and continues.

This matters more than it sounds. The current headline **legitimately ends in a period**, so a naive
"ends with `.`? strip it" would have eaten real punctuation on the first run. Storing the base keeps it:
the toggle runs between `...Certifications.` and `...Certifications..`.

Edit the headline by hand and the script notices the live text matches neither variant, adopts it as the new
base, and logs a warning. Nothing to reset. `--reset-base` forces the same re-capture.

**If state is lost** (fresh container with no volume, CI with no cache) the toggle still works: it strips a
doubled marker if it sees one and appends otherwise, so it oscillates between one and two trailing dots and
never grows without bound. Every run still changes the text, which is the whole point.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `headline card: none of N locators matched` | Naukri changed its markup. Run `--discover` and update `naukri/selectors.py`. |
| `headline card never rendered` | The card is React-mounted lazily; the page was slower than the 20s wait. |
| `still on the login page after submitting` | Wrong password, or an OTP/captcha challenge. See the screenshot in `artifacts/`. |
| Works `--headful`, fails headless | Usually a bot challenge. Check the artifact screenshot. |
| apt `Hash Sum mismatch` building the image | An intercepting HTTP proxy serving a stale `.deb`. The Dockerfile pins sources to HTTPS to avoid this. |
| Timer never fires | `loginctl enable-linger` not set, or `WorkingDirectory` in the unit doesn't match the repo location. |

Failures write a screenshot, the page HTML and the URL into `artifacts/<timestamp>-<label>/`.

Logs go to stdout (journald captures them under systemd) and to `logs/naukri.log`, rotated at 512 KB.
Passwords and cookie values are never logged.

## Selectors

Confirmed against the live page, not guessed:

| What | Locator |
|---|---|
| Headline card | `#lazyResumeHead` |
| Edit control | `span.edit.icon` |
| Textarea | `#resumeHeadlineTxt` (`maxlength=250`) |
| Save | `form[name='resumeHeadlineForm'] button[type='submit']` |
| Cancel | `form[name='resumeHeadlineForm'] a.cancel-btn` |

Two traps encoded in `naukri/selectors.py`: the profile page carries a second *visible* `button[type=submit]`
("Become a Pro"), so the save locator is scoped to the form; and the login page's fallbacks are anchored to
the placeholder, because "any text input" matches the collapsed nav search box, which is present but not
interactable.

## A note on this being automated

Automating profile updates isn't something Naukri's terms contemplate. The realistic downside is an account
flag, not anything legal. Twice a day with a normal browser fingerprint looks like someone tidying their
headline; hammering it hourly, or from a dozen datacenter IPs, is what would stand out.
