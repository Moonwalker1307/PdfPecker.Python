#!/usr/bin/env bash
# Runs inside a manylinux or musllinux container: installs the .NET SDK and clang, then builds and tests the wheel
# with the oldest and the newest Python the image has.
#   ci/linux.sh <dotnet RID> <wheel platform tag>
set -euo pipefail
rid="$1"
platform="$2"
if command -v apk >/dev/null; then
  apk add --no-cache bash clang lld build-base zlib-dev libstdc++ libgcc icu-libs curl
  os=linux-musl
else
  dnf install -y clang lld zlib-devel libicu findutils binutils
  os=linux
fi
curl -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh
bash /tmp/dotnet-install.sh --channel 10.0 --os "$os" --install-dir /opt/dotnet
export PATH="/opt/dotnet:$PATH" DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
oldest=$(ls -d /opt/python/cp3*-cp3*[0-9] | sort -V | head -1)
ci/build.sh "$rid" "$platform" "$oldest/bin/python"
mkdir -p wheelhouse && cp dist/*.whl wheelhouse/
# The newest Python in the image tests the same wheel.
newest=$(ls -d /opt/python/cp3*-cp3*[0-9] | sort -V | tail -1)
venv=$(mktemp -d)/venv
"$newest/bin/python" -m venv "$venv"
"$venv/bin/python" -m pip install --quiet pytest wheelhouse/*.whl
(cd tests && PDFPECKER_TEST_INSTALLED=1 "$venv/bin/python" -m pytest -q)
