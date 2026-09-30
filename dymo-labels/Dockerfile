ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip fonts-dejavu fonts-noto-core fonts-noto-color-emoji fonts-materialdesignicons-webfont cups printer-driver-dymo \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt
COPY label_renderer.py printer.py app.py render_png.py ./
COPY run.sh ./
RUN chmod +x run.sh render_png.py

CMD ["/app/run.sh"]