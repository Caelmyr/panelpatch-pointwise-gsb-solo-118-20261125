"""Pair out-of-limit points along two saved vertical cut lines."""

import numpy as np

SCALE = 100
GAIN = 600_000  # dominates any accumulated tie-break cost, stays inside int32 at 2600 rows
DEVIATION_CEILING = 255.0


def usable(point):
    """Exclude points whose stored 8-bit RGB has a clipped channel."""
    return all(channel not in (0, 255) for channel in point["rgb"])


def possible(point):
    return point["classification"] in ("bright", "dark") and usable(point)


def _cost(dy, gap, max_dy):
    """Prefer a smaller original Y difference, then a more similar deviation."""
    distance = round(abs(float(dy)) * SCALE / max(1, max_dy))
    similarity = round(min(abs(float(gap)), DEVIATION_CEILING) * SCALE / DEVIATION_CEILING)
    return distance + similarity


def _positions(profile):
    return [index for index, point in enumerate(profile) if possible(point)]


def _align(left, right, max_dy):
    """Largest one-to-one, top-to-bottom matching between two ordered point lists.

    More pairs always win; ties are broken by combined |ΔY| and |Δdeviation|.
    """
    rows, columns = len(left), len(right)
    if not rows or not columns:
        return []
    ys_left = np.array([point["y"] for point in left], dtype=np.int64)
    ys_right = np.array([point["y"] for point in right], dtype=np.int64)
    bright_left = np.array([point["classification"] == "bright" for point in left])
    bright_right = np.array([point["classification"] == "bright" for point in right])
    deltas_left = np.array([point["delta"] for point in left], dtype=np.float64)
    deltas_right = np.array([point["delta"] for point in right], dtype=np.float64)
    span = max(1, max_dy)
    scores = np.zeros((rows + 1, columns + 1), dtype=np.int32)
    for row in range(1, rows + 1):
        best = scores[row - 1].copy()
        align = int(ys_left[row - 1])
        low = int(np.searchsorted(ys_right, align - max_dy, side="left"))
        high = int(np.searchsorted(ys_right, align + max_dy, side="right"))
        window = np.arange(low, high)
        allowed = window[bright_right[low:high] == bright_left[row - 1]]
        if allowed.size:
            cost = (np.rint(np.abs(ys_right[allowed] - align) * SCALE / span)
                    + np.rint(np.minimum(np.abs(deltas_right[allowed] - deltas_left[row - 1]),
                                         DEVIATION_CEILING) * SCALE / DEVIATION_CEILING))
            candidate = scores[row - 1, allowed] + GAIN - cost.astype(np.int32)
            best[allowed + 1] = np.maximum(best[allowed + 1], candidate)
        scores[row] = np.maximum.accumulate(best)
    pairs = []
    row, column = rows, columns
    while row and column:
        first, second = left[row - 1], right[column - 1]
        distance = abs(first["y"] - second["y"])
        if (first["classification"] == second["classification"] and distance <= max_dy
                and scores[row, column] == scores[row - 1, column - 1] + GAIN
                - _cost(distance, second["delta"] - first["delta"], max_dy)):
            pairs.append((row - 1, column - 1))
            row -= 1
            column -= 1
        elif scores[row, column] == scores[row - 1, column]:
            row -= 1
        else:
            column -= 1
    pairs.reverse()
    return pairs


def _counts(profile, paired):
    within = sum(1 for point in profile if point["classification"] not in ("bright", "dark"))
    clipped = sum(1 for point in profile if point["classification"] in ("bright", "dark")
                  and not usable(point))
    eligible = sum(1 for point in profile if possible(point))
    return {"rows": len(profile), "eligible": eligible, "paired": paired,
            "unpaired": eligible - paired, "clipped": clipped, "within": within}


def _items(profile, links):
    items = []
    for index, point in enumerate(profile):
        if point["classification"] not in ("bright", "dark"):
            continue
        clipped = not usable(point)
        status = "clipped" if clipped else "paired" if index in links else "unpaired"
        items.append({**point, "clipped": clipped, "status": status,
                      "pair_index": links.get(index)})
    return items


def _card(card):
    return {"id": card["id"], "name": card["name"], "revision": card["revision"],
            "photo_name": card["photo_name"], "width": card["width"], "height": card["height"],
            "synthetic": card["synthetic"], "focus": card["settings"]["focus"],
            "limit": card["settings"]["limit"], "settings": card["settings"]}


def compare(primary, primary_report, other, other_report, max_dy):
    """Return the pairing as ordered pairs plus per-row status for both lines."""
    primary_profile, other_profile = primary_report["profile"], other_report["profile"]
    positions_a, positions_b = _positions(primary_profile), _positions(other_profile)
    left = [primary_profile[index] for index in positions_a]
    right = [other_profile[index] for index in positions_b]
    aligned = _align(left, right, max_dy)
    pairs = [{"primary": left[first], "other": right[second],
              "dy": right[second]["y"] - left[first]["y"],
              "abs_dy": abs(right[second]["y"] - left[first]["y"]),
              "delta_gap": right[second]["delta"] - left[first]["delta"]}
             for first, second in aligned]
    links_a = {positions_a[first]: index for index, (first, _) in enumerate(aligned)}
    links_b = {positions_b[second]: index for index, (_, second) in enumerate(aligned)}
    warning = None
    if not primary_profile:
        warning = "当前截线不在测量框内，无法沿截线比较。"
    elif not other_profile:
        warning = "另一张卡的截线不在其测量框内，无法沿截线比较。"
    return {
        "max_dy": max_dy,
        "primary": _card(primary),
        "other": _card(other),
        "warning": warning,
        "summary": {"pairs": len(pairs),
                    "primary": _counts(primary_profile, len(aligned)),
                    "other": _counts(other_profile, len(aligned))},
        "pairs": pairs,
        "items": _items(primary_profile, links_a),
        "other_items": _items(other_profile, links_b),
        "references": {"primary": primary_report["reference"], "other": other_report["reference"]},
        "note": "沿各自已保存的竖截线，各用自己的参考与限值；任一通道为0或255的点不参与。"
                "仅同为偏亮或同为偏暗、原Y差不超过上限的点按从上到下顺序一一配对；"
                "优先配出更多点，其次兼顾原Y更接近和两张偏差量更相近。",
    }
