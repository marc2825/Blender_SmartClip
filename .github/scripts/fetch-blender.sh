#!/usr/bin/env bash
# Download the Linux build of Blender VERSION into the current directory and
# verify it against the checksum published on blender.org.
#
#   .github/scripts/fetch-blender.sh 4.0.2
#
# An archive and checksum file that are already present (restored from the
# Actions cache) are verified and reused.  download.blender.org sometimes
# rejects parallel downloads from CI runners, so mirrors are tried in turn;
# the checksum always comes from blender.org.
set -euo pipefail

version="$1"
series="${version%.*}"          # 4.0.2 -> 4.0
archive="blender-${version}-linux-x64.tar.xz"
sums="blender-${version}.sha256"

if [[ ! -s "${sums}" ]]; then
  curl -fsSL --retry 5 --retry-all-errors --retry-delay 10 -o "${sums}.part" \
    "https://download.blender.org/release/Blender${series}/${sums}"
  mv "${sums}.part" "${sums}"
fi

verify() {
  grep " ${archive}\$" "${sums}" | sha256sum -c -
}

if [[ -f "${archive}" ]] && verify; then
  exit 0
fi

for base in \
    https://download.blender.org/release \
    https://mirrors.ocf.berkeley.edu/blender/release \
    https://ftp.nluug.nl/pub/graphics/blender/release; do
  if curl -fsSL --retry 3 --retry-all-errors --retry-delay 10 \
        -o "${archive}" "${base}/Blender${series}/${archive}" \
      && verify; then
    exit 0
  fi
  echo "::warning::Downloading ${archive} from ${base} failed; trying the next mirror"
  rm -f "${archive}"
done
exit 1
