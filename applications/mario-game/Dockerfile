# Fleet Runner: a browser platformer served by Python's standard library.
# Same pinned base as load-harness, so no new image to track.
FROM python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080

# Apply Debian security updates published since the base digest, then remove
# the package installer: server.py uses only the standard library, and pip,
# setuptools and wheel carry their own fixed advisories. Same two steps as
# applications/load-harness/Dockerfile; -exec fails the build if the derived
# site-packages path is wrong.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && SITE_PACKAGES="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
    && pip uninstall -y pip setuptools wheel \
    && rm -rf "${SITE_PACKAGES}/pkg_resources" \
    && find "${SITE_PACKAGES}" -maxdepth 1 \
        \( -name 'setuptools-*' -o -name 'wheel-*' -o -name 'pip-*' \) \
        -exec rm -rf {} +
WORKDIR /app
COPY server.py index.html game.js style.css ./
USER 10001:10001
EXPOSE 8080
CMD ["python3", "server.py"]
