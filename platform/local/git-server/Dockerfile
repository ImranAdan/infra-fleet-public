FROM alpine/git:v2.54.0@sha256:a4bb51f1a3553df194ce679fc1db721d8bfba2046fa1a88fe9d4ac551ffbce25
# Alpine packages the read-only Git transport separately from the client.
RUN apk add --no-cache git-daemon=2.54.0-r0 busybox-extras=1.37.0-r31
COPY git-http-backend /web/cgi-bin/git
RUN chmod 0555 /web/cgi-bin/git
ENTRYPOINT ["/usr/sbin/httpd", "-f", "-p", "8080", "-h", "/web"]
