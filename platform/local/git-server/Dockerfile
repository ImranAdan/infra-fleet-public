FROM alpine/git:2.49.1@sha256:c0280cf9572316299b08544065d3bf35db65043d5e3963982ec50647d2746e26
# Alpine packages the read-only Git transport separately from the client.
RUN apk add --no-cache git-daemon
ENTRYPOINT ["git"]
