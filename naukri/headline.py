"""Toggle a marker character on the resume headline.

The naive version of this ("if it ends with '.', strip it") quietly mangles a
headline that legitimately ends in a period. So we keep the canonical headline
in state.json and derive the toggle direction from the *live* text each run.

Deriving from the page rather than from a stored flag means a failed save can
never desync us: the next run just reads reality and carries on.
"""

import json
import logging
from datetime import datetime

from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC

from . import config, driver as drv, selectors as sel

logger = logging.getLogger(__name__)


class HeadlineError(RuntimeError):
    """The headline could not be read or written."""


def load_state() -> dict:
    if not config.STATE_FILE.exists():
        return {}
    try:
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("state file unreadable (%s) — starting fresh", exc)
        return {}


def save_state(base: str, applied: str) -> None:
    config.STATE_FILE.write_text(
        json.dumps(
            {
                "base": base,
                "last_applied": applied,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def wait_for_card(driver):
    """Wait for the headline card to render.

    It is React-mounted lazily (hence the id `lazyResumeHead`), so a bare
    find_element straight after a page load loses the race — reliably so in
    headless, which gets there faster than a headful window does.
    """
    try:
        return drv.wait(driver).until(
            lambda d: sel.find_first_or_none(d, sel.HEADLINE_CARD, "headline card")
        )
    except TimeoutException as exc:
        raise HeadlineError("headline card never rendered") from exc


def open_editor(driver):
    """Click the headline card's edit control and return the live textarea."""
    card = wait_for_card(driver)
    edit = sel.find_first(card, sel.EDIT_CONTROL, "edit control", require_visible=True)

    # The card is often below the fold; a plain click would miss it.
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", edit)
    try:
        edit.click()
    except Exception:
        # Overlays (cookie bars, sticky headers) intercept the real click.
        logger.debug("native click intercepted — falling back to JS click")
        driver.execute_script("arguments[0].click();", edit)

    try:
        textarea = drv.wait(driver).until(
            lambda d: sel.find_first_or_none(
                d, sel.HEADLINE_TEXTAREA, "headline textarea", require_visible=True
            )
        )
        drv.wait(driver).until(EC.visibility_of(textarea))
    except TimeoutException as exc:
        raise HeadlineError("edit dialog never opened") from exc

    return textarea


def close_editor(driver) -> None:
    """Best-effort dismiss, for the read-only paths.

    The dialog is a plain form with a Cancel anchor; Escape does not close it.
    """
    cancel = sel.find_first_or_none(driver, sel.CANCEL_BUTTON, "cancel button", require_visible=True)
    if cancel is None:
        logger.debug("no cancel control found — leaving the dialog open")
        return
    try:
        cancel.click()
    except Exception:
        driver.execute_script("arguments[0].click();", cancel)


def read_headline(driver) -> str:
    """Open the dialog, read the textarea, close it again.

    Reading the textarea beats scraping the display markup: it is the exact
    string Naukri will store, whitespace and all.
    """
    textarea = open_editor(driver)
    value = textarea.get_attribute("value") or ""
    close_editor(driver)
    return value.rstrip()


def _strip_marker_run(text: str, marker: str) -> str:
    """Collapse a trailing run of markers down to a single one.

    Only doubled-up markers are removed, so a headline that legitimately ends
    in the marker character keeps it. This bounds the damage if state.json is
    lost: without it, a stateless runner would append a marker every run and
    the headline would grow "Engineer....." indefinitely.
    """
    while text.endswith(marker + marker):
        text = text[: -len(marker)]
    return text


def resolve_target(current: str, stored_base: str | None, marker: str) -> tuple[str, str, bool]:
    """Work out what to write next.

    Returns (base, target, drifted).
    """
    drifted = False

    if stored_base is not None:
        if current == stored_base + marker:
            return stored_base, stored_base, False
        if current == stored_base:
            return stored_base, stored_base + marker, False
        # Neither variant matched: the headline was edited by hand since the
        # last run. Fall through and re-derive from the page.
        drifted = True

    # No usable state — work it out from the page alone. If the text already
    # carries a doubled marker, that run was ours, so strip it; otherwise
    # append. Either branch changes the text, which is the point of the run.
    base = _strip_marker_run(current, marker)
    target = base if base != current else current + marker
    return base, target, drifted


def apply_headline(driver, target: str) -> None:
    """Type `target` into the dialog and save it."""
    textarea = open_editor(driver)

    # .clear() alone does not always fire the events a controlled textarea
    # listens for; select-all-then-type reliably replaces the content.
    textarea.send_keys(Keys.CONTROL, "a")
    textarea.send_keys(target)

    save = sel.find_first(driver, sel.SAVE_BUTTON, "save button", require_visible=True)
    try:
        save.click()
    except Exception:
        logger.debug("native save click intercepted — falling back to JS click")
        driver.execute_script("arguments[0].click();", save)

    try:
        drv.wait(driver).until(EC.staleness_of(textarea))
    except (TimeoutException, StaleElementReferenceException):
        # Some builds reuse the node instead of tearing it down; the
        # verification read below is the real check, so this is not fatal.
        logger.debug("dialog did not go stale after save")


def toggle(driver, reset_base: bool = False) -> dict:
    """Flip the marker, verify it stuck, and persist the canonical base."""
    marker = config.MARKER
    state = load_state()
    stored_base = None if reset_base else state.get("base")

    if reset_base:
        logger.info("--reset-base: re-capturing the headline from the page")

    current = read_headline(driver)
    logger.info("current headline: %r", current)

    base, target, drifted = resolve_target(current, stored_base, marker)

    if drifted:
        logger.warning(
            "headline was edited outside this script — adopting %r as the new base", base
        )

    if len(target) > config.HEADLINE_MAX:
        raise HeadlineError(
            f"headline would be {len(target)} chars, over Naukri's "
            f"{config.HEADLINE_MAX} limit — shorten it first"
        )

    logger.info("writing headline: %r", target)
    apply_headline(driver, target)

    # Re-load the page so verification reads persisted state, not just the DOM
    # the dialog left behind.
    driver.get(config.PROFILE_URL)
    saved = read_headline(driver)

    if saved != target:
        drv.dump_artifacts(driver, "verify-failed")
        raise HeadlineError(f"save did not stick: wanted {target!r}, page shows {saved!r}")

    save_state(base, target)
    logger.info("verified — headline is now %r", saved)

    return {"base": base, "applied": target, "drifted": drifted}


def log_last_updated(driver) -> None:
    """Informational only — Naukri moves this label around."""
    element = sel.find_first_or_none(driver, sel.LAST_UPDATED, "last-updated label")
    if element is not None:
        logger.info("profile says: %s", " ".join(element.text.split()))
