#!/bin/sh

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    die 'neither shasum nor sha256sum is available'
  fi
}

verify_sha256() {
  _verify_file=$1
  _verify_expected=$2
  _verify_actual=$(sha256_file "$_verify_file")
  [ "$_verify_actual" = "$_verify_expected" ] || \
    die "SHA-256 mismatch for $_verify_file (expected $_verify_expected, got $_verify_actual)"
}

download_once() {
  _download_url=$1
  _download_destination=$2
  if [ -f "$_download_destination" ]; then
    return
  fi

  mkdir -p "$(dirname "$_download_destination")"
  _download_temporary="${_download_destination}.part"
  rm -f "$_download_temporary"
  printf 'Downloading %s\n' "$_download_url" >&2
  curl -L --fail --show-error --retry 3 --max-time 600 "$_download_url" -o "$_download_temporary"
  mv "$_download_temporary" "$_download_destination"
}

host_jobs() {
  if command -v nproc >/dev/null 2>&1; then
    nproc
  elif command -v sysctl >/dev/null 2>&1; then
    sysctl -n hw.ncpu
  else
    printf '2\n'
  fi
}
