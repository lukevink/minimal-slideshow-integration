"""All catalog and image routes require Home Assistant authentication."""
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from .const import DOMAIN
from .feed import PhotoDownloadError

def get_feed(request):
    feeds = request.app["hass"].data.get(DOMAIN, {})
    entry_id = request.query.get("entry_id")
    feed = feeds.get(entry_id) if entry_id else next(iter(feeds.values()), None)
    if feed is None:
        raise web.HTTPNotFound(reason="Album unavailable")
    return feed

class AlbumsView(HomeAssistantView):
    url = "/api/minimal_slideshow/albums"
    name = "api:minimal_slideshow:albums"
    requires_auth = True
    async def get(self, request):
        feeds = request.app["hass"].data.get(DOMAIN, {})
        return web.json_response({"albums": [{"entry_id": key, "title": feed.title} for key, feed in feeds.items()]}, headers={"Cache-Control": "private, no-store"})

class CatalogView(HomeAssistantView):
    url = "/api/minimal_slideshow/catalog"
    name = "api:minimal_slideshow:catalog"
    requires_auth = True
    async def get(self, request):
        feed = get_feed(request)
        try:
            await feed.refresh()
        except Exception:
            if not feed.items:
                return web.json_response({"error": "Album is not ready yet"}, status=503)
        return web.json_response({"entry_id": feed.entry.entry_id, "title": feed.title, "photos": [{k: item.get(k, 0) for k in ("id", "width", "height")} for item in feed.items.values()]}, headers={"Cache-Control": "private, no-store"})

class PhotoView(HomeAssistantView):
    url = "/api/minimal_slideshow/image/{photo_id}"
    name = "api:minimal_slideshow:image"
    requires_auth = True
    async def get(self, request, photo_id):
        feed = get_feed(request)
        if photo_id not in feed.items:
            raise web.HTTPNotFound()
        try:
            data = await feed.get_photo(photo_id)
        except web.HTTPException:
            raise
        except Exception as error:
            reason = str(error) if isinstance(error, PhotoDownloadError) else type(error).__name__
            feed.status(reason)
            return web.json_response({"error": "Photo could not be loaded", "reason": reason}, status=502)
        return web.Response(body=data, content_type="image/jpeg", headers={"Cache-Control": "private, max-age=1800"})
