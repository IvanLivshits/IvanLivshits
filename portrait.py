#!/usr/bin/env python3
"""Draw a photo as ASCII art into ascii.txt.

    python3 portrait.py                 # uses the GitHub avatar of LOGIN in generate.py
    python3 portrait.py me.jpg          # or any local photo
    python3 portrait.py --preview p.png # also save a rendered preview

Needs: pip install pillow "rembg[cpu]" "opencv-python-headless<4.11",
and the DejaVu Sans Mono font.

Made for a dark card: bright areas of the photo become dense characters.
Each character cell is sampled as a 2x3 grid of brightness and matched against
the same grid measured on every printable ASCII glyph, so a cell that is bright
only at the bottom becomes "_" or ",", a diagonal edge becomes "/" and so on.
That keeps edges crisp where a plain brightness ramp would smear them.
The person is found with rembg and the background is removed; shadows are
lifted slightly and the silhouette gets a faint rim, so dark hair does not
dissolve into the dark card. The eye area (found with OpenCV) gets its own
tone curve, otherwise the sockets turn into a dark smudge.

With --if-changed the avatar's hash is compared with avatar.sha256 and nothing
is done when it is the same, so the daily workflow only redraws after the
avatar is replaced.
"""
import argparse
import hashlib
import io
import os
import sys
import urllib.request

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
CHARS = "".join(chr(i) for i in range(32, 127))
SX, SY = 2, 3            # brightness samples per character cell
COLS, ROWS = 84, 50      # keep in sync with the card height in generate.py


def avatar_bytes():
    sys.path.insert(0, HERE)
    from generate import LOGIN
    req = urllib.request.Request(f"https://github.com/{LOGIN}.png?size=1000",
                                 headers={"User-Agent": "profile-card"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def subject_mask(img):
    """Person = white, background = black."""
    from rembg import new_session, remove
    return remove(img, session=new_session("u2net_human_seg"), only_mask=True).convert("L")


def eye_box(img):
    """Box around both eyes and brows in image pixels, or None if no face is found."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    g = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    h, w = g.shape
    faces = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml") \
        .detectMultiScale(g, 1.1, 6, minSize=(w // 6, h // 6))
    if len(faces) == 0:
        return None
    fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
    eyes = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml") \
        .detectMultiScale(g[fy:fy + fh * 6 // 10, fx:fx + fw], 1.1, 8, minSize=(fw // 8, fw // 8))
    if len(eyes) < 2:
        return None
    eyes = sorted(eyes, key=lambda e: -e[2] * e[3])[:2]
    l = fx + min(e[0] for e in eyes)
    r = fx + max(e[0] + e[2] for e in eyes)
    t = fy + min(e[1] for e in eyes)
    b = fy + max(e[1] + e[3] for e in eyes)
    return (int(l - (r - l) * 0.06), int(t - (b - t) * 0.05), int(r + (r - l) * 0.06), int(b - (b - t) * 0.05))


def clean_eyes(grey, box):
    """Inside the eye box push skin tones up to white, so only the brows,
    lash lines and irises stay dark instead of the whole socket going muddy."""
    region = grey.crop(box)
    hist = region.histogram()
    total, acc, lo, hi = sum(hist), 0, 0, 255
    for i, n in enumerate(hist):
        acc += n
        if acc < total * 0.04:
            lo = i
        if acc < total * 0.55:
            hi = i
    hi = max(hi, lo + 1)
    lut = [int(255 * min(1.0, max(0.0, (v - lo) / (hi - lo))) ** 1.25) for v in range(256)]
    region = region.point(lut).filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=0))
    feather = Image.new("L", grey.size, 0)
    pad = max(2, (box[3] - box[1]) // 8)
    ImageDraw.Draw(feather).rectangle((box[0] + pad, box[1] + pad, box[2] - pad, box[3] - pad), fill=255)
    out = grey.copy()
    out.paste(region, box[:2])
    return Image.composite(out, grey, feather.filter(ImageFilter.GaussianBlur(pad / 2)))


def crop_box(mask, aspect):
    """Head-and-shoulders box of the given width/height ratio around the person."""
    w, h = mask.size
    bbox = mask.point(lambda v: 255 if v > 128 else 0).getbbox() or (0, 0, w, h)
    top = max(0, bbox[1] - int(h * 0.04))
    ch = min(h - top, int(h * 0.85))
    cw = min(w, int(ch * aspect))
    # centre on the head: the mask's centre of mass in the top third of the person
    band = mask.crop((0, bbox[1], w, bbox[1] + max(1, (bbox[3] - bbox[1]) // 3))).resize((w, 1), Image.BOX)
    col = list(band.getdata())
    cx = sum(i * v for i, v in enumerate(col)) / (sum(col) or 1) if sum(col) else w / 2
    left = int(max(0, min(w - cw, cx - cw / 2)))
    return (left, top, left + cw, top + ch)


def glyph_vectors():
    """Ink coverage of every glyph on the SX x SY grid, each sample scaled to 0..1."""
    k = 8
    cw, ch = 6 * k, 12 * k + 4
    font = ImageFont.truetype(FONT, round(cw / 0.602))
    vecs = {}
    for c in CHARS:
        im = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(im).text((0, ch * 0.08), c, font=font, fill=255)
        im = im.filter(ImageFilter.GaussianBlur(k * 0.9)).resize((SX, SY), Image.BOX)
        vecs[c] = [v / 255 for v in im.getdata()]
    top = [max(v[i] for v in vecs.values()) or 1 for i in range(SX * SY)]
    return {c: [v[i] / top[i] for i in range(SX * SY)] for c, v in vecs.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo", nargs="?", help="local photo; default: the GitHub avatar")
    ap.add_argument("--if-changed", action="store_true", help="skip when the avatar is the one already drawn")
    ap.add_argument("--local", type=int, default=110, help="local contrast, percent")
    ap.add_argument("--bg", type=float, default=0.0, help="background brightness, 0..1 (0 = removed)")
    ap.add_argument("--floor", type=float, default=0.14, help="darkest tone on the person, 0..1")
    ap.add_argument("--rim", type=float, default=0.45, help="brightness of the silhouette outline, 0..1")
    ap.add_argument("--contrast", type=float, default=1.7, help="edge emphasis inside a cell")
    ap.add_argument("--out", default=os.path.join(HERE, "ascii.txt"))
    ap.add_argument("--preview", help="save a rendered preview PNG here")
    a = ap.parse_args()

    if a.photo:
        with open(a.photo, "rb") as f:
            data = f.read()
    else:
        data = avatar_bytes()
    digest = hashlib.sha256(data).hexdigest()
    seen = os.path.join(HERE, "avatar.sha256")
    if a.if_changed and os.path.exists(seen) and open(seen).read().strip() == digest:
        print("avatar unchanged, keeping ascii.txt")
        return

    img = Image.open(io.BytesIO(data)).convert("RGB")
    mask = subject_mask(img)
    box = crop_box(mask, (COLS * 0.6) / (ROWS * 1.25))  # a cell is 0.6 wide per 1.25 tall
    size = (COLS * 8, ROWS * 16)

    grey = ImageOps.grayscale(img).crop(box).resize(size, Image.LANCZOS)
    grey = ImageOps.autocontrast(grey, cutoff=1)
    grey = grey.filter(ImageFilter.UnsharpMask(radius=28, percent=a.local, threshold=0))  # local contrast
    grey = grey.filter(ImageFilter.UnsharpMask(radius=3, percent=80, threshold=1))        # crisp edges
    eyes = eye_box(img)
    if eyes:  # same box in working-image coordinates
        kx, ky = size[0] / (box[2] - box[0]), size[1] / (box[3] - box[1])
        eyes = (max(0, round((eyes[0] - box[0]) * kx)), max(0, round((eyes[1] - box[1]) * ky)),
                min(size[0], round((eyes[2] - box[0]) * kx)), min(size[1], round((eyes[3] - box[1]) * ky)))
        if eyes[2] > eyes[0] and eyes[3] > eyes[1]:
            grey = clean_eyes(grey, eyes)
            print("eyes: cols %d-%d, rows %d-%d" % (eyes[0] // 8, eyes[2] // 8, eyes[1] // 16, eyes[3] // 16))
    mask = mask.crop(box).resize(size, Image.LANCZOS)
    hard = mask.point(lambda v: 255 if v > 128 else 0)
    # the background is dropped, so nothing on the person may be fully black:
    # lift the shadows a little and trace the silhouette with a faint rim
    lo = int(255 * a.floor)
    grey = grey.point(lambda v: lo + v * (255 - lo) // 255)
    rim = ImageChops.subtract(hard, hard.filter(ImageFilter.MinFilter(9))).filter(ImageFilter.GaussianBlur(2))
    grey = ImageChops.lighter(grey, rim.point(lambda v: int(v * a.rim)))
    grey = Image.composite(grey, grey.point(lambda v: int(v * a.bg)), mask.filter(ImageFilter.GaussianBlur(3)))

    px = grey.resize((COLS * SX, ROWS * SY), Image.BOX).load()
    cover = hard.resize((COLS, ROWS), Image.BOX).load()
    table = glyph_vectors()
    lines = []
    for r in range(ROWS):
        row = ""
        for c in range(COLS):
            if a.bg == 0 and cover[c, r] < 60:
                row += " "
                continue
            v = [px[c * SX + x, r * SY + y] / 255 for y in range(SY) for x in range(SX)]
            m = max(v)
            if m > 0:  # exaggerate differences inside the cell so edges pick shaped glyphs
                v = [(t / m) ** a.contrast * m for t in v]
            row += min(table, key=lambda ch: sum((p - q) ** 2 for p, q in zip(v, table[ch])))
        lines.append(row.rstrip())
    with open(a.out, "w") as f:
        f.write("\n".join(lines) + "\n")
    if not a.photo:
        with open(seen, "w") as f:
            f.write(digest + "\n")
    print(f"wrote {a.out}: {COLS}x{ROWS}")

    if a.preview:
        fs = 8.8
        font = ImageFont.truetype(FONT, fs)
        im = Image.new("RGB", (int(COLS * fs * 0.6) + 24, int(ROWS * fs * 1.25) + 24), "#161b22")
        d = ImageDraw.Draw(im)
        for i, l in enumerate(lines):
            for j, ch in enumerate(l):
                if ch != " ":
                    d.text((12 + j * fs * 0.6, 12 + i * fs * 1.25), ch, font=font, fill="#c9d1d9")
        im.save(a.preview)


if __name__ == "__main__":
    main()
