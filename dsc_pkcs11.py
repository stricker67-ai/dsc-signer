"""Locate the HYP2003 / ePass2003 PKCS#11 module across platforms.

The Linux original hardcoded /usr/lib/libcastle_v2.so.1.0.0. macOS installs the
same vendor middleware somewhere else entirely and as a Mach-O .dylib, so the
path has to be discovered rather than assumed.

Resolution order:
  1. $DSC_PKCS11_MODULE            - explicit override, always wins
  2. ~/.config/dsc-sign/pkcs11_path - remembered from a previous successful run
  3. platform candidate globs       - the usual vendor install locations

On macOS this also checks that the module's architecture matches the running
interpreter, because a PKCS#11 module is dlopen()ed into the Python process:
an x86_64 .dylib simply cannot load into an arm64 Python, and the resulting
error is otherwise cryptic.
"""

import os
import glob
import subprocess
import sys

ENV_VAR = "DSC_PKCS11_MODULE"
CONFIG_DIR = os.path.expanduser("~/.config/dsc-sign")
_REMEMBERED = os.path.join(CONFIG_DIR, "pkcs11_path")

# Globs, most-specific first. ** needs recursive=True.
_CANDIDATES = {
    "linux": [
        "/usr/lib/libcastle_v2.so.1.0.0",
        "/usr/lib/libcastle_v2.so*",
        "/usr/lib/x86_64-linux-gnu/libcastle*.so*",
        "/usr/local/lib/libcastle*.so*",
        "/usr/lib/libeTPkcs11.so",                       # Feitian ePass2003
        "/usr/lib/opensc-pkcs11.so",                     # OpenSC fallback
    ],
    "darwin": [
        # --- HyperPKI middleware (HYP2003_Mac_*.dmg) ---
        os.path.expanduser("~/.local/lib/libcastle*.dylib"),  # extracted, no installer
        "/Library/HyperPKI/**/libcastle*.dylib",
        "/Applications/HyperPKIMgr.app/Contents/**/libcastle*.dylib",
        "/Library/Frameworks/**/libcastle*.dylib",
        "/usr/local/lib/libcastle*.dylib",
        "/usr/local/lib/libcastle*.so",                  # some builds keep .so
        # --- Feitian ePass2003 (HYP2003 is this hardware; often newer/arm64) ---
        "/Library/Frameworks/**/libeTPkcs11*.dylib",
        "/usr/local/lib/libeTPkcs11*.dylib",
        "/Library/Application Support/**/libeTPkcs11*.dylib",
        # --- OpenSC, last resort (may or may not drive this token) ---
        "/Library/OpenSC/lib/opensc-pkcs11.so",
        "/opt/homebrew/lib/opensc-pkcs11.so",
        "/usr/local/lib/opensc-pkcs11.so",
    ],
}


def _platform_key():
    if sys.platform.startswith("darwin"):
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    return None


def module_archs(path):
    """Architectures a Mach-O/ELF module provides, e.g. ['arm64'] or ['x86_64']."""
    try:
        out = subprocess.run(["lipo", "-archs", path],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.split()
    except Exception:
        pass
    try:
        out = subprocess.run(["file", "-b", path],
                             capture_output=True, text=True, timeout=10)
        return [out.stdout.strip()] if out.returncode == 0 else []
    except Exception:
        return []


def interpreter_arch():
    import platform
    return platform.machine()


def check_arch(path):
    """Return (ok, message). On a mismatch the module cannot be dlopen()ed."""
    if not sys.platform.startswith("darwin"):
        return True, ""
    archs = module_archs(path)
    me = interpreter_arch()
    if not archs:
        return True, ""
    norm = " ".join(archs).lower()
    if me == "arm64" and "arm64" not in norm:
        return False, (
            f"Architecture mismatch: module is [{' '.join(archs)}] but Python is "
            f"arm64.\nA PKCS#11 module is loaded INTO this process, so it must "
            f"match.\nFix: run under an x86_64 Python via Rosetta, e.g.\n"
            f"    arch -x86_64 /usr/local/bin/python3 {sys.argv[0]}\n"
            f"or install an arm64-native driver (try the Feitian ePass2003 build)."
        )
    if me == "x86_64" and "x86_64" not in norm and "i386" not in norm:
        return False, (f"Architecture mismatch: module is [{' '.join(archs)}] "
                       f"but Python is x86_64.")
    return True, ""


def _remember(path):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(_REMEMBERED, "w") as fh:
            fh.write(path)
    except Exception:
        pass


def candidates():
    """Every existing module found, in preference order (no side effects)."""
    key = _platform_key()
    found, seen = [], set()
    for pattern in _CANDIDATES.get(key, []):
        for hit in sorted(glob.glob(pattern, recursive=True)):
            if os.path.isfile(hit) and hit not in seen:
                seen.add(hit)
                found.append(hit)
    return found


def find_module(explicit=None, strict=True):
    """Return a usable PKCS#11 module path, or raise RuntimeError explaining why not."""
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        raise RuntimeError(f"PKCS#11 module not found at {explicit}")

    env = os.environ.get(ENV_VAR)
    if env:
        if os.path.isfile(env):
            return env
        raise RuntimeError(f"${ENV_VAR} points at a missing file: {env}")

    if os.path.isfile(_REMEMBERED):
        try:
            prev = open(_REMEMBERED).read().strip()
            if prev and os.path.isfile(prev):
                return prev
        except Exception:
            pass

    hits = candidates()
    if not hits:
        raise RuntimeError(_not_found_help())

    for hit in hits:
        ok, _ = check_arch(hit)
        if ok:
            _remember(hit)
            return hit

    # All found, none loadable on this arch - report the first properly.
    ok, msg = check_arch(hits[0])
    raise RuntimeError(f"Found {hits[0]} but it is unusable.\n{msg}")


def _not_found_help():
    if _platform_key() == "darwin":
        return (
            "No PKCS#11 module found for the HYP2003 token on this Mac.\n\n"
            "Get the vendor middleware first (see README, 'macOS setup'):\n"
            "  - Hypersecu HYP2003-India_20250213.dmg (universal arm64 + x86_64,\n"
            "    Feitian-signed, notarized); copy libcastle_v2.1.0.0.dylib out of\n"
            "    its pkcs11.pkg, e.g. to ~/.local/lib/\n"
            "  - older ePass2003-India-2021 builds are x86_64-only and link the\n"
            "    removed libstdc++ - they do not load on current macOS\n\n"
            f"Then point this at the .dylib explicitly:\n"
            f"  export {ENV_VAR}=/path/to/libcastle.dylib\n\n"
            "To locate it after installing:\n"
            "  sudo find / -name 'libcastle*' -o -name 'libeTPkcs11*' 2>/dev/null"
        )
    return ("No PKCS#11 module found. Install the vendor middleware, or set "
            f"${ENV_VAR} to its path.")


if __name__ == "__main__":
    print(f"platform    : {sys.platform} ({interpreter_arch()})")
    print(f"python      : {sys.executable}")
    hits = candidates()
    print(f"candidates  : {len(hits)}")
    for h in hits:
        ok, msg = check_arch(h)
        print(f"  {'OK ' if ok else 'BAD'} {h}  archs={module_archs(h)}")
        if not ok:
            print("      " + msg.replace("\n", "\n      "))
    try:
        print(f"\nselected    : {find_module()}")
    except RuntimeError as exc:
        print(f"\nNOT RESOLVED:\n{exc}")
