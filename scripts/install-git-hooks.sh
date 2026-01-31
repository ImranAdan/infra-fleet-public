#!/bin/sh
set -e

git config core.hooksPath .githooks
echo "Git hooks installed. Ensure gitlint is available via requirements-dev.txt."
