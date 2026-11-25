"""Read relative brightness from a photographed display test image."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from image_lab.validation import integer, number

from .photo import decode, pixels, png, MAX_IMAGE_BYTES


LUMA = np.array([0.2126, 0.7152, 0.0722])


def settings(value, size):
    width, height = size
    left = integer(value.get("left"), "左界 X", 0, width - 1)
    top = integer(value.get("top"), "上界 Y", 0, height - 1)
    return {
        "left": left, "right": integer(value.get("right"), "右界 X", left, width - 1),
        "top": top, "bottom": integer(value.get("bottom"), "下界 Y", top, height - 1),
        "focus": integer(value.get("focus"), "截线 X", 0, width - 1),
        "ref_x": integer(value.get("ref_x"), "参考点 X", 0, width - 1),
        "ref_y": integer(value.get("ref_y"), "参考点 Y", 0, height - 1),
        "limit": number(value.get("limit"), "偏差限值", 0.1, 255),
    }


def defaults(size):
    width, height = size
    return settings({
        "left": width // 6, "right": width * 5 // 6, "top": height // 4, "bottom": height * 3 // 4,
        "focus": width // 2, "ref_x": width // 3, "ref_y": height // 2, "limit": 8,
    }, size)


def classify(delta, limit):
    if delta > limit:
        return "bright"
    if delta < -limit:
        return "dark"
    return "within"


def point(image, x, y, config):
    rgb = image[y, x]
    brightness = float(rgb @ LUMA)
    reference = float(image[config["ref_y"], config["ref_x"]] @ LUMA)
    inside = config["left"] <= x <= config["right"] and config["top"] <= y <= config["bottom"]
    delta = brightness - reference
    return {
        "x": x, "y": y, "rgb": rgb.tolist(), "brightness": brightness, "delta": delta,
        "classification": classify(delta, config["limit"]) if inside else None,
    }


def profile(image, config):
    x = config["focus"]
    if not config["left"] <= x <= config["right"]:
        return []
    return [point(image, x, y, config) for y in range(config["top"], config["bottom"] + 1)]


def coverage(image, config):
    x0, x1, y0, y1 = (config[key] for key in ("left", "right", "top", "bottom"))
    sample = image[y0 : y1 + 1, x0 : x1 + 1] @ LUMA
    delta = sample - float(image[config["ref_y"], config["ref_x"]] @ LUMA)
    means = sample.mean(axis=0)
    bright = np.count_nonzero(delta > config["limit"], axis=0)
    dark = np.count_nonzero(delta < -config["limit"], axis=0)
    return [
        {"x": x, "brightness": float(mean), "bright": int(above), "dark": int(below)}
        for x, mean, above, below in zip(range(x0, x1 + 1), means, bright, dark)
    ]


def report(image, config):
    rows = profile(image, config)
    reference = point(image, config["ref_x"], config["ref_y"], config)
    distribution = coverage(image, config)
    reading = None
    if rows:
        column = distribution[config["focus"] - config["left"]]
        reading = {
            "mean_luma": column["brightness"], "delta_mean": column["brightness"] - reference["brightness"],
            "bright": column["bright"], "dark": column["dark"], "rows": len(rows),
        }
    return {"reading": reading, "reference": reference, "profile": rows, "coverage": distribution,
            "focus": config["focus"]}


def practice():
    width, height = 766, 482
    cfg = settings({"left": 133, "right": 625, "top": 131, "bottom": 341, "focus": 274,
                    "ref_x": 207, "ref_y": 170, "limit": 8}, (width, height))
    y, x = np.indices((height, width))
    panel = (82 <= x) & (x <= 688) & (70 <= y) & (y <= 405)
    base = 132 + (x - 200) * 0.012 + (y - 240) * 0.012
    texture = 0.8 * np.sin(x * 0.37 + y * 0.47) + 0.55 * np.sin(x * 0.94 - y * 0.07)
    hotspot = 34 * np.exp(-((x - 484)**2 / 55**2 + (y - 247)**2 / 69**2))
    corner = -26 * np.exp(-((x - 161)**2 / 78**2 + (y - 328)**2 / 59**2))
    narrow = -8 * np.exp(-((y - 274) / 4)**2) * np.exp(-((x - 346) / 60)**2)
    luminance = base + texture + hotspot + corner + narrow
    display = luminance[..., None] + np.array([-2, 0, 4])
    outer = np.broadcast_to(np.array([28, 34, 41]), display.shape)
    color = np.where(panel[..., None], display, outer)
    photo = Image.fromarray(color.clip(0, 255).astype("uint8"), "RGB")
    draw = ImageDraw.Draw(photo)
    draw.rounded_rectangle((80, 68, 690, 407), radius=9, outline="#12171d", width=3)
    draw.text((98, 37), "STATIC GRAY PATCH / SCREEN LAB SAMPLE", fill="#bbc7d2", font=ImageFont.load_default(size=13))
    draw.text((96, 435), "SIMULATED SCREEN PHOTO", fill="#97a9b7", font=ImageFont.load_default(size=12))
    draw.ellipse((677,430,682,435),fill="#9ed4ab")
    return photo.size, png(photo), cfg
