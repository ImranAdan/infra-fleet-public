FROM alpine/git:2.49.1@sha256:c0280cf9572316299b08544065d3bf35db65043d5e3963982ec50647d2746e26
# Alpine packages the read-only Git transport separately from the client.
RUN apk add --no-cache git-daemon=2.49.1-r0 busybox-extras=1.37.0-r20
COPY git-http-backend /web/cgi-bin/git
RUN chmod 0555 /web/cgi-bin/git
ENTRYPOINT ["/usr/sbin/httpd", "-f", "-p", "8080", "-h", "/web"]
