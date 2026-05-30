FROM python:3.11-slim-bookworm

# Install WeasyPrint system dependencies.
# These must be apt packages in a Debian environment — Nixpacks' Nix store
# approach puts libraries in /nix/store paths that CFFI's ctypes.util.find_library
# cannot locate at runtime.  A Dockerfile with apt-get is the reliable fix.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libharfbuzz0b \
        libcairo2 \
        libgdk-pixbuf2.0-0 \
        libfontconfig1 \
        libffi-dev \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway injects $PORT; default 8000 for local docker runs
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
