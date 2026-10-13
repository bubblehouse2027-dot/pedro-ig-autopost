#!/usr/bin/env python3
"""Convert media/*.png to high-quality JPEG (the Instagram API accepts JPEG only)
and warn about carousel images Instagram would reject or crop."""
import glob, os, re
from collections import defaultdict
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
converted = 0
for png in sorted(glob.glob(os.path.join(HERE, "media", "*.png"))):
    jpg = png[:-4] + ".jpg"
    if os.path.exists(jpg):
        continue
    im = Image.open(png)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.save(jpg, "JPEG", quality=95, optimize=True)
    converted += 1
    print("converted", os.path.basename(png), "->", os.path.basename(jpg))
print(converted, "image(s) converted")

groups = defaultdict(list)
for jpg in sorted(glob.glob(os.path.join(HERE, "media", "*.jpg"))):
    m = re.match(r"(P\d+)_\d+\.jpg$", os.path.basename(jpg))
    if m:
        groups[m.group(1)].append(jpg)
for post, files in groups.items():
    sizes = [Image.open(f).size for f in files]
    first = sizes[0][0] / sizes[0][1]
    for f, (w, h) in zip(files, sizes):
        r = w / h
        if not 0.8 <= r <= 1.91:
            print(f"WARNING {os.path.basename(f)}: {w}x{h} is outside Instagram's 4:5 to 1.91:1 range")
        elif abs(r - first) > 0.01:
            print(f"NOTE {os.path.basename(f)}: will be cropped to match the first image of {post}")
