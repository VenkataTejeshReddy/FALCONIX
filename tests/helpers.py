import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def make_doc_image(path, size=(1400, 1000), seed=0):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    d.text((120, 100), f"CERTIFICATE {seed}", fill="black", font=font)
    for i in range(10):
        d.text((120, 220 + i * 60), f"This is to certify that Priya Sharma, roll no {seed}{i:04d}", fill="black", font=font)
    img.save(path)
    return path