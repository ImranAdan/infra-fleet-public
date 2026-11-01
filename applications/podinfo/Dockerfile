# podinfo (https://github.com/stefanprodan/podinfo), pinned by digest. It is the
# second application that proves the fleet runs any containerised HTTP service
# through the app contract in k8s/fleet-app; nothing here is fleet-specific.
FROM ghcr.io/stefanprodan/podinfo:6.17.0@sha256:fa2f27c1a8561097e5144bfc0853eba6054d743b68b03de4cad4675616ddefb0

# Alpine security updates published since the pinned digest (OpenSSL
# CVE-2026-14456 at the time of writing). The Go binaries' own advisories need
# an upstream release, which Dependabot proposes. Restore the image's user.
USER root
RUN apk upgrade --no-cache
USER app
