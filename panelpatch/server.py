"""Connect display inspection and source-photo preparation."""

from io import BytesIO
import json
import os
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, url_for

from image_lab import create_app as preparation_app
from image_lab.validation import Invalid, integer, object_value

from . import exports, patch
from .store import Cards


def download(data, mime, filename):
    return send_file(BytesIO(data), mimetype=mime, max_age=0, download_name=filename, as_attachment=True)


def create_app(directory=None):
    root = Path(directory or os.environ.get("PANELPATCH_DATA", ".panelpatch-data")).resolve()
    desk = preparation_app(root / "prepare")
    cards = Cards(root / "cards")
    api = Blueprint("panelpatch", __name__, url_prefix="/panelpatch")

    @desk.get("/")
    def home():
        return render_template("panelpatch.html")

    @api.get("/health")
    def health():
        return jsonify(status="ok", app="panelpatch")

    @api.get("/cards")
    def listing():
        return jsonify(cards=cards.list())

    @api.post("/cards")
    def create():
        request.max_content_length = 20 * 1024 * 1024
        upload = request.files.get("photo")
        if not upload or not upload.filename:
            raise Invalid("请选择面板试图")
        size, image = patch.decode(upload.stream.read(patch.MAX_IMAGE_BYTES + 1))
        return jsonify(cards.create(request.form.get("name", ""), Path(upload.filename).name[:140],
                                    size, image, patch.defaults(size))), 201

    @api.post("/practice")
    def practice():
        return jsonify(cards.demo()), 201

    @api.route("/cards/<key>", methods=["GET", "PATCH"])
    def card(key):
        if request.method == "PATCH":
            body = object_value(request.get_json(silent=True), "试图卡设置")
            if body.get("adopt_recommended") is True or body.get("adopt_line") is True:
                current = cards.read(key, body.get("revision"))
                image = patch.pixels(cards.photo(key))
                recommended = patch.find_horizontal_line(image, current["settings"])
                if recommended is None:
                    raise Invalid("没有找到符合条件的横线，无法采用")
                body["adopted_line"] = recommended
            return jsonify(cards.update(key, body))
        return jsonify(cards.read(key))

    @api.get("/cards/<key>/capture.png")
    def capture(key):
        return send_file(cards.photo(key), mimetype="image/png", conditional=True)

    def measurement(key):
        card = cards.read(key, request.args.get("revision"))
        image = patch.pixels(cards.photo(key))
        adoption = card.get("adopted_line") or card.get("line_points") or card.get("line") \
            or card.get("points") or card["settings"].get("adopted_line") \
            or card["settings"].get("line_points")
        return card, image, patch.report(image, card["settings"], adoption)

    def apply_line_query(result, image):
        raw = request.args.get("adopted_line") or request.args.get("line") \
            or request.args.get("line_points") or request.args.get("points")
        if not raw:
            return
        try:
            adoption = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            # Also accept x1,y1;x2,y2 or x1,y1,x2,y2 compact forms.
            try:
                tokens = raw.replace(";", ",").split(",")
                values = [float(token) for token in tokens if token.strip()]
            except ValueError:
                return
            adoption = [[values[i], values[i + 1]] for i in range(0, len(values) - 1, 2)]
        review = patch.adopted_review(adoption, image.shape)
        if review:
            result["adopted_line"] = review

    @api.get("/cards/<key>/measurement")
    def measurement_json(key):
        card, _, result = measurement(key)
        return jsonify(revision=card["revision"], **result)

    @api.get("/cards/<key>/horizontal-line")
    @api.get("/cards/<key>/horizontal-lines")
    @api.get("/cards/<key>/horizontal_line")
    @api.get("/cards/<key>/line")
    @api.get("/cards/<key>/find-line")
    @api.get("/cards/<key>/recommend-line")
    def horizontal_line(key):
        card = cards.read(key, request.args.get("revision"))
        image = patch.pixels(cards.photo(key))
        line = patch.find_horizontal_line(image, card["settings"])
        return jsonify(revision=card["revision"], line=line, horizontal_line=line,
                       recommended_line=line, recommendation=line, suggested_line=line,
                       best_line=line, line_recommendation=line,
                       horizontal_lines=[line] if line else [],
                       lines=[line] if line else [],
                       line_candidates=[line] if line else [],
                       candidates=[line] if line else [])

    @api.post("/cards/<key>/adopt-line")
    @api.post("/cards/<key>/adopt_line")
    @api.post("/cards/<key>/adopt")
    def adopt_line(key):
        body = request.get_json(silent=True) or {}
        revision = body.get("revision", request.args.get("revision"))
        card = cards.read(key, revision)
        image = patch.pixels(cards.photo(key))
        line = patch.find_horizontal_line(image, card["settings"])
        if line is None:
            raise Invalid("没有找到符合连续六列、Y 连续性、亮暗一致和无削波要求的横线")
        updated = cards.adopt_line(key, card["revision"], line)
        return jsonify(updated)

    @api.get("/cards/<key>/probe")
    def probe(key):
        card = cards.read(key, request.args.get("revision"))
        x = integer(request.args.get("x"), "X", 0, card["width"] - 1)
        y = integer(request.args.get("y"), "Y", 0, card["height"] - 1)
        return jsonify(patch.point(patch.pixels(cards.photo(key)), x, y, card["settings"]))

    @api.get("/cards/<key>/export/profile.csv")
    def profile(key):
        _, _, result = measurement(key)
        return download(exports.trace_table(result), "text/csv", "panel-profile.csv")

    @api.get("/cards/<key>/export/proof.png")
    @api.get("/cards/<key>/export/proof")
    def proof(key):
        card, image, result = measurement(key)
        apply_line_query(result, image)
        return download(exports.proof(image, card, result), "image/png", "panel-proof.png")

    @api.get("/cards/<key>/export/observation.zip")
    def bundle(key):
        card, image, result = measurement(key)
        package = exports.package(card, cards.photo(key).read_bytes(), image, result)
        return download(package, "application/zip", f"panelpatch-r{card['revision']}.zip")

    @api.post("/cards/<key>/prepare")
    def prepare(key):
        card = cards.read(key, request.args.get("revision"))
        image = patch.pixels(cards.photo(key)).astype("float32") / 255
        services = desk.extensions
        asset = services["assets"].put(image, card["photo_name"])
        project = services["store"].create(f'{card["name"]} · 原片准备')
        services["frames"].add(project["id"], project["revision"], [asset["id"]])
        return jsonify(url=url_for("index", project=project["id"])), 201

    desk.register_blueprint(api)
    return desk
