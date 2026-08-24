"""Chrome factory and failure-artifact dumping."""

import logging
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from . import config

logger = logging.getLogger(__name__)

# Real Chrome 151 on Linux. Headless Chrome otherwise advertises a
# "HeadlessChrome" token, which is the cheapest possible bot tell.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

PAGE_LOAD_TIMEOUT = 60
DEFAULT_WAIT = 20


def build_driver(headless: bool) -> webdriver.Chrome:
    """Selenium Manager resolves chromedriver itself, so no driver path here."""
    options = Options()

    if headless:
        options.add_argument("--headless=new")

    # Headless Chrome defaults to 800x600, at which Naukri serves a mobile
    # layout with an entirely different DOM. Pin a desktop viewport.
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=en-US")
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if config.no_sandbox():
        # Required in a container: the setuid sandbox needs privileges that a
        # default Docker profile withholds.
        options.add_argument("--no-sandbox")

    if config.CHROME_BINARY:
        options.binary_location = config.CHROME_BINARY

    # With no explicit driver, Selenium Manager resolves one — fine on a
    # workstation, but it needs network access, so containers pin the path.
    service = Service(executable_path=config.CHROMEDRIVER) if config.CHROMEDRIVER else Service()

    logger.info("starting chrome (headless=%s)", headless)
    driver = webdriver.Chrome(options=options, service=service)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver


def wait(driver: webdriver.Chrome, timeout: int = DEFAULT_WAIT) -> WebDriverWait:
    return WebDriverWait(driver, timeout)


def dump_artifacts(driver: webdriver.Chrome, label: str) -> Path | None:
    """Screenshot + page source into artifacts/<timestamp>-<label>/.

    Best effort: never let diagnostics mask the original failure.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = config.ARTIFACT_DIR / f"{stamp}-{label}"
    try:
        target.mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(str(target / "screenshot.png"))
        (target / "page.html").write_text(driver.page_source, encoding="utf-8")
        (target / "url.txt").write_text(driver.current_url, encoding="utf-8")
    except Exception:
        logger.exception("could not write artifacts to %s", target)
        return None

    logger.error("wrote failure artifacts to %s", target)
    return target
