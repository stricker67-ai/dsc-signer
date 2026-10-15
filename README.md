# dsc-signer

Sign PDFs with an Indian Class-3 DSC USB token on **Linux and Apple Silicon macOS**: a command-line tool, a GUI with drag-to-place signature boxes, optional company seal / signatory-block stamps, and Finder / PDF Expert integration on the Mac.

Signatures are standard PAdES-style PDF signatures made with [pyHanko](https://github.com/MatthiasValvekens/pyHanko) through the token's PKCS#11 module. They validate in Adobe Acrobat and other readers once the Indian CCA root is trusted.

> Tested with a **Hypersecu HYP2003** token (Feitian ePass2003 family, USB `2ccf:080a`) carrying IDSign and eMudhra Class-3 certificates, on Ubuntu and on macOS 27 (Apple Silicon). Other tokens may work through their own PKCS#11 module (`DSC_PKCS11_MODULE`), but are untested.

## Features

- **`dsc-sign`** (CLI): sign the last page, all pages or chosen pages. It can also compress (Ghostscript) or OCR (OCRmyPDF) before signing.
- **`dsc-sign-gui`** (Tk GUI):
  - page preview, drag/resize the signature box, batch-sign several PDFs, PIN entry;
  - optional second signature on the same page;
  - **Same position on all pages**: place the box once, and it is used on every page of every open document.
- **Stamps**: overlay a round company seal and/or a signatory block before signing, so the artwork is covered by the signature. With the signatory block, the DSC appearance lands inside its blank "(Signature)" band.
- **macOS Quick Actions**:
  - Finder: right-click PDFs → *Quick Actions → Sign with DSC*.
  - PDF Expert: *PDF Expert → Services → Sign with DSC* signs the open document, then opens the signed copy.
- **PKCS#11 discovery**: finds the vendor module on Linux and macOS, and checks that its CPU architecture matches Python (arm64 vs x86_64).

The PIN is only ever passed to the token. Nothing is stored and nothing is sent over the network.

## Install

```sh
git clone https://github.com/stricker67-ai/dsc-signer.git
cd dsc-signer
./install.sh          # venv in ~/.local/share/dsc-sign/venv, scripts in ~/.local/bin
```

Requirements:
- **Python 3.10+ with Tk.** On macOS: `brew install python@3.13 python-tk@3.13` and `PYTHON=python3.13 ./install.sh`. On Debian/Ubuntu: `apt install python3-venv python3-tk`.
- **poppler,** for the GUI page preview: `brew install poppler` or `apt install poppler-utils`.
- **Optional:** `ghostscript` (for `--compress`) and `ocrmypdf` (for `--ocr`).
- **The token's PKCS#11 driver,** which is not included. See below.

Check that the driver is found:

```sh
~/.local/share/dsc-sign/venv/bin/python ~/.local/bin/dsc_pkcs11.py
```

### Linux setup

Install Hypersecu's Linux middleware for the HYP2003. It provides `/usr/lib/libcastle_v2.so*`, which is picked up automatically. Any other location can be set with `export DSC_PKCS11_MODULE=/path/to/module.so`.

### macOS setup (Apple Silicon)

The macOS setup needs three things, all from Hypersecu's official macOS package.

**1. Get the package.** Hypersecu's download page only shows Windows. The macOS build is `HYP2003-MAC-iOS.zip` on their file archive:
`https://www.hypersecu.com/_files/archives/5aae8d_455153f9dcfa4f98a57824244cc520a3.zip?dn=HYP2003-MAC-iOS.zip`
It contains `HYP2003-India_20250213.dmg`, which is universal (arm64 + x86_64), Developer ID-signed by Feitian and notarized by Apple. Indian CAs such as XtraTrust mirror the same file. Older `ePass2003-India-2021` builds are x86_64-only and link the removed `libstdc++`, so they don't load on current macOS.

You don't need to run the installer. Expand the package and take the two pieces you need:

```sh
hdiutil attach -nobrowse -readonly HYP2003-India_20250213.dmg
pkgutil --expand-full "/Volumes/<volume>/HYP2003-India_20250213.pkg" ~/hyp2003-pkg
hdiutil detach "/Volumes/<volume>"

mkdir -p ~/.local/lib
cp ~/hyp2003-pkg/pkcs11.pkg/Payload/libcastle_v2.1.0.0.dylib ~/.local/lib/
codesign -dv ~/.local/lib/libcastle_v2.1.0.0.dylib   # Authority: Developer ID Application: FEITIAN Technologies
echo "$HOME/.local/lib/libcastle_v2.1.0.0.dylib" > ~/.config/dsc-sign/pkcs11_path
```

With only the PKCS#11 module, the token **reads** fine: certificates list and the PIN is accepted. But **signing fails** with `pkcs11.exceptions.DeviceError`. The next two steps fix that.

**2. Install Feitian's reader driver.** The RSA-2048 sign command is a 298-byte *extended* APDU. macOS's built-in CCID driver rejects it, and the PKCS#11 module reports this as `CKR_DEVICE_ERROR`. At the PC/SC level it shows up as `SCardTransmit → 0x80100016 (SCARD_E_NOT_TRANSACTED)`. Feitian's CCID driver, from the same package, lists this token and handles it:

```sh
sudo mkdir -p /usr/local/libexec/SmartCardServices/drivers
sudo ditto ~/hyp2003-pkg/kext.pkg/Payload/ifd-FeiTccid.bundle \
           /usr/local/libexec/SmartCardServices/drivers/ifd-FeiTccid.bundle
sudo chown -R root:wheel /usr/local/libexec/SmartCardServices/drivers/ifd-FeiTccid.bundle
```

macOS will show a "Smart Card Reader Extension Added" notification.

**3. Let macOS use it.** Since Sonoma, Apple's own CCID driver (`usbsmartcardreaderd`) always wins over third-party drivers. Its "Can't claim interface" race is visible in the logs. Switch the preference, then restart both daemons **with the token unplugged**, because they only read the preference at startup:

```sh
sudo defaults write /Library/Preferences/com.apple.security.smartcard useIFDCCID -bool yes
# unplug the token, then:
sudo killall -9 usbsmartcardreaderd com.apple.ifdreader
# plug the token back in
```

Verify it worked:

```sh
/usr/bin/log show --last 2m --info --predicate 'process CONTAINS "usbsmartcard" OR process BEGINSWITH "com.apple.ifd"' \
  | grep -E "skipped: 0x2ccf|Using USB"
#   usbsmartcardreaderd ... new device skipped: 0x2ccf/0x080a     <- Apple's driver stepped aside
#   com.apple.ifdbundle (libccid.dylib) Using USB bus/device ...  <- Feitian's driver has the token
```

The reader name also changes from "HYPERSECU USB TOKEN" to "HYP2003".

`useIFDCCID` is global, so it affects every smart-card reader on the Mac. To undo all of this, run `sudo defaults delete /Library/Preferences/com.apple.security.smartcard useIFDCCID`, remove the bundle and replug the token.

Steps 2 and 3 are the only parts of the vendor installer that are needed. Its `kern.sysv.semume` sysctl change, launch agent and management apps can be skipped.

## Usage

```sh
dsc-sign contract.pdf                         # signs the last page -> contract_signed.pdf
dsc-sign contract.pdf --pages all
dsc-sign contract.pdf --pages 1,3 out.pdf
dsc-sign invoice.pdf --round-stamp --signatory-stamp
dsc-sign scan.pdf --compress --target-size-kb 500 --ocr
dsc-sign scan.pdf --compress --no-sign        # process only
dsc-sign-gui a.pdf b.pdf                      # GUI, batch of documents
```

The first certificate object on the token is used. Its label must match the label of its private key, which is the usual case for CA-issued tokens.

Signature appearance:
- `--stamp-mode text` (the default): "Digitally signed by … / Timestamp …".
- `--stamp-mode image`: uses an image as the appearance, `~/.config/dsc-sign/signature.png` or `$DSC_SIGNATURE_IMAGE`.

Stamp artwork is not included. Use your own PNGs (transparent background recommended):

| File | Purpose | Override |
| --- | --- | --- |
| `~/.config/dsc-sign/round.png` | round company seal (square image) | `DSC_ROUND_STAMP`, `--round-stamp-img` |
| `~/.config/dsc-sign/signatory.png` | signatory block, 1400×600 layout | `DSC_SIGNATORY_STAMP`, `--signatory-stamp-img` |
| `~/.config/dsc-sign/signature.png` | image signature appearance | `DSC_SIGNATURE_IMAGE` |

In the GUI, *Browse…* copies a chosen image into `~/.config/dsc-sign/`. If your signatory artwork has a different aspect ratio or signature band, adjust `SIGNATORY_ASPECT` and `SIGNATORY_GAP` in `dsc_stamp.py`.

To check a signed file, open it in Adobe Acrobat Reader (the Signature panel) or any reader that validates PDF signatures.

## Troubleshooting

- **`DeviceError` on macOS while reading works:** follow steps 2 and 3 above.
- **Find out exactly which card command fails:** `tools/scard_trace.c` is a small interposer that logs every PC/SC call and SysV-semaphore call the driver makes. It logs only APDU headers (`CLA INS P1 P2`) and status words, never command data, so the PIN never reaches the log.

  ```sh
  clang -arch arm64 -dynamiclib -O1 -o scard_trace.dylib tools/scard_trace.c -framework PCSC
  DSC_TRACE_LOG=$PWD/trace.log DYLD_INSERT_LIBRARIES=$PWD/scard_trace.dylib dsc-sign test.pdf
  grep -v -E -- "-> 0x00000000|sw=9000|errno=0" trace.log
  ```

  This works with Homebrew's Python, which has no hardened runtime. It does not work with Apple's `/usr/bin/python3`.
- **Smart-card daemon logs:** use `/usr/bin/log show --info --predicate 'process BEGINSWITH "com.apple.ifd" OR process CONTAINS "usbsmartcard" OR process == "ctkd"'`. Use the full path to `log`, because zsh has a `log` builtin.
- **Mind the PIN retry counter.** A wrong PIN counts against the token's lockout, so don't loop retries in scripts.

## License and disclaimer

AGPL-3.0, because the tool links PyMuPDF, which is AGPL. This project is not affiliated with Hypersecu, Feitian or any Certifying Authority. No vendor binaries are included or redistributed: get the drivers from the vendor. A digital signature is legally binding, so check where the signature boxes land before signing documents that matter.
