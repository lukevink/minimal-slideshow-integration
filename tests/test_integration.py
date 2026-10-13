"""Offline tests against real Home Assistant classes; no private album needed."""
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from PIL import Image
from aiohttp import web
from homeassistant.core import HomeAssistant
from custom_components.minimal_slideshow import config_flow, feed, views, icloud
from custom_components.minimal_slideshow.const import DOMAIN
from custom_components.minimal_slideshow import async_setup_entry, async_unload_entry
from homeassistant.exceptions import ConfigEntryNotReady

@pytest.mark.parametrize('url,allowed', [
    ('https://p01.icloud-content.com/picture', True),
    ('https://apple.com.evil.test/picture', False),
    ('https://icloud.com.evil.test/picture', False),
    ('http://p01.icloud-content.com/picture', False),
    ('https://user:password@p01.icloud.com/picture', False),
    ('https://p01.icloud.com:8443/picture', False),
    ('http://127.0.0.1:8123/api/', False),
])
def test_image_host_guard(url, allowed):
    assert feed.safe_image_url(url) is allowed

@pytest.mark.parametrize('size,expected', [((2400,1200),(1800,900)),((600,1200),(600,1200))])
def test_jpeg_keeps_aspect_ratio_and_strips_metadata(size, expected):
    raw=BytesIO(); image=Image.new('RGB',size,'red'); exif=Image.Exif(); exif[270]='private caption'
    image.save(raw,'JPEG',exif=exif)
    data,width,height=feed.render_photo(raw.getvalue())
    assert (width,height)==expected
    with Image.open(BytesIO(data)) as output:
        assert output.format=='JPEG'
        assert not output.getexif()

def request(feeds, entry=None):
    return SimpleNamespace(app={'hass':SimpleNamespace(data={DOMAIN:feeds})},query={'entry_id':entry} if entry else {})

@pytest.mark.asyncio
async def test_catalog_hides_signed_urls_and_routes_require_auth():
    f=SimpleNamespace(entry=SimpleNamespace(entry_id='album'),title='Test',items={'x':{'id':'x','url':'https://secret','width':100,'height':50}},refresh=AsyncMock())
    response=await views.CatalogView().get(request({'album':f}))
    data=json.loads(response.body)
    assert data['photos']==[{'id':'x','width':100,'height':50}]
    assert 'secret' not in response.text
    assert all(v.requires_auth for v in (views.AlbumsView,views.CatalogView,views.PhotoView))
    with pytest.raises(web.HTTPNotFound):
        views.get_feed(request({'album':f},'missing'))

@pytest.mark.asyncio
async def test_refresh_failure_retains_previous_catalog():
    f=SimpleNamespace(entry=SimpleNamespace(entry_id='album'),title='Test',items={'x':{'id':'x'}},refresh=AsyncMock(side_effect=RuntimeError('secret')))
    assert (await views.CatalogView().get(request({'album':f}))).status==200
    f.items={}
    response=await views.CatalogView().get(request({'album':f}))
    assert response.status==503
    assert 'secret' not in response.text

@pytest.mark.asyncio
async def test_feed_refresh_uses_own_config_and_ignores_untrusted_assets():
    hass=SimpleNamespace(); entry=SimpleNamespace(data={'token':'test','backend':'cloudkit'},title='Test')
    f=feed.PhotoFeed(hass,entry)
    records=[{'source_id':'one','url':'https://p01.icloud-content.com/photo','width':1200,'height':800},
             {'source_id':'bad','url':'http://127.0.0.1/private','width':1,'height':1}]
    with patch.object(icloud.IcloudCloudKitClient,'async_get_items',AsyncMock(return_value=records)) as get:
        await f.refresh(); await f.refresh()
    assert get.await_count==1
    assert len(f.items)==1
    assert list(f.items.values())[0]['width']==1200
    assert all('one'!=key for key in f.items)

@pytest.mark.asyncio
async def test_camera_free_config_flow(tmp_path):
    hass=HomeAssistant(str(tmp_path))
    hass.config_entries=SimpleNamespace(async_entries=lambda domain:[])
    flow=config_flow.MinimalSlideshowConfigFlow();flow.hass=hass
    form=await flow.async_step_user()
    assert form['step_id']=='user'
    flow._provider='icloud'
    with patch.object(config_flow,'validate',AsyncMock(side_effect=ValueError('invalid_url'))):
        form=await flow.async_step_source({'album_url':'invalid'})
        assert form['errors']=={'base':'invalid_url'}
    with patch.object(config_flow,'validate',AsyncMock(side_effect=RuntimeError('secret token'))):
        form=await flow.async_step_source({'album_url':'invalid'})
        assert form['errors']=={'base':'cannot_connect'}

@pytest.mark.asyncio
async def test_validates_album_without_another_integration():
    with patch.object(icloud.IcloudClient,'async_validate',AsyncMock(return_value='Test')):
        data,title=await config_flow.validate(None,{'album_url':'https://www.icloud.com/sharedalbum/#ABTestAlbum','name':'Our photos'})
    assert data=={'provider':'icloud','token':'ABTestAlbum','backend':'sharedstreams'}
    assert title=='Our photos'

@pytest.mark.asyncio
async def test_setup_failure_is_retried_without_secret_exception():
    with patch.object(feed.PhotoFeed,'refresh',AsyncMock(side_effect=RuntimeError('secret'))):
        with pytest.raises(ConfigEntryNotReady) as exc:
            await async_setup_entry(SimpleNamespace(),SimpleNamespace(data={}))
    assert 'secret' not in str(exc.value)

@pytest.mark.asyncio
async def test_unload_removes_memory_cache():
    hass=SimpleNamespace(data={DOMAIN:{'test':SimpleNamespace(close=AsyncMock())}},config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True)))
    assert await async_unload_entry(hass,SimpleNamespace(entry_id='test'))
    assert hass.data[DOMAIN]=={}
