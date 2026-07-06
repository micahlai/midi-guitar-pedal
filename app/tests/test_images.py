"""Milestone 13: image asset storage, validation, config references."""

import base64
import tempfile
import unittest
from pathlib import Path

from config.defaults import default_config
from web import images
from web.server import clear_image_references, validate_action

# Smallest valid PNG (1x1 transparent pixel).
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def data_url(raw=TINY_PNG):
    return "data:image/png;base64," + base64.b64encode(raw).decode()


class ImageStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = images.ASSETS_DIR
        images.ASSETS_DIR = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(setattr, images, "ASSETS_DIR", self._old)

    def test_save_list_delete(self):
        saved = images.save_image("My Amp!", data_url())
        self.assertTrue(saved["id"].startswith("my-amp-"))
        self.assertEqual(saved["name"], "my amp")
        self.assertEqual(images.list_images(), [saved])
        self.assertEqual(images.image_path(saved["id"]).read_bytes(), TINY_PNG)
        images.delete_image(saved["id"])
        self.assertEqual(images.list_images(), [])

    def test_rejects_non_png(self):
        bad = "data:image/png;base64," + base64.b64encode(b"GIF89a...").decode()
        with self.assertRaises(ValueError):
            images.save_image("x", bad)

    def test_rejects_bad_data_url(self):
        with self.assertRaises(ValueError):
            images.save_image("x", "data:image/jpeg;base64,AAAA")
        with self.assertRaises(ValueError):
            images.save_image("x", "data:image/png;base64,!!!not-base64!!!")
        with self.assertRaises(ValueError):
            images.save_image("x", None)

    def test_rejects_oversize(self):
        big = TINY_PNG + b"\x00" * images.MAX_IMAGE_BYTES
        with self.assertRaises(ValueError):
            images.save_image("x", data_url(big))

    def test_asset_id_validation(self):
        images.validate_asset_id("my-amp-18c2")
        for bad in ("../x", "UPPER", "a b", "", None, "-lead", "x" * 65):
            with self.assertRaises(ValueError):
                images.validate_asset_id(bad)

    def test_delete_missing(self):
        with self.assertRaises(ValueError):
            images.delete_image("nope-123")


class ImageActionValidationTest(unittest.TestCase):
    def action(self, image):
        return {
            "type": "effect_cc", "midi_channel": 1, "cc_number": 20, "label": "X",
            "off_color": "#303030", "on_color": "#00FF66", "image_asset_id": image,
        }

    def test_valid_id_and_null(self):
        out = validate_action(self.action("drive-18c2"), ("effect_cc",), secondary=False)
        self.assertEqual(out["image_asset_id"], "drive-18c2")
        out = validate_action(self.action(None), ("effect_cc",), secondary=False)
        self.assertIsNone(out["image_asset_id"])

    def test_bad_id_rejected(self):
        with self.assertRaises(ValueError):
            validate_action(self.action("../etc/passwd"), ("effect_cc",), secondary=False)


class ClearReferencesTest(unittest.TestCase):
    def test_clears_only_matching(self):
        config = default_config()
        slots = config["menus"][0]["slots"]
        slots["1"]["primary"]["image_asset_id"] = "gone-1"
        slots["2"]["primary"]["image_asset_id"] = "kept-2"
        self.assertEqual(clear_image_references(config, "gone-1"), 1)
        self.assertIsNone(slots["1"]["primary"]["image_asset_id"])
        self.assertEqual(slots["2"]["primary"]["image_asset_id"], "kept-2")


if __name__ == "__main__":
    unittest.main()
