# podinfo

A small Go web service by the Flux maintainers, used here as a swap-in
application. It proves the platform names no app of its own: run
`scripts/select-app.sh podinfo`, commit, then `./fleet sync --profile local`
and `./fleet test --profile local`. It can also be launched beside the selected
app from the local application dashboard.
See the [application contract](../../docs/APPLICATION-CONTRACT.md).

Its fault switch is `PODINFO_RANDOM_ERROR=true`, which fails about a third of
requests; the acceptance test uses it to prove automatic rollback.
