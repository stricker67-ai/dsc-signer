#!/bin/sh
# install.sh — install dsc-signer for the current user.
#
#   ./install.sh            venv in ~/.local/share/dsc-sign/venv, scripts in ~/.local/bin
#   PREFIX=/opt/x ./install.sh
#   PYTHON=python3.13 ./install.sh
#
# On macOS it also installs the "Sign with DSC" Quick Actions (Finder, and
# PDF Expert if present); skip them with DSC_QUICK_ACTIONS=0.
# Token drivers are NOT installed - see README.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
PREFIX=${PREFIX:-$HOME/.local}
VENV=${DSC_VENV:-$PREFIX/share/dsc-sign/venv}
PY=${PYTHON:-python3}

"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' ||
  { echo "need Python >= 3.10 (set PYTHON=...)"; exit 1; }
"$PY" -c 'import tkinter' 2>/dev/null ||
  echo "warning: $PY has no tkinter - the GUI won't start (macOS: brew install python-tk@3.13; Debian/Ubuntu: apt install python3-tk)"

[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$HERE/requirements.txt"

mkdir -p "$PREFIX/bin"
for f in dsc-sign dsc-sign-gui; do
  # point the shebang at the venv so the scripts run with their dependencies
  { echo "#!$VENV/bin/python"; tail -n +2 "$HERE/$f"; } > "$PREFIX/bin/$f"
  chmod 755 "$PREFIX/bin/$f"
done
cp "$HERE/dsc_stamp.py" "$HERE/dsc_pkcs11.py" "$PREFIX/bin/"

if [ "$(uname -s)" = Darwin ]; then
  cp "$HERE/macos/dsc-sign-pdfexpert" "$PREFIX/bin/"
  chmod 755 "$PREFIX/bin/dsc-sign-pdfexpert"
  [ "${DSC_QUICK_ACTIONS:-1}" = 0 ] ||
    "$VENV/bin/python" "$HERE/macos/make_quick_actions.py" "$PREFIX/bin/dsc-sign-pdfexpert"
fi

for tool in pdftoppm gs ocrmypdf; do
  command -v "$tool" >/dev/null 2>&1 || case $tool in
    pdftoppm) echo "warning: pdftoppm missing - the GUI page preview needs poppler (brew/apt install poppler / poppler-utils)";;
    gs)       echo "note: ghostscript missing - only needed for --compress";;
    ocrmypdf) echo "note: ocrmypdf missing - only needed for --ocr";;
  esac
done

echo
echo "Installed to $PREFIX/bin. Check the token driver with:"
echo "  $VENV/bin/python $PREFIX/bin/dsc_pkcs11.py"
