"""Button image assets (Milestone 13).

Images live outside the deployed app dir (deploys never clobber them):
    /opt/midi-controller/assets/images/<asset_id>.png

The BROWSER does all resizing/compression (canvas -> small PNG data URL);
the server only validates and stores, so no image library is needed on the
Zero 2 W. Asset ids are self-describing: <name-slug>-<hex timestamp>.
"""

import base64
import logging
import os
import re
import time
from pathlib import Path

log = logging.getLogger("controller.images")

ASSETS_DIR = Path(os.environ.get("CONTROLLER_ASSETS_DIR", "/opt/midi-controller/assets"))

ASSET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_IMAGE_BYTES = 128 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_DATA_URL_PREFIX = "data:image/png;base64,"


def images_dir() -> Path:
    return ASSETS_DIR / "images"


def validate_asset_id(asset_id) -> str:
    if not isinstance(asset_id, str) or not ASSET_ID_RE.match(asset_id):
        raise ValueError("invalid image asset id")
    return asset_id


def image_path(asset_id: str) -> Path:
    return images_dir() / f"{validate_asset_id(asset_id)}.png"


def display_name(asset_id: str) -> str:
    return asset_id.rsplit("-", 1)[0].replace("-", " ")


def list_images() -> list[dict]:
    directory = images_dir()
    if not directory.is_dir():
        return []
    return [
        {"id": path.stem, "name": display_name(path.stem)}
        for path in sorted(directory.glob("*.png"))
        if ASSET_ID_RE.match(path.stem)
    ]


def save_image(name, data_url) -> dict:
    """Store a browser-prepared PNG data URL; returns {id, name}."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "image").lower()).strip("-")[:32] or "image"
    if not isinstance(data_url, str) or not data_url.startswith(_DATA_URL_PREFIX):
        raise ValueError("data must be a PNG data URL")
    try:
        raw = base64.b64decode(data_url[len(_DATA_URL_PREFIX):], validate=True)
    except Exception:
        raise ValueError("invalid base64 image data")
    if not raw.startswith(PNG_MAGIC):
        raise ValueError("data is not a PNG image")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"image too large ({len(raw)} bytes, max {MAX_IMAGE_BYTES})")

    asset_id = f"{slug}-{int(time.time() * 1000):x}"
    directory = images_dir()
    directory.mkdir(parents=True, exist_ok=True)
    image_path(asset_id).write_bytes(raw)
    log.info("image saved: %s (%d bytes)", asset_id, len(raw))
    return {"id": asset_id, "name": display_name(asset_id)}


def delete_image(asset_id: str) -> None:
    path = image_path(asset_id)
    if not path.exists():
        raise ValueError(f"no image {asset_id!r}")
    path.unlink()
    log.info("image deleted: %s", asset_id)
