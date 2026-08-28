FROM rockylinux:8

# RHEL 8's default python3 is 3.6, which can't run the service. python39
# (AppStream) can: the source is 3.7+ syntax and tomllib falls back to the
# vendored tomli backport on <3.11. Point `python3` on PATH at python3.9 so
# both the pkger build (compileall) and the runtime launcher use it.
RUN dnf install -y python39 ca-certificates \
    && dnf clean all \
    && ln -sf /usr/bin/python3.9 /usr/local/bin/python3

ENV PKGER_OS=Red\ Hat
ENV PKGER_OS_VERSION=8
