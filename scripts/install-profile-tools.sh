#!/usr/bin/env bash
# Install the pinned profile CLIs into a caller-owned directory. CI asks for
# kubectl only; the local profile also asks for kind and Flux.
set -euo pipefail

tool_directory=${1:?Pass the tool directory}
mode=${2:-}
case "$mode" in ''|--local) ;; *) echo 'Usage: install-profile-tools.sh DIRECTORY [--local]' >&2; exit 2 ;; esac

case "$(uname -s)" in
  Linux) operating_system=linux ;;
  Darwin) operating_system=darwin ;;
  *) echo 'Profile tools support Linux and macOS.' >&2; exit 2 ;;
esac
case "$(uname -m)" in
  x86_64|amd64) architecture=amd64 ;;
  arm64|aarch64) architecture=arm64 ;;
  *) echo 'Profile tools support amd64 and arm64.' >&2; exit 2 ;;
esac

case "$operating_system/$architecture" in
  linux/amd64)
    kubectl_checksum=a2e984a18a0c063279d692533031c1eff93a262afcc0afdc517375432d060989
    kind_checksum=eb244cbafcc157dff60cf68693c14c9a75c4e6e6fedaf9cd71c58117cb93e3fa
    flux_checksum=1e92141e8498289e4b27411385aeb18396053176cf297b0cb99abd6ca8293e75 ;;
  linux/arm64)
    kubectl_checksum=58f82f9fe796c375c5c4b8439850b0f3f4d401a52434052f2df46035a8789e25
    kind_checksum=8e1014e87c34901cc422a1445866835d1e666f2a61301c27e722bdeab5a1f7e4
    flux_checksum=89d3ebb47ee5f7a0def33217e8dcb885e0bec41d01d0e23fc84e9aba0416c24e ;;
  darwin/amd64)
    kubectl_checksum=2447cb78911b10a667202b078eeb30541ec78d1280c3682921dc81607e148d96
    kind_checksum=a8b3cf77b2ad77aec5bf710d1a2589d9117576132af812885cad41e9dede4d4e
    flux_checksum=2058b49ef38b5773b9aa87b3db83d68cbaf5082ecf908cbd8952a17f6af0e2e8 ;;
  darwin/arm64)
    kubectl_checksum=cf699c56340dc775230fde4ef84237d27563ea6ef52164c7d078072b586c3918
    kind_checksum=88bf554fe9da6311c9f8c2d082613c002911a476f6b5090e9420b35d84e70c5c
    flux_checksum=79faae964badc0b08f61ef6228f636bea99c6750537634855fa8b84f75b006d8 ;;
esac

verify_checksum() {
  local expected=$1 file=$2 actual
  if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$file" | awk '{print $1}')
  elif command -v shasum >/dev/null 2>&1; then
    actual=$(shasum -a 256 "$file" | awk '{print $1}')
  elif command -v openssl >/dev/null 2>&1; then
    actual=$(openssl dgst -sha256 "$file" | awk '{print $NF}')
  else
    echo 'A SHA-256 tool (sha256sum, shasum or openssl) is required.' >&2
    return 1
  fi
  [ "$actual" = "$expected" ]
}

download_verified() {
  local url=$1 checksum=$2 destination=$3 temporary
  if [ -f "$destination" ] && verify_checksum "$checksum" "$destination"; then
    return
  fi
  temporary=$(mktemp "$tool_directory/.download.XXXXXX")
  if ! curl -fsSL --retry 3 "$url" -o "$temporary" || \
     ! verify_checksum "$checksum" "$temporary"; then
    rm -f "$temporary"
    echo "Could not install the verified tool from $url" >&2
    return 1
  fi
  mv "$temporary" "$destination"
}

mkdir -p "$tool_directory"
chmod 700 "$tool_directory"
download_verified \
  "https://dl.k8s.io/release/v1.35.0/bin/$operating_system/$architecture/kubectl" \
  "$kubectl_checksum" "$tool_directory/kubectl"
chmod +x "$tool_directory/kubectl"

if [ "$mode" = --local ]; then
  download_verified \
    "https://github.com/kubernetes-sigs/kind/releases/download/v0.31.0/kind-$operating_system-$architecture" \
    "$kind_checksum" "$tool_directory/kind"
  flux_archive="$tool_directory/.flux_2.7.5_${operating_system}_${architecture}.tar.gz"
  download_verified \
    "https://github.com/fluxcd/flux2/releases/download/v2.7.5/flux_2.7.5_${operating_system}_${architecture}.tar.gz" \
    "$flux_checksum" "$flux_archive"
  flux_extract=$(mktemp -d "$tool_directory/.flux.XXXXXX")
  trap 'rm -rf "$flux_extract"' EXIT
  tar -xzf "$flux_archive" -C "$flux_extract" flux
  mv "$flux_extract/flux" "$tool_directory/flux"
  rm -rf "$flux_extract"
  trap - EXIT
  chmod +x "$tool_directory/kind" "$tool_directory/flux"
fi
