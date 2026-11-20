import numpy as np
from PIL import Image, ImageFilter
import sys, os
D = sys.argv[1]; rng = np.random.default_rng(13)
# animated grain tile (grayscale noise around mid-gray, for overlay blend)
g = rng.normal(128, 38, (2100, 1200)).clip(0, 255).astype(np.uint8)
Image.fromarray(g, 'L').save(f'{D}/grain.png')
# aged paper texture (for multiply blend): blotches + fibers
h, w = 1920, 1080
base = np.ones((h, w), np.float32)
for scale, amp in ((240, .10), (90, .06), (30, .035)):
    small = rng.random((h // scale + 2, w // scale + 2)).astype(np.float32)
    im = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    base -= amp * (np.asarray(im, np.float32) / 255.0)
fib = Image.fromarray((rng.random((h, w)) > .9985).astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(1.2))
base -= .25 * np.asarray(fib, np.float32) / 255.0
# edge darkening
yy, xx = np.mgrid[0:h, 0:w]
d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
base -= .18 * np.clip(d - .6, 0, 1)
paper = np.array([232, 220, 192], np.float32)
rgb = (base[..., None] * paper).clip(0, 255).astype(np.uint8)
Image.fromarray(rgb, 'RGB').save(f'{D}/paper.png')
print('ok')
