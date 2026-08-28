FROM opensuse/tumbleweed

# pkger 0.11.0 has no OpenSUSE distro in its enum (only arch/centos/debian/
# fedora/redhat/ubuntu/rocky/alpine), so with os: OpenSUSE it would invoke
# its fallback package manager ("unkown") and fail. Workaround: declare
# `os: Fedora` in .pkger.yml so pkger uses dnf for dependency installation,
# preinstall dnf AND every package pkger would try to install (build deps
# tar/rpm-build/util-linux + recipe dep python3) via zypper here — dnf5 in
# Tumbleweed has no repo metadata configured, so anything NOT already
# installed would fail with "No match"; preinstalled packages resolve as
# "already installed" and dnf exits 0. The actual RPM build uses rpmbuild
# and is OS-agnostic.
RUN zypper --non-interactive install \
        python3 dnf tar rpm-build util-linux ca-certificates \
    && zypper clean -a

ENV PKGER_OS=OpenSUSE
ENV PKGER_OS_VERSION=tumbleweed
# pkger uploads the source tarball and spec to /root/rpmbuild/{SOURCES,SPECS}
# (Fedora layout). Tumbleweed's rpm defaults %_topdir to /usr/src/packages —
# override via /root/.rpmmacros so rpmbuild finds pkger's uploads.
RUN echo "%_topdir /root/rpmbuild" > /root/.rpmmacros
