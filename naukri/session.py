"""Cookie-pickle session restore, with a password login as the fallback."""

import logging
import pickle

from selenium.common.exceptions import (
    InvalidArgumentException,
    InvalidCookieDomainException,
    TimeoutException,
    WebDriverException,
)

from . import config, driver as drv, selectors as sel

logger = logging.getLogger(__name__)

# Cookies may only be installed for the domain the browser is currently on.
ALLOWED_DOMAINS = {"naukri.com", ".naukri.com", "www.naukri.com"}

# URL fragments that mean "definitely not logged in".
LOGGED_OUT_MARKERS = ("/nlogin/", "/registration/", "/login")


class LoginFailed(RuntimeError):
    """Password login did not land us in a signed-in session."""


def _sanitize(cookie: dict) -> dict | None:
    """Coerce a saved cookie into something add_cookie() will accept.

    Chrome hands back `expiry` as a float and `sameSite` values that the
    WebDriver spec rejects; both raise InvalidArgumentException verbatim.
    """
    domain = cookie.get("domain", "")
    if domain and domain not in ALLOWED_DOMAINS:
        return None

    clean = {
        k: v
        for k, v in cookie.items()
        if k in {"name", "value", "path", "domain", "secure", "httpOnly", "sameSite", "expiry"}
    }

    if "expiry" in clean:
        try:
            clean["expiry"] = int(clean["expiry"])
        except (TypeError, ValueError):
            del clean["expiry"]

    if clean.get("sameSite") not in {"Strict", "Lax", "None"}:
        clean.pop("sameSite", None)

    if not clean.get("name"):
        return None

    return clean


def load_cookies(driver) -> int:
    """Install saved cookies. Returns how many actually took."""
    if not config.COOKIE_FILE.exists():
        logger.info("no cookie file at %s", config.COOKIE_FILE)
        return 0

    try:
        with config.COOKIE_FILE.open("rb") as fh:
            cookies = pickle.load(fh)
    except (pickle.UnpicklingError, EOFError, OSError) as exc:
        logger.warning("cookie file unreadable (%s) — ignoring it", exc)
        return 0

    if not isinstance(cookies, list) or not cookies:
        logger.info("cookie file holds no usable session")
        return 0

    # add_cookie() only works once the browser is on the target domain.
    driver.get(config.BASE_URL)

    installed = 0
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        clean = _sanitize(cookie)
        if clean is None:
            continue
        try:
            driver.add_cookie(clean)
            installed += 1
        except (
            InvalidArgumentException,
            InvalidCookieDomainException,
            WebDriverException,
        ) as exc:
            # One malformed cookie must not sink the whole restore.
            logger.debug("skipped cookie %s: %s", clean.get("name"), exc.__class__.__name__)

    logger.info("restored %d/%d cookies", installed, len(cookies))
    return installed


def save_cookies(driver) -> None:
    cookies = driver.get_cookies()
    with config.COOKIE_FILE.open("wb") as fh:
        pickle.dump(cookies, fh)
    config.COOKIE_FILE.chmod(0o600)
    logger.info("saved %d cookies to %s", len(cookies), config.COOKIE_FILE.name)


def is_logged_in(driver, timeout: int = 10) -> bool:
    """Positive check: the headline card is actually on the page.

    A URL test alone is not enough — Naukri will serve the profile shell to a
    signed-out client and only then redirect client-side.
    """
    url = driver.current_url
    if any(marker in url for marker in LOGGED_OUT_MARKERS):
        logger.debug("logged out by URL: %s", url)
        return False

    try:
        drv.wait(driver, timeout).until(
            lambda d: sel.find_first_or_none(d, sel.HEADLINE_CARD, "headline card") is not None
        )
    except TimeoutException:
        logger.debug("headline card never appeared at %s", driver.current_url)
        return False

    return True


def password_login(driver) -> None:
    """Sign in with credentials from .env, then re-pickle the fresh session."""
    email, password = config.credentials()

    logger.info("session expired or absent — logging in as %s", email)
    driver.get(config.LOGIN_URL)

    # Wait for a field that is actually usable, not merely present: the login
    # form renders after the rest of the page.
    try:
        email_field = drv.wait(driver).until(
            lambda d: sel.find_first_or_none(d, sel.LOGIN_EMAIL, "login email", require_visible=True)
        )
        password_field = sel.find_first(
            driver, sel.LOGIN_PASSWORD, "login password", require_visible=True
        )
    except TimeoutException as exc:
        drv.dump_artifacts(driver, "login-form-missing")
        raise LoginFailed("login form never rendered") from exc

    email_field.clear()
    email_field.send_keys(email)
    password_field.clear()
    password_field.send_keys(password)

    sel.find_first(driver, sel.LOGIN_SUBMIT, "login submit", require_visible=True).click()

    try:
        drv.wait(driver, 30).until(
            lambda d: "/nlogin/" not in d.current_url
        )
    except TimeoutException as exc:
        # Wrong password, an OTP challenge or a captcha all land here.
        drv.dump_artifacts(driver, "login-stuck")
        raise LoginFailed(
            "still on the login page after submitting — check the artifacts "
            "directory for a captcha or OTP challenge"
        ) from exc

    driver.get(config.PROFILE_URL)
    if not is_logged_in(driver, timeout=20):
        drv.dump_artifacts(driver, "login-unverified")
        raise LoginFailed("logged in but the profile page did not load")

    logger.info("login succeeded")
    save_cookies(driver)


def ensure_session(driver) -> None:
    """Land on the profile page in a signed-in state, however that takes."""
    load_cookies(driver)
    driver.get(config.PROFILE_URL)

    if is_logged_in(driver):
        logger.info("restored session is still valid")
        return

    password_login(driver)
