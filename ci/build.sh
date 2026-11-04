#!/usr/bin/env bash
# Builds the native library for one runtime, wraps it in a wheel and tests the installed wheel.
#   ci/build.sh <dotnet RID> <wheel platform tag> [python]
# The platform tag "auto-macos" reads the minimum macOS version from the library itself.
set -euo pipefail
rid="$1"
platform="$2"
python="${3:-python3}"
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

case "$rid" in
  win-*) lib=pdfpecker_native.dll ;;
  osx-*) lib=pdfpecker_native.dylib ;;
  *) lib=pdfpecker_native.so ;;
esac

dotnet publish native/PdfPecker.Native.csproj -c Release -r "$rid" -o "native/bin/publish/$rid"
rm -f src/pdfpecker/pdfpecker_native.*
cp "native/bin/publish/$rid/$lib" src/pdfpecker/

if [[ "$platform" == auto-macos ]]; then
  minos=$(otool -l "src/pdfpecker/$lib" | awk '/LC_BUILD_VERSION/{f=1} f&&/minos/{print $2; exit}')
  arch=$([[ "$rid" == osx-arm64 ]] && echo arm64 || echo x86_64)
  platform="macosx_${minos%%.*}_0_${arch}"
  echo "The library needs macOS $minos or later: $platform"
fi

if [[ "$platform" == manylinux_* ]]; then
  # The wheel tag promises a glibc version; the library must not need a newer one.
  wanted="${platform#manylinux_}"; wanted="${wanted%_*}"; wanted="${wanted/_/.}"
  needed=$(objdump -T "src/pdfpecker/$lib" | grep -o 'GLIBC_[0-9.]*' | sed 's/GLIBC_//' | sort -V | tail -1)
  echo "The library needs glibc $needed; the tag allows $wanted"
  [[ "$(printf '%s\n%s\n' "$needed" "$wanted" | sort -V | tail -1)" == "$wanted" ]]
fi

rm -rf dist build
"$python" -m pip install --quiet build
PDFPECKER_WHEEL_PLATFORM="$platform" "$python" -m build --wheel --outdir dist .
ls -l dist

# Test the installed wheel, not the source tree, in a fresh virtual environment.
venv="$(mktemp -d)/venv"
"$python" -m venv "$venv"
if [[ -x "$venv/Scripts/python.exe" ]]; then vpython="$venv/Scripts/python.exe"; else vpython="$venv/bin/python"; fi
"$vpython" -m pip install --quiet pytest dist/*.whl
rm -f src/pdfpecker/pdfpecker_native.*
(cd tests && PDFPECKER_TEST_INSTALLED=1 "$vpython" -m pytest -q)
