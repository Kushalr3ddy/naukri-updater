#!/usr/bin/env python3
"""Toggle a '.' on the Naukri resume headline so the profile reads as updated today."""

import json
import os
import pickle
import sys
from pathlib import Path

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DATA = Path(os.getenv("DATA_DIR") or ROOT)
COOKIES = DATA / "cookies.pkl"
STATE = DATA / "state.json"
MARKER = os.getenv("MARKER", ".")
HEADLESS = os.getenv("HEADLESS", "1") not in ("0", "false", "no")

PROFILE = "https://www.naukri.com/mnjuser/profile"
LOGIN = "https://www.naukri.com/nlogin/login"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")

# Scoped to the edit form on purpose: the page has another visible
# button[type=submit] ("Become a Pro") that a page-wide match would hit.
FORM = "form[name='resumeHeadlineForm']"


def log(msg):
    print(msg, flush=True)


def build_driver():
    o = Options()
    if HEADLESS:
        o.add_argument("--headless=new")
    # Headless defaults to 800x600, where Naukri serves a different mobile DOM.
    o.add_argument("--window-size=1920,1080")
    o.add_argument("--disable-blink-features=AutomationControlled")
    o.add_argument("--disable-dev-shm-usage")
    o.add_argument(f"--user-agent={UA}")
    o.add_experimental_option("excludeSwitches", ["enable-automation"])
    if os.getenv("NO_SANDBOX"):
        o.add_argument("--no-sandbox")
    if os.getenv("CHROME_BINARY"):
        o.binary_location = os.environ["CHROME_BINARY"]
    drv = os.getenv("CHROMEDRIVER")
    return webdriver.Chrome(options=o, service=Service(drv) if drv else Service())


def load_cookies(d):
    if not COOKIES.exists():
        return
    try:
        jar = pickle.load(COOKIES.open("rb"))
    except Exception:
        return
    d.get("https://www.naukri.com/")  # add_cookie only works on the target domain
    for c in jar:
        c.pop("sameSite", None)
        if isinstance(c.get("expiry"), float):
            c["expiry"] = int(c["expiry"])
        try:
            d.add_cookie(c)
        except Exception:
            pass


def login(d):
    email, pw = os.getenv("NAUKRI_EMAIL"), os.getenv("NAUKRI_PASSWORD")
    if not email or not pw:
        sys.exit("set NAUKRI_EMAIL and NAUKRI_PASSWORD in .env")
    log(f"logging in as {email}")
    d.get(LOGIN)
    wait = WebDriverWait(d, 20)
    # visibility matters: the collapsed nav search box is also a text input
    wait.until(EC.visibility_of_element_located((By.ID, "usernameField"))).send_keys(email)
    d.find_element(By.ID, "passwordField").send_keys(pw)
    # match by text so we never hit "Use OTP to Login"
    d.find_element(By.XPATH, '//button[@type="submit"][normalize-space()="Login"]').click()
    wait.until(lambda x: "/nlogin/" not in x.current_url)
    pickle.dump(d.get_cookies(), COOKIES.open("wb"))


def open_editor(d):
    """Returns the headline textarea. The card is lazy-rendered, so wait for it."""
    wait = WebDriverWait(d, 20)
    card = wait.until(EC.presence_of_element_located((By.ID, "lazyResumeHead")))
    card.find_element(By.CSS_SELECTOR, "span.edit").click()
    return wait.until(EC.visibility_of_element_located((By.ID, "resumeHeadlineTxt")))


def main():
    d = build_driver()
    try:
        load_cookies(d)
        d.get(PROFILE)
        try:
            WebDriverWait(d, 10).until(EC.presence_of_element_located((By.ID, "lazyResumeHead")))
        except Exception:
            login(d)
            d.get(PROFILE)

        ta = open_editor(d)
        current = (ta.get_attribute("value") or "").rstrip()
        log(f"current: {current!r}")

        # state.json holds your real headline, so a headline that genuinely
        # ends in '.' keeps it instead of being eaten by a blind strip.
        base = json.loads(STATE.read_text()).get("base") if STATE.exists() else None
        if base is None or current not in (base, base + MARKER):
            base = current[:-len(MARKER)] if current.endswith(MARKER * 2) else current
        target = base if current == base + MARKER else base + MARKER

        if len(target) > 250:
            sys.exit(f"headline would be {len(target)} chars, over Naukri's 250 limit")

        log(f"writing:  {target!r}")
        ta.send_keys(Keys.CONTROL, "a")
        ta.send_keys(target)
        d.find_element(By.CSS_SELECTOR, f"{FORM} button[type='submit']").click()

        d.get(PROFILE)
        saved = (open_editor(d).get_attribute("value") or "").rstrip()
        if saved != target:
            d.save_screenshot(str(DATA / "failure.png"))
            sys.exit(f"save did not stick: page shows {saved!r}")

        STATE.write_text(json.dumps({"base": base}))
        pickle.dump(d.get_cookies(), COOKIES.open("wb"))
        log("done - profile marked updated today")
    finally:
        d.quit()


if __name__ == "__main__":
    main()
