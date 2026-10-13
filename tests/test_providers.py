"""Provider adapter contracts with synthetic responses, no real credentials."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from PIL import Image
from custom_components.minimal_slideshow import providers, button, views
from custom_components.minimal_slideshow.providers import Provider, origin, scan_folder
from custom_components.minimal_slideshow.const import DOMAIN

@pytest.fixture
def hass(tmp_path):
    async def executor(fn,*args):return fn(*args)
    return SimpleNamespace(config=SimpleNamespace(media_dirs={'local':str(tmp_path)},is_allowed_path=lambda path:False),async_add_executor_job=executor)

@pytest.mark.parametrize('kind',list(providers.PROVIDERS))
def test_all_providers_have_a_setup_schema(kind):
    from custom_components.minimal_slideshow.config_flow import source_schema
    schema=source_schema(kind)
    assert len(schema.schema)>1

@pytest.mark.parametrize('url',['file:///etc/passwd','https://user:secret@example.com','javascript:alert(1)','https://example.com:bad'])
def test_invalid_origins_rejected(url):
    with pytest.raises(ValueError):origin(url)

@pytest.mark.asyncio
async def test_local_folder_symlink_escape_and_image_read(hass,tmp_path):
    good=tmp_path/'image.jpg';Image.new('RGB',(100,50)).save(good)
    (tmp_path/'not-an-image.txt').write_text('secret')
    (tmp_path/'outside.jpg').symlink_to('/etc/passwd')
    provider=Provider(hass,{'provider':'local','folder':str(tmp_path)})
    records=await provider.records()
    assert len(records)==1
    assert (await provider.image(records[0])).startswith(b'\xff\xd8')
    assert provider.allowed_path(tmp_path)

@pytest.mark.asyncio
async def test_immich_and_photoprism_keep_auth_server_side(hass):
    for kind,module,clientname,asset in [
        ('immich',providers.immich,'ImmichClient',{'id':'asset','width':100,'height':50}),
        ('photoprism',providers.photoprism,'PhotoprismClient',{'UID':'asset','Hash':'hash','Width':100,'Height':50})]:
        client=SimpleNamespace(async_validate=AsyncMock(),async_collect_assets=AsyncMock(return_value=[asset]),base_url='https://photos.test',image_headers={'x-api-key':'secret'},preview_token='private-preview')
        with patch.object(module,clientname,return_value=client):
            source=Provider(hass,{'provider':kind,'url':'https://photos.test','api_key':'secret','selection':{'albums':['family']}})
            result=await source.records()
        assert len(result)==1 and result[0]['width']==100
        assert client.async_collect_assets.await_args.args[0]=='composite'
        if kind=='photoprism':assert result[0]['url'].endswith('/fit_1280')

@pytest.mark.asyncio
async def test_synology_trusted_device_and_thumbnail(hass):
    client=SimpleNamespace(async_login=AsyncMock(),captured_device_id='trusted',base_url='https://nas.test',image_headers={'Cookie':'sid=secret'},async_collect_composite=AsyncMock(return_value=[{'id':1}]))
    with patch.object(providers.synology,'SynologyClient',return_value=client),patch.object(providers.synology,'thumbnail_ref',return_value=(1,'cache')),patch.object(providers.synology,'parse_photo_meta',return_value={'width':100,'height':50}):
        source=Provider(hass,{'provider':'synology','url':'https://nas.test','username':'u','password':'secret','otp_code':'123456','selection':{'albums':['shared:album-token','2']}})
        result=await source.records()
    assert source.data['device_id']=='trusted'
    assert 'otp_code' not in source.data
    assert len(result)==1 and 'secret' not in result[0]['url']
    assert client.async_collect_composite.await_args.args[0]['passphrases']==['album-token']

@pytest.mark.asyncio
async def test_ugreen_selected_album_type(hass):
    client=SimpleNamespace(async_login=AsyncMock(),base_url='https://nas.test',image_headers={'Cookie':'secret'},image_params={'ugk':'secret'},async_list_album_pictures=AsyncMock(return_value=[{'picture_id':12}]))
    with patch.object(providers.ugreen,'UGreenClient',return_value=client):
        source=Provider(hass,{'provider':'ugreen','url':'https://nas.test','username':'u','password':'p','selection':{'albums':['["album", 3]']}})
        result=await source.records()
    client.async_list_album_pictures.assert_awaited_once_with('album',3)
    assert result[0]['params']=={'ugk':'secret'}

@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['nextcloud','nextcloud_public'])
async def test_nextcloud_rejects_foreign_credential_destination(hass,kind):
    client=SimpleNamespace(async_validate=AsyncMock(),async_list_photos=AsyncMock(return_value=[{'href':'https://cloud.test/image.jpg','file_id':'one'},{'href':'https://evil.test/image.jpg','file_id':'evil'}]),base_url='https://cloud.test',image_headers={'Authorization':'Basic secret'})
    cls='NextcloudClient' if kind=='nextcloud' else 'NextcloudPublicClient'
    with patch.object(providers.nextcloud,cls,return_value=client):
        source=Provider(hass,{'provider':kind,'url':'https://cloud.test','username':'u','password':'p','album_url':'https://cloud.test/apps/photos/public/TEST'})
        result=await source.records()
    assert len(result)==1 and result[0]['source_id']=='one'

@pytest.mark.asyncio
async def test_google_has_no_third_party_scraping_service(hass):
    items=[SimpleNamespace(source_id='one',url='https://lh3.googleusercontent.com/photo',width=100,height=50),SimpleNamespace(source_id='evil',url='https://evil.test/photo',width=1,height=1)]
    with patch.object(providers,'async_get_clientsession',return_value=object()),patch.object(providers.google_scraper,'fetch_album',AsyncMock(return_value=('Test',items,set()))) as fetch:
        result=await Provider(hass,{'provider':'google','album_url':'https://photos.app.goo.gl/test'}).records()
    assert fetch.await_count==1 and len(result)==1

@pytest.mark.asyncio
async def test_ente_keeps_keys_out_of_public_catalog(hass):
    client=SimpleNamespace(async_validate=AsyncMock(),share=SimpleNamespace(collection_key=b'x'*32),async_list_files=AsyncMock(return_value=[{'id':1,'thumbnail':{'decryptionHeader':'private'}}]))
    with patch.object(providers.ente,'parse_share_link',return_value=object()),patch.object(providers.ente,'EnteClient',return_value=client),patch.object(providers.ente,'decrypt_file_key',return_value=b's'*32),patch.object(providers.ente,'decrypt_metadata',return_value={'fileType':0,'width':100,'height':50}),patch.object(providers.ente,'is_image',return_value=True):
        result=await Provider(hass,{'provider':'ente','album_url':'https://albums.ente.io/test'}).records()
    assert result[0]['key']==b's'*32 and 'url' not in result[0]
    f=SimpleNamespace(entry=SimpleNamespace(entry_id='album'),title='Test',refresh=AsyncMock(),items={'one':{**result[0],'id':'one'}})
    req=SimpleNamespace(app={'hass':SimpleNamespace(data={DOMAIN:{'album':f}})},query={})
    response=await views.CatalogView().get(req)
    assert 'private' not in response.text and 'key' not in response.text and 'ente_id' not in response.text

@pytest.mark.asyncio
async def test_media_source_browses_nested_images(hass):
    from homeassistant.components import media_source
    leaf=SimpleNamespace(media_content_id='media-source://test/image',media_content_type='image/jpeg',media_class='image',can_expand=False)
    folder=SimpleNamespace(media_content_id='media-source://test/folder',media_content_type='',media_class='directory',can_expand=True)
    async def browse(_hass,path):return SimpleNamespace(children=[folder] if path.endswith('root') else [leaf])
    with patch.object(media_source,'async_browse_media',browse):
        items=await Provider(hass,{'provider':'media_source','media_content_id':'media-source://test/root'}).records()
    assert len(items)==1 and items[0]['media_id'].endswith('/image')

@pytest.mark.asyncio
@pytest.mark.parametrize('action',['next','previous','restart'])
async def test_buttons_emit_source_scoped_commands(action):
    f=SimpleNamespace();hass=SimpleNamespace(data={DOMAIN:{'album':f}},bus=SimpleNamespace(async_fire=lambda *args:events.append(args)))
    events=[];entry=SimpleNamespace(entry_id='album')
    entity=button.SlideshowButton(hass,entry,action)
    with patch.object(button,'async_dispatcher_send'):
        await entity.async_press();await entity.async_press()
    assert events[-1]==('minimal_slideshow_command',{'entry_id':'album','command':action,'sequence':2})
