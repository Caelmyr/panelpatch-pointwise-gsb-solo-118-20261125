"""Export the saved source-relative panel readings."""
from io import BytesIO, StringIO
from zipfile import ZipFile, ZIP_DEFLATED
import csv
import json

from PIL import Image, ImageDraw

from .photo import png


def trace_table(result):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("x_px", "y_px", "red", "green", "blue", "luma", "local_reference",
                     "delta_luma", "classification"))
    for point in result["profile"]:
        writer.writerow((point["x"], point["y"], *point["rgb"], f'{point["brightness"]:.3f}',
                         "" if point["reference"] is None else f'{point["reference"]:.3f}',
                         "" if point["delta"] is None else f'{point["delta"]:.3f}',
                         point["classification"] or "unreferenced"))
    return buffer.getvalue().encode()


def proof(image, card, result):
    height, width = image.shape[:2]
    output = Image.new("RGB", (max(430, width), height + 64), "#192433")
    output.paste(Image.fromarray(image), (0, 0))
    draw = ImageDraw.Draw(output)
    cfg = card["settings"]
    draw.rectangle((cfg["left"], cfg["top"], cfg["right"], cfg["bottom"]), outline="#6aa5cb", width=2)
    for point in result["reference"]["points"]:
        color = "#66d2a0" if point["usable"] else "#b4776a"
        draw.rectangle((point["x"] - 4, point["y"] - 4, point["x"] + 4, point["y"] + 4),
                       outline=color, width=2)
    colors = {"bright": "#e9934c", "dark": "#7c85e2", "within": "#75bfa8"}
    for row in result["profile"]:
        x, y = row["x"], row["y"]
        if row["classification"]:
            draw.line((x - 1, y, x + 1, y), fill=colors[row["classification"]])
    reading = result["reading"]
    detail = (f'Column {cfg["focus"]}: mean {reading["mean_luma"]:.2f} / difference {reading["delta_mean"]:+.2f}'
              f' (bright {reading["bright"]}, dark {reading["dark"]}, without reference {reading["unreferenced"]})'
              if reading and reading["delta_mean"] is not None else
              "Current column is outside the inspection rectangle or has no enclosing references")
    reference = result["reference"]
    draw.text((14, height + 13),
              f'References {reference["usable"]}/{reference["total"]} usable | limit +/-{cfg["limit"]:.1f}',
              fill="#dae9eb")
    draw.text((14, height + 35), detail, fill="#a6ead1")
    return png(output)


def package(card, original, image, result):
    memory = BytesIO()
    with ZipFile(memory, "w", ZIP_DEFLATED) as stream:
        stream.writestr("panel.png", original)
        stream.writestr("reading.json", json.dumps({"card": card, "reading": result["reading"],
                                                 "reference": result["reference"]}, ensure_ascii=False, indent=2))
        stream.writestr("panel-profile.csv", trace_table(result))
        stream.writestr("panel-proof.png", proof(image, card, result))
    return memory.getvalue()
