# Fleet Runner

A small side-scrolling platform game for the browser: run, jump, stomp the
walkers, collect coins and reach the flag. It is plain HTML5 canvas served by
Python's standard library, with no dependencies, and it plugs into the fleet
through the [application contract](../../docs/APPLICATION-CONTRACT.md) like
any other app.

Play it locally:

```bash
scripts/select-app.sh mario-game
git commit -am "chore: run mario-game"
./fleet sync --profile local
./fleet access --profile local --service app   # http://localhost:8080/
```

Controls: arrows or A/D to run, Space or W to jump, Enter or Jump to play again.
Touch screens get on-screen buttons.

Its fault switch is `GAME_FAULT=true`, which makes every page request fail
while the health probes keep answering; the acceptance test uses it to prove
automatic rollback.
