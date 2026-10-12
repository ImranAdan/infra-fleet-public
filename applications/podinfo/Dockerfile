# podinfo (https://github.com/stefanprodan/podinfo), pinned by digest. It is the
# second application that proves the fleet runs any containerised HTTP service
# through the app contract in k8s/fleet-app; nothing here is fleet-specific.
FROM ghcr.io/stefanprodan/podinfo:6.15.0@sha256:ec73780a8425f59ea49f5bc8cdff0d598805a224fbaa1f86c67a244f250fa9da

# Alpine security updates published since the pinned digest (OpenSSL
# CVE-2026-14456 at the time of writing). The Go binaries' own advisories need
# an upstream release, which Dependabot proposes. Restore the image's user.
USER root
RUN apk upgrade --no-cache
USER app
