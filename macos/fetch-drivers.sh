#!/bin/zsh
# fetch-drivers.sh — optional: get the HYP2003 token drivers for macOS from
# Hypersecu's official package, verify them, and set them up.
#
#   macos/fetch-drivers.sh                   download + verify; install the PKCS#11
#                                            module for this user (no sudo); stage the
#                                            reader driver and print the sudo steps
#   macos/fetch-drivers.sh --install-reader  ...and also install the reader driver,
#                                            set useIFDCCID and restart the smart-card
#                                            daemons (asks for your password and for
#                                            you to unplug/replug the token)
#   macos/fetch-drivers.sh --uninstall-reader  undo the reader-driver part
#
# Options: --zip PATH   use an already-downloaded HYP2003-MAC-iOS.zip
#          --dry-run    print the sudo commands instead of running them
#
# Nothing from the vendor package is executed: its installer, scripts, launch
# agent and apps are skipped. Only two signed files are copied out of it, and
# only after the package and both files pass Feitian/Apple signature checks.
set -euo pipefail
# System tools only: Homebrew's GNU coreutils (mktemp, stat, ...) take different flags.
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

URL='https://www.hypersecu.com/_files/archives/5aae8d_455153f9dcfa4f98a57824244cc520a3.zip?dn=HYP2003-MAC-iOS.zip'
ZIP_SHA256=a57a1efb7d278fd0e8ca8bf9803faf7b6cd804e789f443e71aa06cf6105cca62   # HYP2003-MAC-iOS.zip, Feb 2025 build
TEAM=S47T4UESP3                                                                # FEITIAN Technologies Co.,Ltd.
REQ="anchor apple generic and certificate leaf[subject.OU] = \"$TEAM\""

LIB_DIR="$HOME/.local/lib"
CONF_DIR="$HOME/.config/dsc-sign"
STAGE="$HOME/.local/share/dsc-sign/drivers"
DRIVERS=/usr/local/libexec/SmartCardServices/drivers
BUNDLE=ifd-FeiTccid.bundle
PREF=/Library/Preferences/com.apple.security.smartcard

mode=user zip="" dry=0
while (( $# )); do
  case $1 in
    --install-reader)   mode=reader ;;
    --uninstall-reader) mode=uninstall ;;
    --zip)              zip=$2; shift ;;
    --dry-run)          dry=1 ;;
    -h|--help)          sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)                  print -u2 "unknown option: $1"; exit 2 ;;
  esac
  shift
done

say()  { print -P "%B==>%b $*"; }
die()  { print -u2 -P "%F{red}error:%f $*"; exit 1; }
root() { if (( dry )); then print "  sudo $*"; else sudo "$@"; fi; }
reader_name() { system_profiler SPSmartCardsDataType 2>/dev/null | awk '/Readers:/{f=1; next} f && /#01:/{sub(/.*#01: /,""); sub(/ \(ATR.*/,""); print; exit}'; }

[[ $(uname -s) == Darwin ]] || die "macOS only"

restart_daemons() {
  print
  print -P "%BUnplug the token now%b, then press Return."; (( dry )) || read -r _
  root killall -9 usbsmartcardreaderd com.apple.ifdreader || true
  print -P "%BPlug the token back in%b, wait a few seconds, then press Return."; (( dry )) || read -r _
}

if [[ $mode == uninstall ]]; then
  say "removing the Feitian reader driver and the useIFDCCID preference"
  root rm -rf "$DRIVERS/$BUNDLE"
  root defaults delete "$PREF" useIFDCCID 2>/dev/null || true
  restart_daemons
  say "done - macOS's built-in reader driver is back in charge"
  exit 0
fi

work=$(mktemp -d -t dsc-drivers)
mnt="$work/mnt"
trap 'hdiutil detach -quiet "$mnt" 2>/dev/null || true; rm -rf "$work"' EXIT

# 1. Get the official archive and check it is the exact build this was tested with.
if [[ -z $zip ]]; then
  say "downloading HYP2003-MAC-iOS.zip from hypersecu.com"
  zip="$work/HYP2003-MAC-iOS.zip"
  curl -fL --proto '=https' --tlsv1.2 --retry 2 -o "$zip" "$URL" || die "download failed"
fi
[[ -f $zip ]] || die "no such file: $zip"
sum=$(/usr/bin/shasum -a 256 "$zip" | cut -d' ' -f1)
if [[ $sum != $ZIP_SHA256 ]]; then
  die "SHA-256 mismatch for $zip
  expected $ZIP_SHA256
  got      $sum
Hypersecu may have published a newer build. Nothing was installed. If you trust the
new file, verify it yourself (pkgutil --check-signature) and follow the README by hand."
fi
say "archive SHA-256 OK"

# 2. Unpack zip -> dmg -> pkg (nothing is executed) and verify the installer signature.
/usr/bin/ditto -x -k "$zip" "$work/zip"
dmg=$(print -l "$work"/zip/**/*.dmg(N) | head -1); [[ -n $dmg ]] || die "no .dmg inside the archive"
mkdir -p "$mnt"; hdiutil attach -quiet -nobrowse -readonly -mountpoint "$mnt" "$dmg" || die "cannot mount $dmg"
pkg=$(print -l "$mnt"/*.pkg(N) | head -1); [[ -n $pkg ]] || die "no .pkg inside the disk image"
pkgutil --check-signature "$pkg" | grep -q "Developer ID Installer: .*($TEAM)" || die "installer is not signed by Feitian ($TEAM)"
pkgutil --check-signature "$pkg" | grep -q "trusted by the Apple notary service" || die "installer is not notarized"
say "installer signed by Feitian ($TEAM) and notarized by Apple"
pkgutil --expand-full "$pkg" "$work/pkg" >/dev/null

lib="$work/pkg/pkcs11.pkg/Payload/libcastle_v2.1.0.0.dylib"
rdr="$work/pkg/kext.pkg/Payload/$BUNDLE"
[[ -f $lib && -d $rdr ]] || die "package layout changed - expected pkcs11.pkg and kext.pkg payloads"
for f in "$lib" "$rdr"; do
  codesign --verify --strict -R="$REQ" "$f" 2>/dev/null || die "${f:t} is not validly signed by Feitian ($TEAM)"
done
file "$lib" | grep -qw arm64 || die "${lib:t} has no arm64 slice"
say "PKCS#11 module and reader driver both carry valid Feitian signatures"

# 3. PKCS#11 module: per-user, no sudo.
mkdir -p "$LIB_DIR" "$CONF_DIR" "$STAGE"
/usr/bin/ditto "$lib" "$LIB_DIR/${lib:t}"
print -r -- "$LIB_DIR/${lib:t}" > "$CONF_DIR/pkcs11_path"
say "PKCS#11 module -> $LIB_DIR/${lib:t}"

# 4. Reader driver: staged for the user; installed system-wide only on request.
rm -rf "$STAGE/$BUNDLE"; /usr/bin/ditto "$rdr" "$STAGE/$BUNDLE"
say "reader driver staged -> $STAGE/$BUNDLE"

if [[ $mode != reader ]]; then
  cat <<EOF

Reading certificates works now. Signing on macOS also needs the reader driver.
Re-run with --install-reader, or do it by hand:

  sudo mkdir -p $DRIVERS
  sudo ditto "$STAGE/$BUNDLE" "$DRIVERS/$BUNDLE"
  sudo chown -R root:wheel "$DRIVERS/$BUNDLE"
  sudo defaults write $PREF useIFDCCID -bool yes
  # unplug the token, then:
  sudo killall -9 usbsmartcardreaderd com.apple.ifdreader
  # plug the token back in
EOF
  exit 0
fi

# 5. Reader driver: system-wide install + preference + daemon restart.
say "installing the reader driver (sudo will ask for your password)"
root mkdir -p "$DRIVERS"
root rm -rf "$DRIVERS/$BUNDLE"
root /usr/bin/ditto "$STAGE/$BUNDLE" "$DRIVERS/$BUNDLE"
root chown -R root:wheel "$DRIVERS/$BUNDLE"
root defaults write "$PREF" useIFDCCID -bool yes
restart_daemons
(( dry )) && exit 0

sleep 3
name=$(reader_name)
case $name in
  HYP2003)  say "token is on Feitian's reader driver (reader name: HYP2003) - signing should work" ;;
  "")       say "no token detected - plug it in and check: system_profiler SPSmartCardsDataType" ;;
  *)        print -P "%F{yellow}warning:%f reader is still '$name' (macOS's built-in driver)."
            print "Unplug the token, run 'sudo killall -9 usbsmartcardreaderd com.apple.ifdreader',"
            print "plug it back in - or restart the Mac." ;;
esac
