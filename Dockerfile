FROM python:3.12-slim-bookworm

# Chromium and its matching driver come from apt, so the image needs no
# network access at run time to resolve a driver.
# Fetch over HTTPS. An intercepting HTTP proxy can serve a stale .deb, which
# apt reports as "Hash Sum mismatch" and which no amount of retrying fixes;
# HTTPS is not interceptable that way.
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
        /etc/apt/sources.list.d/debian.sources \
    && echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        ca-certificates \
        fonts-liberation \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BINARY=/usr/bin/chromium \
    CHROMEDRIVER=/usr/bin/chromedriver \
    NO_SANDBOX=1 \
    HEADLESS=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY naukri.py .


# Run unprivileged. /data holds cookies.pkl and state.json across runs.
RUN useradd --create-home --uid 1000 runner \
    && mkdir -p /data \
    && chown -R runner:runner /data /app
USER runner

VOLUME ["/data"]

ENTRYPOINT ["python", "naukri.py"]
