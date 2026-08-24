"""Every locator in one place.

Naukri ships markup changes without warning, so no locator is used bare. Each
one is a *chain*: a fast primary, then text-anchored fallbacks that survive
class renames. When a chain runs out, the error names the chain rather than
surfacing a bare NoSuchElementException from somewhere in the call stack.

Run `main.py --discover` to dump the live DOM and confirm these against it.
"""

import logging

from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)

Locator = tuple[str, str]
Chain = list[Locator]


class SelectorBroken(RuntimeError):
    """No locator in a chain matched — Naukri's markup has moved."""


# The "Resume headline" card on /mnjuser/profile.
HEADLINE_CARD: Chain = [
    (By.ID, "lazyResumeHead"),
    (
        By.XPATH,
        '//*[normalize-space(text())="Resume headline"]'
        '/ancestor::div[contains(@class,"card")][1]',
    ),
    (
        By.XPATH,
        '//*[contains(normalize-space(.),"Resume headline")]'
        '/ancestor-or-self::div[contains(@class,"card")][1]',
    ),
]

# The pencil/edit control, searched *within* the headline card.
# Confirmed live: <span class="edit icon">editOneTheme</span>
EDIT_CONTROL: Chain = [
    (By.CSS_SELECTOR, "span.edit.icon"),
    (By.CSS_SELECTOR, "span.edit"),
    (By.CSS_SELECTOR, "em.edit"),
    (By.XPATH, './/*[contains(@class,"edit")]'),
]

# The edit dialog is a plain form, not a .modal / [role=dialog] container, so
# every locator below anchors on the form name.
EDIT_FORM = "form[name='resumeHeadlineForm']"

# The textarea inside the edit dialog. This doubles as the read path: opening
# the dialog and reading .value is more reliable than scraping display markup.
# Confirmed live: id=resumeHeadlineTxt, maxlength=250.
HEADLINE_TEXTAREA: Chain = [
    (By.ID, "resumeHeadlineTxt"),
    (By.CSS_SELECTOR, f"{EDIT_FORM} textarea"),
    (By.CSS_SELECTOR, "textarea[name='resumeHeadline']"),
]

# Scoped to the form on purpose: the profile page carries another *visible*
# button[type=submit] ("Become a Pro"), and a page-wide match could hit it.
SAVE_BUTTON: Chain = [
    (By.CSS_SELECTOR, f"{EDIT_FORM} button[type='submit']"),
    (By.XPATH, '//form[@name="resumeHeadlineForm"]//button[normalize-space()="Save"]'),
    (By.CSS_SELECTOR, f"{EDIT_FORM} button.btn-dark-ot"),
]

# Dismissing the dialog: it is an <a>, and Escape does not close this form.
CANCEL_BUTTON: Chain = [
    (By.CSS_SELECTOR, f"{EDIT_FORM} a.cancel-btn"),
    (By.XPATH, '//form[@name="resumeHeadlineForm"]//a[normalize-space()="Cancel"]'),
]

# Login form. Confirmed against the live page: both fields carry stable ids.
# Fallbacks anchor on the placeholder rather than on "any text input", which
# would match the nav search box.
LOGIN_EMAIL: Chain = [
    (By.ID, "usernameField"),
    (By.CSS_SELECTOR, "input[placeholder*='Email' i]"),
]

LOGIN_PASSWORD: Chain = [
    (By.ID, "passwordField"),
    (By.CSS_SELECTOR, "input[type='password']"),
]

# The page has two submit buttons: "Login" and "Use OTP to Login". Match the
# password one by its text first — landing on the OTP button would send a code
# to the user's phone and stall the run.
LOGIN_SUBMIT: Chain = [
    (By.XPATH, '//button[@type="submit"][normalize-space()="Login"]'),
    (By.XPATH, '//button[normalize-space()="Login"]'),
]

# Purely informational — absence is not an error.
LAST_UPDATED: Chain = [
    (By.XPATH, '//*[contains(text(),"Last updated")]'),
    (By.XPATH, '//*[contains(text(),"last updated")]'),
]


def find_first(scope, chain: Chain, label: str, require_visible: bool = False):
    """Return the first element matched by `chain`, searched within `scope`.

    `scope` may be a driver (document-wide) or an element (subtree).

    Each locator is matched against *all* its hits rather than just the first,
    because a loose fallback often matches an offscreen node before the one we
    want — Naukri's collapsed nav search box is a text input sitting in the DOM
    long before the login form renders. Pass require_visible for anything you
    are about to click or type into.
    """
    for by, value in chain:
        try:
            elements = scope.find_elements(by, value)
        except (NoSuchElementException, WebDriverException):
            continue

        for element in elements:
            if require_visible:
                try:
                    if not (element.is_displayed() and element.is_enabled()):
                        continue
                except WebDriverException:
                    continue
            logger.debug("%s matched via %s=%s", label, by, value)
            return element

    raise SelectorBroken(
        f"{label}: none of {len(chain)} locators matched. "
        f"Naukri's markup likely changed — run `main.py --discover` and "
        f"update naukri/selectors.py."
    )


def find_first_or_none(scope, chain: Chain, label: str, require_visible: bool = False):
    """find_first for locators whose absence is tolerable."""
    try:
        return find_first(scope, chain, label, require_visible)
    except SelectorBroken:
        logger.debug("%s not present", label)
        return None
