"""Stamp company seal / signatory-block images onto PDF pages.

Used by both `dsc-sign` (CLI) and `dsc-sign-gui` (GUI). Stamps are applied
*before* the PDF is digitally signed, so the imagery becomes part of the
cryptographically attested content rather than an afterthought overlay.

Coordinate convention: all (x, y, w, h) tuples are in PDF points with a
top-left origin -- the same convention the GUI already uses to store the
signature box. PyMuPDF's native page coordinate system matches this.
"""

import os
import shutil

import fitz  # PyMuPDF

# Persistent stamp store: a chosen stamp is copied here so it survives even if
# the original is moved/deleted, and becomes the default next run.
# Put your own artwork at ~/.config/dsc-sign/{round,signatory,signature}.png,
# or pick it once with the GUI's Browse buttons (which copies it there).
CONFIG_DIR = os.path.expanduser("~/.config/dsc-sign")
_DEFAULT_ROUND = os.environ.get("DSC_ROUND_STAMP", os.path.join(CONFIG_DIR, "round.png"))
_DEFAULT_SIGNATORY = os.environ.get("DSC_SIGNATORY_STAMP", os.path.join(CONFIG_DIR, "signatory.png"))

# Image used as the signature appearance in "image" stamp mode (e.g. a scanned
# handwritten signature). Text mode needs no image.
SIGNATURE_IMAGE = os.environ.get("DSC_SIGNATURE_IMAGE", os.path.join(CONFIG_DIR, "signature.png"))


def save_stamp(kind, src):
    """Copy a chosen stamp image into the config folder as its persistent copy.

    `kind` is 'round' or 'signatory'. Returns the persisted config-folder path
    on success, or the original `src` if the copy fails.
    """
    dst = os.path.join(CONFIG_DIR, f"{kind}.png")
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
        return dst
    except Exception:
        return src


def _persisted(kind, default):
    """Resolve a stamp path: prefer the config-folder copy; else seed it from
    the default (copying the default in so it lives in the config folder); else
    fall back to the default path as-is."""
    dst = os.path.join(CONFIG_DIR, f"{kind}.png")
    if os.path.exists(dst):
        return dst
    if os.path.exists(default):
        return save_stamp(kind, default)
    return default


# Default stamp artwork — the config-folder copy if present (seeded from the
# $DSC_*_STAMP paths on first run), overridable via GUI browse / CLI flags.
ROUND_STAMP = _persisted("round", _DEFAULT_ROUND)
SIGNATORY_STAMP = _persisted("signatory", _DEFAULT_SIGNATORY)

# Native aspect ratios (width / height) the layout assumes for the artwork:
# a square round seal, and a 1400x600 signatory block. Adjust for your images.
ROUND_ASPECT = 1.0
SIGNATORY_ASPECT = 1400 / 600

# The blank "(Signature)" band inside the signatory stamp, expressed as
# fractions (x0, y0, x1, y1) of the stamp's bounding box -- here, between two
# ruled lines at 0.359 and 0.634 of the height. The DSC signature appearance
# is dropped into this rectangle; measure your own artwork and adjust.
SIGNATORY_GAP = (0.13, 0.38, 0.87, 0.61)


def gap_rect(box):
    """Return the '(Signature)' gap rectangle inside a signatory-stamp box.

    `box` is the signatory stamp placement (x, y, w, h) in PDF points,
    top-left origin. The returned (x, y, w, h) is where the DSC signature
    field should be created so it lands inside the blank signature band.
    """
    x, y, w, h = box
    gx0, gy0, gx1, gy1 = SIGNATORY_GAP
    return (x + gx0 * w, y + gy0 * h, (gx1 - gx0) * w, (gy1 - gy0) * h)


def apply_stamps(in_pdf, out_pdf, placements):
    """Overlay stamp images onto PDF pages and write the result.

    placements: dict mapping page index -> list of
        (image_path, x, y, w, h) tuples, PDF points, top-left origin.

    PNG transparency is preserved; `keep_proportion` keeps the artwork
    undistorted within its box. Returns the number of stamps applied.
    """
    doc = fitz.open(in_pdf)
    applied = 0
    img_xrefs = {}
    try:
        for page_idx, stamps in placements.items():
            if page_idx < 0 or page_idx >= doc.page_count:
                continue
            page = doc[page_idx]
            for image_path, x, y, w, h in stamps:
                rect = fitz.Rect(x, y, x + w, y + h)
                xref = img_xrefs.get(image_path)
                if xref is not None:
                    page.insert_image(
                        rect,
                        xref=xref,
                        keep_proportion=True,
                        overlay=True,
                    )
                else:
                    xref = page.insert_image(
                        rect,
                        filename=image_path,
                        keep_proportion=True,
                        overlay=True,
                    )
                    if xref:
                        img_xrefs[image_path] = xref
                applied += 1
        doc.save(out_pdf, deflate=True, deflate_images=True, garbage=4)
    finally:
        doc.close()
    return applied
