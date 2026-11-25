"""Read relative brightness from a photographed display test image."""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from image_lab.validation import integer, number

from .photo import decode, pixels, png, MAX_IMAGE_BYTES


LUMA = np.array([0.2126, 0.7152, 0.0722])
LINE_MIN_COLUMNS = 6
LINE_MARKER = "#ff3df0"


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


def _line_masks(image, config):
    """Return strict bright/dark candidate masks and their over-limit amounts."""
    x0, x1, y0, y1 = (config[key] for key in ("left", "right", "top", "bottom"))
    crop = image[y0 : y1 + 1, x0 : x1 + 1]
    luma = crop @ LUMA
    reference = float(image[config["ref_y"], config["ref_x"]] @ LUMA)
    delta = luma - reference
    limit = float(config["limit"])

    # A clipped channel gives no trustworthy 8-bit deviation and cannot be a
    # bridge between otherwise usable columns.
    clipped = np.any((crop == 0) | (crop == 255), axis=2)
    bright = (delta > limit) & ~clipped
    dark = (delta < -limit) & ~clipped
    excess = np.maximum(np.abs(delta) - limit, 0.0)
    excess[~(bright | dark)] = 0.0
    return bright, dark, excess


def _best_path_in_band(valid_rows, excess_rows, image, config, base_y, kind):
    """DP for one three-row Y band.  The band enforces max(Y)-min(Y) <= 2."""
    width = len(valid_rows[0]) if valid_rows else 0
    if width < LINE_MIN_COLUMNS:
        return None

    negative_infinity = -math.inf
    scores = [negative_infinity, negative_infinity, negative_infinity]
    backtrace = []
    end_score = negative_infinity
    end_x = end_row = -1

    for column in range(width):
        next_scores = [negative_infinity, negative_infinity, negative_infinity]
        previous_row = [-1, -1, -1]

        for row in range(len(valid_rows)):
            if not valid_rows[row][column]:
                continue

            amount = float(excess_rows[row][column])
            best_previous = negative_infinity
            best_row = -1
            # Prefer a straight continuation on exact score ties, then upward.
            for candidate_row in (row, row - 1, row + 1):
                if 0 <= candidate_row < len(valid_rows) and scores[candidate_row] > best_previous:
                    best_previous = scores[candidate_row]
                    best_row = candidate_row

            if best_row >= 0:
                next_scores[row] = best_previous + amount
                previous_row[row] = best_row
            else:
                next_scores[row] = amount
                previous_row[row] = -1

            if next_scores[row] > end_score:
                end_score = next_scores[row]
                end_x, end_row = column, row

        backtrace.append(previous_row)
        scores = next_scores

    if end_x < 0:
        return None

    indexed_points = []
    column, row = end_x, end_row
    while column >= 0:
        indexed_points.append((column, base_y + row))
        previous = backtrace[column][row]
        if previous < 0:
            break
        row = previous
        column -= 1
    indexed_points.reverse()

    if len(indexed_points) < LINE_MIN_COLUMNS:
        return None

    points = []
    excesses = []
    for local_x, y in indexed_points:
        x = config["left"] + local_x
        item = point(image, x, y, config)
        item["excess"] = max(0.0, abs(item["delta"]) - float(config["limit"]))
        points.append(item)
        excesses.append(item["excess"])

    columns = len(points)
    average_excess = float(sum(excesses) / columns)
    average_abs_delta = float(sum(abs(item["delta"]) for item in points) / columns)
    average_delta = float(sum(item["delta"] for item in points) / columns)
    ys = [item["y"] for item in points]
    return {
        "kind": kind,
        "polarity": kind,
        "classification": kind,
        "columns": columns,
        "column_count": columns,
        "original_columns": columns,
        "length": columns,
        "count": columns,
        "start_x": points[0]["x"],
        "end_x": points[-1]["x"],
        "x0": points[0]["x"],
        "x1": points[-1]["x"],
        "y_min": min(ys),
        "y_max": max(ys),
        "average_excess": average_excess,
        "mean_excess": average_excess,
        "avg_excess": average_excess,
        "average_overrun": average_excess,
        "mean_overrun": average_excess,
        "strength": average_excess,
        "average_abs_delta": average_abs_delta,
        "mean_abs_delta": average_abs_delta,
        "average_delta": average_delta,
        "mean_delta": average_delta,
        # columns * average excess is total over-limit amount.  It rewards both
        # coverage of original columns and a clearly visible deviation.
        "score": float(sum(excesses)),
        "marker": LINE_MARKER,
        "points": points,
        "coordinates": [[item["x"], item["y"]] for item in points],
        "xs": [item["x"] for item in points],
        "ys": ys,
    }


def find_horizontal_line(image, config):
    """Recommend the strongest valid one-pixel-per-column horizontal line."""
    x0, x1, y0, y1 = (config[key] for key in ("left", "right", "top", "bottom"))
    if x1 - x0 + 1 < LINE_MIN_COLUMNS or y1 < y0:
        return None

    bright, dark, excess = _line_masks(image, config)
    height = y1 - y0 + 1
    best = None
    best_key = None
    seen = set()

    for base_y in range(y0, y1 + 1):
        top = base_y - y0
        bottom = min(height, top + 3)
        if top >= bottom:
            continue
        excess_rows = np.asarray(excess)[top:bottom, :].tolist()
        for kind, mask in (("bright", bright), ("dark", dark)):
            valid_rows = np.asarray(mask)[top:bottom, :].tolist()
            candidate = _best_path_in_band(valid_rows, excess_rows, image, config, base_y, kind)
            if candidate is None:
                continue

            signature = tuple((item["x"], item["y"]) for item in candidate["points"])
            if signature in seen:
                continue
            seen.add(signature)

            ranking_key = (
                candidate["score"],
                candidate["columns"],
                candidate["average_excess"],
                -candidate["y_min"],
                -candidate["start_x"],
                1 if kind == "bright" else 0,
            )
            if best_key is None or ranking_key > best_key:
                best_key = ranking_key
                best = candidate

    return best


# Descriptive aliases for callers/tests using either the issue or UI vocabulary.
detect_horizontal_line = find_horizontal_line
horizontal_line = find_horizontal_line
recommend_line = find_horizontal_line
find_line = find_horizontal_line
detect_line = find_horizontal_line
scan_horizontal_line = find_horizontal_line


def find_horizontal_lines(image, config):
    """Return ranked candidates; the workflow currently recommends the best one."""
    best = find_horizontal_line(image, config)
    return [best] if best is not None else []


detect_horizontal_lines = find_horizontal_lines


def normalize_line(value, image_shape=None):
    """Normalize stored/adopted line data to ``[{"x": int, "y": int}, ...]``."""
    if value is None:
        return []
    if isinstance(value, dict):
        value = value.get("points", value.get("coordinates", value.get("xy", value.get("line"))))
        if value is None:
            if "x" in value and "y" in value:
                value = [value]
            else:
                return []

    raw_points = list(value) if isinstance(value, (list, tuple, np.ndarray)) else []
    points = []
    for item in raw_points:
        if isinstance(item, dict):
            if "x" not in item or "y" not in item:
                continue
            try:
                x, y = int(item["x"]), int(item["y"])
            except (TypeError, ValueError):
                continue
        elif isinstance(item, (list, tuple, np.ndarray)) and len(item) >= 2:
            try:
                x, y = int(item[0]), int(item[1])
            except (TypeError, ValueError):
                continue
        else:
            continue

        if image_shape is not None:
            height, width = image_shape[:2]
            if not (0 <= x < width and 0 <= y < height):
                continue
        if not points or points[-1] != {"x": x, "y": y}:
            points.append({"x": x, "y": y})
    return points


def adopted_review(adoption, image_shape=None):
    source = adoption if isinstance(adoption, dict) else {}
    points = normalize_line(adoption, image_shape)
    if not points:
        return None
    xs = [point["x"] for point in points]
    ys = [point["y"] for point in points]
    kind = source.get("kind") or source.get("polarity") or source.get("classification")
    if kind not in ("bright", "dark"):
        kind = None

    def metadata_number(*names):
        for name in names:
            value = source.get(name)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return float(value)
        return None

    average_excess = metadata_number("average_excess", "mean_excess", "avg_excess")
    average_abs_delta = metadata_number("average_abs_delta", "mean_abs_delta")
    average_delta = metadata_number("average_delta", "mean_delta")
    score = metadata_number("score")
    result = {
        "status": "adopted",
        "adopted": True,
        "kind": kind,
        "polarity": kind,
        "classification": kind,
        "columns": len(points),
        "column_count": len(points),
        "original_columns": len(points),
        "length": len(points),
        "start_x": min(xs),
        "end_x": max(xs),
        "x0": min(xs),
        "x1": max(xs),
        "y_min": min(ys),
        "y_max": max(ys),
        "marker": source.get("marker") or LINE_MARKER,
        "points": points,
        "coordinates": [[point["x"], point["y"]] for point in points],
        "xs": xs,
        "ys": ys,
    }
    if average_excess is not None:
        result.update(average_excess=average_excess, mean_excess=average_excess,
                      avg_excess=average_excess)
    if average_abs_delta is not None:
        result.update(average_abs_delta=average_abs_delta, mean_abs_delta=average_abs_delta)
    if average_delta is not None:
        result.update(average_delta=average_delta, mean_delta=average_delta)
    if score is not None:
        result["score"] = score
    return result


def report(image, config, adoption=None):
    rows = profile(image, config)
    reference = point(image, config["ref_x"], config["ref_y"], config)
    distribution = coverage(image, config)
    recommendation = find_horizontal_line(image, config)
    adopted = adopted_review(adoption if adoption is not None else config.get("adopted_line"),
                            image.shape)
    if adopted and recommendation and adopted["coordinates"] == recommendation["coordinates"]:
        for key in ("kind", "polarity", "classification", "average_excess", "mean_excess",
                    "avg_excess", "average_abs_delta", "mean_abs_delta", "average_delta",
                    "mean_delta", "score"):
            if recommendation.get(key) is not None and adopted.get(key) is None:
                adopted[key] = recommendation[key]
    reading = None
    if rows:
        column = distribution[config["focus"] - config["left"]]
        reading = {
            "mean_luma": column["brightness"], "delta_mean": column["brightness"] - reference["brightness"],
            "bright": column["bright"], "dark": column["dark"], "rows": len(rows),
        }
    return {"reading": reading, "reference": reference, "profile": rows, "coverage": distribution,
            "focus": config["focus"],
            "horizontal_line": recommendation,
            "horizontal_lines": [recommendation] if recommendation else [],
            "recommended_line": recommendation,
            "recommendation": recommendation,
            "suggested_line": recommendation,
            "suggestion": recommendation,
            "best_line": recommendation,
            "line_recommendation": recommendation,
            "line": recommendation,
            "lines": [recommendation] if recommendation else [],
            "line_candidates": [recommendation] if recommendation else [],
            "candidates": [recommendation] if recommendation else [],
            "adopted_line": adopted,
            "adoption": adopted,
            "line_points": adopted["coordinates"] if adopted else []}


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
