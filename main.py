#!/usr/bin/env python3
"""Keep a Naukri profile marked as recently updated.

    python main.py                 # the scheduled path: headless toggle
    python main.py --headful       # same, with a visible browser
    python main.py --discover      # dump the live headline DOM, change nothing
    python main.py --reset-base    # re-capture the headline as the new base
"""

import argparse
import sys

from naukri import config, driver as drv, headline, selectors as sel, session


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--headful", action="store_true", help="show the browser window")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="dump the headline card's markup to artifacts/ and exit without editing",
    )
    parser.add_argument(
        "--reset-base",
        action="store_true",
        help="treat the current headline as the new canonical base",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def discover(driver, logger) -> None:
    """Confirm the real locators in one pass, without touching the profile."""
    config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out = config.ARTIFACT_DIR / "discovery.html"

    card = sel.find_first(driver, sel.HEADLINE_CARD, "headline card")
    markup = card.get_attribute("outerHTML")
    out.write_text(markup, encoding="utf-8")
    logger.info("wrote headline card markup to %s (%d bytes)", out, len(markup))

    # The ids and classes inside the card are what selectors.py needs.
    attrs = driver.execute_script(
        """
        const root = arguments[0];
        return Array.from(root.querySelectorAll('*'))
            .map(el => ({tag: el.tagName.toLowerCase(), id: el.id, cls: el.className}))
            .filter(x => x.id || (typeof x.cls === 'string' && x.cls));
        """,
        card,
    )
    for a in attrs:
        logger.info("  <%s> id=%r class=%r", a["tag"], a["id"], a["cls"])

    headline.log_last_updated(driver)


def run_once(headless: bool, args, logger) -> dict | None:
    driver = drv.build_driver(headless=headless)
    try:
        session.ensure_session(driver)

        if args.discover:
            discover(driver, logger)
            return None

        result = headline.toggle(driver, reset_base=args.reset_base)
        headline.log_last_updated(driver)

        # The session may have been refreshed server-side during this run.
        session.save_cookies(driver)
        return result
    finally:
        driver.quit()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = config.setup_logging(args.verbose)

    # Discovery is a human-in-the-loop step; never hide the browser for it.
    headless = False if (args.headful or args.discover) else config.headless_default()

    try:
        try:
            result = run_once(headless, args, logger)
        except (session.LoginFailed, headline.HeadlineError, sel.SelectorBroken) as exc:
            # A stale cookie jar can leave us half-authenticated in ways that
            # surface as a selector miss. Drop it and take the login path once.
            if not config.COOKIE_FILE.exists():
                raise
            logger.warning("first attempt failed (%s) — discarding cookies and retrying", exc)
            config.COOKIE_FILE.unlink()
            result = run_once(headless, args, logger)
    except config.ConfigError as exc:
        logger.error("%s", exc)
        return 2
    except Exception as exc:
        logger.error("run failed: %s", exc)
        logger.debug("traceback", exc_info=True)
        return 1

    if result is not None:
        logger.info("done — headline is %r", result["applied"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
