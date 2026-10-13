"""Authenticated, aspect-preserving iCloud photo feed."""
from __future__ import annotations
import asyncio
from collections import OrderedDict
import hashlib
from io import BytesIO
from time import monotonic
from urllib.parse import urlparse
from aiohttp import ClientTimeout, web
from PIL import Image, ImageOps
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from . import icloud
from .providers import Provider
MAX_BYTES = 32 * 1024 * 1024

def safe_image_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and not parsed.username and not parsed.password and parsed.port in (None, 443) and any(host == d or host.endswith("." + d) for d in ("icloud-content.com", "icloud.com", "cdn-apple.com"))


def render_photo(data: bytes) -> tuple[bytes, int, int]:
    with Image.open(BytesIO(data)) as opened:
        if opened.width * opened.height > 45_000_000:
            raise ValueError("Photo too large")
        opened.draft("RGB", (1800, 1800))
        photo = ImageOps.exif_transpose(opened)
        photo.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
        photo = photo.convert("RGB")
        output = BytesIO()
        photo.save(output, "JPEG", quality=88)
        return output.getvalue(), photo.width, photo.height


class PhotoFeed:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.items = {}
        self.title = "Family photos"
        self.lock = asyncio.Lock()
        self.downloads = asyncio.Semaphore(2)
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.last_refresh = 0
        self.served = 0
        self.provider = None if entry.data.get("provider", "icloud") == "icloud" else Provider(hass, dict(entry.data))

    def status(self, error=None):
        self.error = error

    async def refresh(self, force=False):
        async with self.lock:
            if self.items and not force and monotonic() - self.last_refresh < 7200:
                return
            if self.provider:
                # Refresh sessions as well as signed asset links.
                candidate = Provider(self.hass, dict(self.entry.data))
                try:
                    records = await candidate.records()
                    self._set_records(records)
                except Exception:
                    await candidate.close()
                    raise
                previous, self.provider = self.provider, candidate
                await previous.close()
                return
            token = self.entry.data["token"]
            backend = self.entry.data["backend"]
            self.title = self.entry.title
            if backend == "cloudkit":
                records = await icloud.IcloudCloudKitClient(self.hass, token).async_get_items("full")
            else:
                client = icloud.IcloudClient(self.hass, token)
                photos = await client.async_get_photos()
                assets = await client.async_get_asset_urls([p["photoGuid"] for p in photos if p.get("photoGuid")])
                records = []
                for photo in photos:
                    checksum = icloud.pick_checksum(photo, "full")
                    asset = assets.get(checksum) if checksum else None
                    if asset:
                        records.append({"source_id": photo.get("photoGuid"), "url": icloud.build_image_url(asset), "width": photo.get("width"), "height": photo.get("height")})
            records = [r for r in records if r.get("url") and safe_image_url(r["url"])]
            self._set_records(records)

    def _set_records(self, records):
        result = {}
        for record in records:
            source_id = record.get("source_id")
            if source_id is None:
                continue
            key = hashlib.sha256(str(source_id).encode()).hexdigest()[:32]
            result[key] = {**record, "id": key, "width": int(record.get("width") or 0), "height": int(record.get("height") or 0)}
        if not result:
            raise ValueError("No photos are available")
        self.items = result
        self.title = self.entry.title
        self.last_refresh = monotonic()
        self.status()

    async def close(self):
        if self.provider:
            await self.provider.close()
        self.cache.clear()
        self.cache_bytes = 0

    async def get_photo(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        async with self.downloads:
            if key in self.cache:
                return self.cache[key]
            for attempt in range(2):
                item = self.items.get(key)
                if not item:
                    raise web.HTTPNotFound()
                if self.provider:
                    try:
                        raw = await self.provider.image(item)
                    except Exception:
                        if attempt == 0:
                            await self.refresh(force=True)
                            continue
                        raise
                    if len(raw) > MAX_BYTES:
                        raise ValueError("Photo too large")
                    return await self._cache_photo(key, raw)
                async with async_get_clientsession(self.hass).get(item["url"], timeout=ClientTimeout(total=35), allow_redirects=False) as response:
                    if response.status in (401, 403, 404) and attempt == 0:
                        await self.refresh(force=True)
                        continue
                    if response.status != 200:
                        raise ValueError("Photo download unavailable")
                    if response.content_length and response.content_length > MAX_BYTES:
                        raise ValueError("Photo too large")
                    chunks, size = [], 0
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError("Photo too large")
                        chunks.append(chunk)
                return await self._cache_photo(key, b"".join(chunks))
            raise ValueError("Photo link expired")

    async def _cache_photo(self, key, raw):
        data, width, height = await self.hass.async_add_executor_job(render_photo, raw)
        if key in self.items:
            self.items[key].update(width=width, height=height)
        self.cache[key] = data
        self.cache_bytes += len(data)
        while self.cache_bytes > 24 * 1024 * 1024 and len(self.cache) > 1:
            _, old = self.cache.popitem(last=False)
            self.cache_bytes -= len(old)
        self.served += 1
        self.status()
        return data
