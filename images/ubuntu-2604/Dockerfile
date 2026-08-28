FROM ubuntu:26.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PKGER_OS=Ubuntu
ENV PKGER_OS_VERSION=26.04
