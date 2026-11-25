"""Connect display inspection and source-photo preparation."""

from io import BytesIO
import os
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, url_for

from image_lab import create_app as preparation_app
from image_lab.validation import Invalid, identifier, integer, object_value

from . import exports, pairing, patch
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
        return jsonify(cards.update(key, object_value(request.get_json(silent=True), "试图卡设置"))
                       if request.method == "PATCH" else cards.read(key))

    @api.get("/cards/<key>/capture.png")
    def capture(key):
        return send_file(cards.photo(key), mimetype="image/png", conditional=True)

    def measurement(key):
        card = cards.read(key, request.args.get("revision"))
        image = patch.pixels(cards.photo(key))
        return card, image, patch.report(image, card["settings"])

    @api.get("/cards/<key>/measurement")
    def measurement_json(key):
        card, _, result = measurement(key)
        return jsonify(revision=card["revision"], **result)

    @api.get("/cards/<key>/probe")
    def probe(key):
        card = cards.read(key, request.args.get("revision"))
        x = integer(request.args.get("x"), "X", 0, card["width"] - 1)
        y = integer(request.args.get("y"), "Y", 0, card["height"] - 1)
        return jsonify(patch.point(patch.pixels(cards.photo(key)), x, y, card["settings"]))

    @api.get("/cards/<key>/paired")
    def paired(key):
        primary = cards.read(key, request.args.get("revision"))
        if not request.args.get("other"):
            raise Invalid("请选择另一张试图卡")
        other_key = identifier(request.args.get("other"))
        if other_key == primary["id"]:
            raise Invalid("请另选一张试图卡配对")
        other = cards.read(other_key, request.args.get("other_revision"))
        max_dy = integer(request.args.get("max_dy"), "原 Y 差上限", 0, max(primary["height"], other["height"]) - 1)
        first = patch.report(patch.pixels(cards.photo(primary["id"])), primary["settings"])
        second = patch.report(patch.pixels(cards.photo(other["id"])), other["settings"])
        return jsonify(revision=primary["revision"], other_revision=other["revision"],
                       **pairing.compare(primary, first, other, second, max_dy))

    @api.get("/cards/<key>/export/profile.csv")
    def profile(key):
        _, _, result = measurement(key)
        return download(exports.trace_table(result), "text/csv", "panel-profile.csv")

    @api.get("/cards/<key>/export/proof.png")
    def proof(key):
        card, image, result = measurement(key)
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
