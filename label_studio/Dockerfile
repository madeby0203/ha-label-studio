# https://developers.home-assistant.io/docs/apps/configuration#app-dockerfile
# Debian, not Alpine: DYMO's CUPS driver (printer-driver-dymo) is packaged for Debian.
ARG BUILD_FROM=ghcr.io/home-assistant/base-debian:bookworm-2026.08.0
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip ca-certificates curl tzdata dbus avahi-daemon fonts-dejavu fonts-roboto-unhinted fonts-noto-color-emoji cups printer-driver-dymo \
    && rm -rf /var/lib/apt/lists/*

# Debian only packages MDI 1.x; fetch the release Home Assistant's icon names come from.
ARG MDI_VERSION=7.4.47
RUN mkdir -p /usr/share/mdi \
    && for file in css/materialdesignicons.css fonts/materialdesignicons-webfont.ttf fonts/materialdesignicons-webfont.woff2; do \
        curl -fsSL -o "/usr/share/mdi/$(basename "$file")" "https://cdn.jsdelivr.net/npm/@mdi/font@${MDI_VERSION}/${file}" || exit 1; \
    done

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt
COPY label_renderer.py printer.py app.py ha.py mqtt_bridge.py print_server.py render_png.py ./
# Mode 0700 makes CUPS run the backend as root, which it needs for the USB device.
COPY cups-backend-dymo /usr/lib/cups/backend/dymo
RUN chmod 0700 /usr/lib/cups/backend/dymo
COPY templates ./templates
COPY fonts ./fonts
COPY run.sh ./
RUN chmod +x run.sh render_png.py

CMD ["/app/run.sh"]

LABEL \
    org.opencontainers.image.title="Home Assistant App: Label Studio" \
    org.opencontainers.image.description="Design and print labels on a USB DYMO LabelWriter, from Home Assistant" \
    org.opencontainers.image.source="https://github.com/madeby0203/ha-label-studio" \
    org.opencontainers.image.licenses="MIT"