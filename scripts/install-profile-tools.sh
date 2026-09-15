#!/usr/bin/env bash
# Pinned Linux CI tools. Local users use the host tools listed in the guide.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
  echo 'This installer targets Linux amd64 CI only.' >&2; exit 2
fi
tool_directory=${1:?Pass the CI tool directory}
mkdir -p "$tool_directory"
curl -fsSL --retry 3 https://dl.k8s.io/release/v1.35.0/bin/linux/amd64/kubectl -o "$tool_directory/kubectl"
echo "a2e984a18a0c063279d692533031c1eff93a262afcc0afdc517375432d060989  $tool_directory/kubectl" | sha256sum --check
chmod +x "$tool_directory/kubectl"
if [ "${2:-}" = --local ]; then
  curl -fsSL --retry 3 https://github.com/kubernetes-sigs/kind/releases/download/v0.31.0/kind-linux-amd64 -o "$tool_directory/kind"
  echo "eb244cbafcc157dff60cf68693c14c9a75c4e6e6fedaf9cd71c58117cb93e3fa  $tool_directory/kind" | sha256sum --check
  curl -fsSL --retry 3 https://github.com/fluxcd/flux2/releases/download/v2.7.5/flux_2.7.5_linux_amd64.tar.gz -o "$tool_directory/flux.tar.gz"
  echo "1e92141e8498289e4b27411385aeb18396053176cf297b0cb99abd6ca8293e75  $tool_directory/flux.tar.gz" | sha256sum --check
  tar -xzf "$tool_directory/flux.tar.gz" -C "$tool_directory" flux
  chmod +x "$tool_directory/kind" "$tool_directory/flux"
fi
