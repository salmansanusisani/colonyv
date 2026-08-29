# ColonyV production image.
#
# The service both serves the dashboard/API and runs the full production pipeline,
# so the image needs the complete render toolchain, not just Python:
#
#   * Node.js       to run the Remotion renderer
#   * Chromium      the headless browser Remotion rasterises frames with
#   * FFmpeg        muxing, and ffprobe for measuring narration duration
#
# The previous image was python:slim with pip requirements only. It could serve
# the dashboard but every render failed, because npx, Chromium and ffprobe were
# all absent.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    NODE_MAJOR=20 \
    # Point Remotion at the distro Chromium instead of letting it download one.
    REMOTION_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium \
    # Vertex AI via the attached service account; no API keys in the image.
    GOOGLE_GENAI_USE_VERTEXAI=true

WORKDIR /app

# --- System toolchain -------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        ffmpeg \
        chromium \
        fonts-liberation \
        fontconfig \
        libnss3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y --auto-remove gnupg \
    && rm -rf /var/lib/apt/lists/*

# --- Python dependencies ----------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Node dependencies ------------------------------------------------------
# Copied separately so a source change does not invalidate the npm layer.
COPY producer/package.json producer/package-lock.json producer/.npmrc ./producer/
RUN cd producer \
    && npm ci --no-audit --no-fund \
    && npm cache clean --force

# --- Application ------------------------------------------------------------
COPY . .

# Remotion writes its bundle and Chromium writes its profile at render time.
RUN mkdir -p producer/renders producer/public output \
    && fc-cache -f

EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn dashboard.app:app --host 0.0.0.0 --port ${PORT}"]
