FROM debian:13

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# pkger target metadata
ENV PKGER_OS=Debian
ENV PKGER_OS_VERSION=13
