FROM alpine/git:v2.54.0@sha256:832b1cd1a271509f3d5272a1a62d4cb2ab1a53426ebde1f6c2cb7349f907dc6f
# Alpine packages the read-only Git transport separately from the client.
RUN apk add --no-cache git-daemon=2.54.0-r0 busybox-extras=1.37.0-r31
COPY git-http-backend /web/cgi-bin/git
RUN chmod 0555 /web/cgi-bin/git
ENTRYPOINT ["/usr/sbin/httpd", "-f", "-p", "8080", "-h", "/web"]
