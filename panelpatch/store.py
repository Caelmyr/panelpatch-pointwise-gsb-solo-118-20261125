"""Keep an immutable test photo and its source-relative inspection settings."""

import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from image_lab.validation import Conflict, Invalid, identifier, integer, object_value, text

from . import patch


class Cards:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def folder(self, key):
        folder = self.root / identifier(key)
        if not (folder / "card.json").is_file():
            raise Invalid("没有找到这份试图卡")
        return folder

    def read(self, key, revision=None):
        with self.lock:
            card = json.loads((self.folder(key) / "card.json").read_text())
            if revision is not None and integer(revision, "工作版本", 1) != card["revision"]:
                raise Conflict("试图卡已经改动，请重新打开")
            return card

    @staticmethod
    def commit(folder, card):
        stage = folder / (uuid4().hex + ".tmp")
        stage.write_text(json.dumps(card, ensure_ascii=False, allow_nan=False))
        stage.replace(folder / "card.json")

    def list(self):
        with self.lock:
            rows = []
            for path in self.root.glob("*/card.json"):
                card = json.loads(path.read_text())
                rows.append({**{key: card[key] for key in ("id", "name", "synthetic", "revision")},
                             "modified_ns": path.stat().st_mtime_ns})
            return sorted(rows, key=lambda row: (-row["modified_ns"], row["id"]))

    def create(self, name, title, size, data, config, synthetic=False):
        name = text(name, "试图卡名称", 80, False)
        title = text(title, "原片名称", 140, False)
        with self.lock:
            if len(self.list()) >= 150:
                raise Invalid("试图卡库已达150份")
            key = uuid4().hex
            folder = self.root / key
            folder.mkdir()
            (folder / "capture.png").write_bytes(data)
            card = {"id": key, "revision": 1, "name": name, "photo_name": title, "synthetic": synthetic,
                    "width": size[0], "height": size[1], "settings": config}
            self.commit(folder, card)
            return card

    def demo(self):
        size, image, config = patch.practice()
        return self.create("练习 · 灰阶面板", "合成试图.png", size, image, config, synthetic=True)

    def update(self, key, value):
        with self.lock:
            card = self.read(key, integer(value.get("revision"), "工作版本", 1))
            incoming = object_value(value.get("settings", {}), "试图设置")
            old_settings = card["settings"]
            if not card.get("adopted_line"):
                legacy_adoption = old_settings.get("adopted_line") or old_settings.get("line_points")
                if legacy_adoption:
                    review = patch.adopted_review(
                        legacy_adoption, (card["height"], card["width"], 3))
                    if review:
                        card["adopted_line"] = review
            config = patch.settings({**old_settings, **incoming}, (card["width"], card["height"]))

            adoption_present = False
            adoption_value = None
            for source in (value, incoming):
                for name in ("adopted_line", "adopt_line", "line", "line_points", "points"):
                    if name in source:
                        adoption_present = True
                        adoption_value = source[name]
                        break
                if adoption_present:
                    break

            # Geometry/reference/limit edits invalidate an adopted path.  A
            # focus-only edit is the chart-to-transect interaction and keeps it.
            rule_keys = ("left", "right", "top", "bottom", "ref_x", "ref_y", "limit")
            rules_changed = any(old_settings.get(name) != config[name] for name in rule_keys)
            if rules_changed or adoption_present:
                card.pop("adopted_line", None)
            if adoption_present and adoption_value not in (None, [], {}):
                review = patch.adopted_review(adoption_value, (card["height"], card["width"], 3))
                if review is None:
                    raise Invalid("采用横线至少需要一个有效原片点")
                card["adopted_line"] = review

            adoption = card.get("adopted_line")
            if adoption:
                config["adopted_line"] = adoption
                config["line_points"] = adoption["coordinates"]

            card.update(name=text(value.get("name", card["name"]), "试图卡名称", 80, False),
                        settings=config, revision=card["revision"] + 1)
            self.commit(self.folder(key), card)
            return card

    def adopt_line(self, key, revision, line):
        with self.lock:
            card = self.read(key, revision)
            review = patch.adopted_review(line, (card["height"], card["width"], 3))
            if review is None:
                raise Invalid("没有可采用的横线实点")
            card["adopted_line"] = review
            card["settings"]["adopted_line"] = review
            card["settings"]["line_points"] = review["coordinates"]
            card["revision"] += 1
            self.commit(self.folder(key), card)
            return card

    def photo(self, key):
        return self.folder(key) / "capture.png"
