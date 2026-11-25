"""Read relative brightness against locally interpolated reference points."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from image_lab.validation import Invalid, integer, list_value, number

from .photo import decode, pixels, png, MAX_IMAGE_BYTES


LUMA = np.array([0.2126, 0.7152, 0.0722])
MAX_REFERENCES = 12
GEOMETRY_EPSILON = 1e-9


def references_setting(value, size):
    width, height = size
    if "references" in value:
        items = list_value(value.get("references"), "参考点", MAX_REFERENCES)
        references = []
        for item in items:
            if isinstance(item, dict):
                x, y = item.get("x"), item.get("y")
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                x, y = item
            else:
                raise Invalid("参考点需要 X 和 Y 坐标")
            references.append({"x": integer(x, "参考点 X", 0, width - 1),
                               "y": integer(y, "参考点 Y", 0, height - 1)})
        return references
    if value.get("ref_x") is not None and value.get("ref_y") is not None:
        return [{"x": integer(value.get("ref_x"), "参考点 X", 0, width - 1),
                 "y": integer(value.get("ref_y"), "参考点 Y", 0, height - 1)}]
    return []


def settings(value, size):
    width, height = size
    left = integer(value.get("left"), "左界 X", 0, width - 1)
    top = integer(value.get("top"), "上界 Y", 0, height - 1)
    return {
        "left": left, "right": integer(value.get("right"), "右界 X", left, width - 1),
        "top": top, "bottom": integer(value.get("bottom"), "下界 Y", top, height - 1),
        "focus": integer(value.get("focus"), "截线 X", 0, width - 1),
        "references": references_setting(value, size),
        "limit": number(value.get("limit"), "偏差限值", 0.1, 255),
    }


def defaults(size):
    width, height = size
    left, right, top, bottom = width // 6, width * 5 // 6, height // 4, height * 3 // 4
    return settings({
        "left": left, "right": right, "top": top, "bottom": bottom,
        "focus": width // 2, "limit": 8,
        "references": [{"x": x, "y": y} for x, y in ((left, top), (right, top),
                                                     (left, bottom), (right, bottom))],
    }, size)


def classify(delta, limit):
    if delta > limit:
        return "bright"
    if delta < -limit:
        return "dark"
    return "within"


def configured_references(config):
    if "references" in config:
        return config["references"]
    if config.get("ref_x") is not None and config.get("ref_y") is not None:
        return [{"x": config["ref_x"], "y": config["ref_y"]}]
    return []


def reference_model(image, references):
    points = []
    for index, reference in enumerate(references):
        x, y = reference["x"], reference["y"]
        rgb = [int(channel) for channel in image[y, x]]
        clipped = any(channel in (0, 255) for channel in rgb)
        points.append({
            "index": index, "x": x, "y": y, "rgb": rgb,
            "brightness": float(np.dot(rgb, LUMA)),
            "usable": not clipped, "reason": "clipped" if clipped else None,
        })
    triangles = []
    usable = [point for point in points if point["usable"]]
    for first in range(len(usable)):
        for second in range(first + 1, len(usable)):
            for third in range(second + 1, len(usable)):
                triangle = make_triangle(usable[first], usable[second], usable[third])
                if triangle is not None:
                    triangles.append(triangle)
    scale = float(np.median([triangle["perimeter"] for triangle in triangles])) if triangles else 1.0
    for triangle in triangles:
        triangle["scale"] = scale or 1.0
    return points, triangles


def make_triangle(first, second, third):
    x0, y0, x1, y1, x2, y2 = (first["x"], first["y"], second["x"], second["y"],
                              third["x"], third["y"])
    area2 = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if area2 == 0:
        return None
    edge0 = (x1 - x0) ** 2 + (y1 - y0) ** 2
    edge1 = (x2 - x1) ** 2 + (y2 - y1) ** 2
    edge2 = (x0 - x2) ** 2 + (y0 - y2) ** 2
    perimeter = math.sqrt(edge0) + math.sqrt(edge1) + math.sqrt(edge2)
    quality = 2 * math.sqrt(3) * abs(area2) / (edge0 + edge1 + edge2)
    return {
        "indices": [first["index"], second["index"], third["index"]],
        "x": np.array([x0, x1, x2], dtype=float), "y": np.array([y0, y1, y2], dtype=float),
        "brightness": np.array([first["brightness"], second["brightness"], third["brightness"]]),
        "quality": quality, "perimeter": perimeter,
    }


def barycentric(triangle, x, y):
    x0, y0 = triangle["x"][0], triangle["y"][0]
    x1, y1 = triangle["x"][1], triangle["y"][1]
    x2, y2 = triangle["x"][2], triangle["y"][2]
    denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    weight0 = ((y1 - y2) * (x - x2) + (x2 - x1) * (y - y2)) / denominator
    weight1 = ((y2 - y0) * (x - x2) + (x0 - x2) * (y - y2)) / denominator
    return weight0, weight1, 1 - weight0 - weight1


def triangle_score(triangle, x, y):
    distances = sum(math.hypot(triangle["x"][index] - x, triangle["y"][index] - y)
                    for index in range(3)) / 3
    return float(triangle["quality"] / (1 + distances / triangle["scale"]))


def interpolate(weights, brightness):
    return (weights[0] * brightness[0] + weights[1] * brightness[1]
            + weights[2] * brightness[2])


def local_reference(triangles, x, y):
    best = None
    for triangle in triangles:
        low_x, high_x = float(triangle["x"].min()), float(triangle["x"].max())
        low_y, high_y = float(triangle["y"].min()), float(triangle["y"].max())
        if not (low_x <= x <= high_x and low_y <= y <= high_y):
            continue
        weight0, weight1, weight2 = barycentric(triangle, x, y)
        if min(weight0, weight1, weight2) < -GEOMETRY_EPSILON:
            continue
        score = triangle_score(triangle, x, y)
        if best is None or score > best["score"]:
            weights = [float(weight0), float(weight1), float(weight2)]
            best = {"reference": float(interpolate(weights, triangle["brightness"])),
                    "triangle": triangle["indices"], "weights": weights, "score": score}
    return best


def reference_grid(triangles, x0, x1, y0, y1):
    values = np.full((y1 - y0 + 1) * (x1 - x0 + 1), np.nan)
    scores = np.full(values.shape, -np.inf)
    for triangle in triangles:
        start_x = max(x0, int(np.floor(triangle["x"].min())))
        end_x = min(x1, int(np.ceil(triangle["x"].max())))
        start_y = max(y0, int(np.floor(triangle["y"].min())))
        end_y = min(y1, int(np.ceil(triangle["y"].max())))
        if start_x > end_x or start_y > end_y:
            continue
        weights, pixel_x, pixel_y = triangle_pixels(triangle, start_x, end_x, start_y, end_y)
        if not pixel_x.size:
            continue
        sample_x = pixel_x.astype(float)
        sample_y = pixel_y.astype(float)
        distance = sum(np.sqrt((triangle["x"][index] - sample_x) ** 2
                               + (triangle["y"][index] - sample_y) ** 2)
                       for index in range(3)) / 3
        score = triangle["quality"] / (1 + distance / triangle["scale"])
        flat = (pixel_y - y0) * (x1 - x0 + 1) + (pixel_x - x0)
        update = score > scores[flat]
        values[flat[update]] = interpolate([weight[update] for weight in weights],
                                           triangle["brightness"])
        scores[flat[update]] = score[update]
    return values.reshape(y1 - y0 + 1, x1 - x0 + 1)


def triangle_pixels(triangle, start_x, end_x, start_y, end_y):
    """Yield the pixels inside a triangle, row by row, without a full temporary grid."""
    x0, y0 = triangle["x"][0], triangle["y"][0]
    x1, y1 = triangle["x"][1], triangle["y"][1]
    x2, y2 = triangle["x"][2], triangle["y"][2]
    denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    terms = [(y1 - y2, x2 - x1, (x1 - x2) * y2 - (y1 - y2) * x2),
             (y2 - y0, x0 - x2, (x2 - x0) * y2 - (y2 - y0) * x2)]
    terms.append((-(terms[0][0] + terms[1][0]), -(terms[0][1] + terms[1][1]),
                  denominator - terms[0][2] - terms[1][2]))
    rows = np.arange(start_y, end_y + 1, dtype=float)
    lower = np.full(rows.shape, float(start_x))
    upper = np.full(rows.shape, float(end_x))
    open_rows = np.ones(rows.shape, dtype=bool)
    sign = 1.0 if denominator > 0 else -1.0
    tolerance = -GEOMETRY_EPSILON * abs(denominator)
    for slope_x, slope_y, constant in terms:
        fixed = slope_y * rows + constant
        gradient = sign * slope_x
        bound = (tolerance - sign * fixed)
        if gradient > 0:
            lower = np.maximum(lower, bound / gradient)
        elif gradient < 0:
            upper = np.minimum(upper, bound / gradient)
        else:
            open_rows &= bound <= 0
        open_rows &= lower <= upper
    lower = np.ceil(lower[open_rows])
    upper = np.floor(upper[open_rows])
    open_rows = np.nonzero(open_rows)[0]
    lengths = (upper - lower + 1).astype(np.int64)
    keep = lengths > 0
    if not keep.any():
        empty = np.zeros(0, dtype=np.int64)
        return [empty.astype(float)] * 3, empty, empty
    rows = rows[open_rows[keep]]
    lower = lower[keep]
    lengths = lengths[keep]
    pixel_y = np.repeat(rows.astype(np.int64), lengths)
    offsets = np.arange(int(lengths.sum())) - np.repeat(np.cumsum(lengths) - lengths, lengths)
    pixel_x = (np.repeat(lower.astype(np.int64), lengths) + offsets)
    weights = [((slope_x * pixel_x + slope_y * pixel_y + constant) / denominator).astype(float)
               for slope_x, slope_y, constant in terms]
    return weights, pixel_x, pixel_y


def point(image, x, y, config, model=None):
    _, triangles = model if model is not None else reference_model(image, configured_references(config))
    rgb = image[y, x]
    brightness = float(rgb @ LUMA)
    inside = config["left"] <= x <= config["right"] and config["top"] <= y <= config["bottom"]
    local = local_reference(triangles, x, y)
    delta = brightness - local["reference"] if local is not None else None
    return {
        "x": x, "y": y, "rgb": rgb.tolist(), "brightness": brightness, "inside": inside,
        "reference": local["reference"] if local is not None else None,
        "delta": delta,
        "classification": (classify(delta, config["limit"])
                           if inside and delta is not None else None),
        "triangle": local["triangle"] if local is not None else None,
        "weights": local["weights"] if local is not None else None,
    }


def profile(image, config, model=None):
    x = config["focus"]
    if not config["left"] <= x <= config["right"]:
        return []
    _, triangles = model if model is not None else reference_model(image, configured_references(config))
    local = reference_grid(triangles, x, x, config["top"], config["bottom"])[:, 0]
    rows = []
    for y, reference in zip(range(config["top"], config["bottom"] + 1), local):
        rgb = image[y, x]
        brightness = float(rgb @ LUMA)
        available = not np.isnan(reference)
        delta = brightness - float(reference) if available else None
        rows.append({
            "x": x, "y": y, "rgb": rgb.tolist(), "brightness": brightness,
            "reference": float(reference) if available else None, "delta": delta,
            "classification": classify(delta, config["limit"]) if available else None,
        })
    return rows


def coverage(image, config, model=None):
    _, triangles = model if model is not None else reference_model(image, configured_references(config))
    x0, x1, y0, y1 = (config[key] for key in ("left", "right", "top", "bottom"))
    sample = image[y0:y1 + 1, x0:x1 + 1] @ LUMA
    reference = reference_grid(triangles, x0, x1, y0, y1)
    delta = sample - reference
    means = sample.mean(axis=0)
    bright = np.count_nonzero(delta > config["limit"], axis=0)
    dark = np.count_nonzero(delta < -config["limit"], axis=0)
    missing = np.count_nonzero(np.isnan(reference), axis=0)
    return [
        {"x": x, "brightness": float(mean), "bright": int(above), "dark": int(below),
         "unreferenced": int(gap)}
        for x, mean, above, below, gap in zip(range(x0, x1 + 1), means, bright, dark, missing)
    ]


def report(image, config):
    model = reference_model(image, configured_references(config))
    points, triangles = model
    rows = profile(image, config, model)
    distribution = coverage(image, config, model)
    reference = {
        "points": points, "total": len(points),
        "usable": sum(1 for point in points if point["usable"]),
        "triangles": len(triangles),
    }
    reading = None
    if rows:
        column = distribution[config["focus"] - config["left"]]
        deltas = [row["delta"] for row in rows if row["delta"] is not None]
        reading = {
            "mean_luma": column["brightness"],
            "delta_mean": float(np.mean(deltas)) if deltas else None,
            "bright": column["bright"], "dark": column["dark"],
            "rows": len(rows), "referenced": len(deltas),
            "unreferenced": column["unreferenced"],
        }
    return {"reading": reading, "reference": reference, "profile": rows, "coverage": distribution,
            "focus": config["focus"]}


def practice():
    width, height = 766, 482
    cfg = settings({"left": 133, "right": 625, "top": 131, "bottom": 341, "focus": 274,
                    "references": [{"x": 133, "y": 131}, {"x": 625, "y": 131},
                                   {"x": 133, "y": 341}, {"x": 625, "y": 341}],
                    "limit": 8}, (width, height))
    y, x = np.indices((height, width))
    panel = (82 <= x) & (x <= 688) & (70 <= y) & (y <= 405)
    base = 132 + (x - 200) * 0.012 + (y - 240) * 0.012
    texture = 0.8 * np.sin(x * 0.37 + y * 0.47) + 0.55 * np.sin(x * 0.94 - y * 0.07)
    hotspot = 34 * np.exp(-((x - 484)**2 / 55**2 + (y - 247)**2 / 69**2))
    corner = -26 * np.exp(-((x - 255)**2 / 48**2 + (y - 285)**2 / 34**2))
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
