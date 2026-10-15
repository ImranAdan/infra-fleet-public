FROM alpine/git:v2.54.0@sha256:ce84fd6a057b4dc5cf5009da2dd832f1c6d096c1984bf50496cf3c256402264d
# Alpine packages the read-only Git transport separately from the client.
RUN apk add --no-cache git-daemon=2.54.0-r0 busybox-extras=1.37.0-r31
COPY git-http-backend /web/cgi-bin/git
RUN chmod 0555 /web/cgi-bin/git
ENTRYPOINT ["/usr/sbin/httpd", "-f", "-p", "8080", "-h", "/web"]
