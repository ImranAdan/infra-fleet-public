FROM alpine/git:v2.54.0@sha256:ae0f6f4bce38d2b8c40becc0d6241a08d9f57186ea03029de2189a2b5e722d94
# Alpine packages the read-only Git transport separately from the client.
RUN apk add --no-cache git-daemon=2.49.1-r0 busybox-extras=1.37.0-r20
COPY git-http-backend /web/cgi-bin/git
RUN chmod 0555 /web/cgi-bin/git
ENTRYPOINT ["/usr/sbin/httpd", "-f", "-p", "8080", "-h", "/web"]
