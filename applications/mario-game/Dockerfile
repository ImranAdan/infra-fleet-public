# Fleet Runner: a browser platformer served by Python's standard library.
# Same pinned base as load-harness, so no new image to track.
FROM python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY server.py index.html game.js style.css ./
USER 10001:10001
EXPOSE 8080
CMD ["python3", "server.py"]
