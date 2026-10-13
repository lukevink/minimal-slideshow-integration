"""Independent direct-file adapters, with credentials retained on the server."""
from __future__ import annotations
import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin, urlparse
from datetime import timedelta
from aiohttp import ClientTimeout
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .vendor import immich, photoprism, synology, nextcloud, ente, ugreen, google_scraper

PROVIDERS = {
    'icloud': 'iCloud Shared Album', 'google': 'Google Photos shared album',
    'immich': 'Immich', 'photoprism': 'PhotoPrism', 'synology': 'Synology Photos',
    'ugreen': 'UGREEN Photos (experimental)', 'nextcloud': 'Nextcloud WebDAV folder',
    'nextcloud_public': 'Nextcloud public album', 'ente': 'Ente public album',
    'local': 'Local folder / mounted NAS', 'media_source': 'Home Assistant Media Source',
}
MAX_BYTES=32*1024*1024
MAX_ITEMS=20000
EXTENSIONS={'.jpg','.jpeg','.png','.webp','.gif','.bmp','.tif','.tiff'}

def origin(url):
    p=urlparse(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
        raise ValueError('invalid_url')
    return (p.scheme,p.hostname.lower(),p.port or (443 if p.scheme=='https' else 80))

def public_link(url, hosts):
    scheme,host,_=origin(url)
    if scheme!='https' or host not in hosts: raise ValueError('invalid_url')
    return url

async def bounded_read(response):
    response.raise_for_status()
    if response.status!=200: raise ValueError('Unexpected image response')
    if response.content_length and response.content_length>MAX_BYTES: raise ValueError('Photo too large')
    chunks=[];size=0
    async for chunk in response.content.iter_chunked(65536):
        size+=len(chunk)
        if size>MAX_BYTES: raise ValueError('Photo too large')
        chunks.append(chunk)
    return b''.join(chunks)

def scan_folder(folder, recursive, allowed):
    root=Path(folder).expanduser().resolve(strict=True)
    if not root.is_dir() or not allowed(root): raise ValueError('invalid_path')
    records=[]
    for item in root.rglob('*') if recursive else root.iterdir():
        path=item.resolve()
        if not path.is_relative_to(root) or path.suffix.lower() not in EXTENSIONS or not path.is_file(): continue
        if not allowed(path): continue
        if path.stat().st_size>MAX_BYTES: continue
        records.append({'source_id':str(path),'path':str(path),'root':str(root)})
        if len(records)>=MAX_ITEMS: break
    return sorted(records,key=lambda r:r['path'])

class Provider:
    def __init__(self,hass,data):
        self.hass=hass;self.data=data;self.kind=data['provider'];self.client=None

    def allowed_path(self,path):
        # Restrict all reads, including symlink targets, to HA's allowed paths.
        roots=[Path(p).resolve() for p in getattr(self.hass.config,'media_dirs',{}).values()]
        return any(path.is_relative_to(root) for root in roots) or self.hass.config.is_allowed_path(str(path))

    async def connect(self):
        d=self.data;k=self.kind
        if 'url' in d and d['url']: origin(d['url'])
        if k=='immich':
            self.client=immich.ImmichClient(self.hass,d['url'],d['api_key']);await self.client.async_validate()
        elif k=='photoprism':
            self.client=photoprism.PhotoprismClient(self.hass,d['url'],auth_method=d.get('auth_method','app_password'),token=d.get('api_key'),username=d.get('username'),password=d.get('password'));await self.client.async_validate()
        elif k=='synology':
            self.client=synology.SynologyClient(self.hass,d['url'],d['username'],d['password'],device_id=d.get('device_id'),space=d.get('space','personal'));await self.client.async_login(d.get('otp_code'))
            if self.client.captured_device_id:d['device_id']=self.client.captured_device_id
            d.pop('otp_code',None)
        elif k=='ugreen':
            self.client=ugreen.UGreenClient(self.hass,d['url'],d['username'],d['password']);await self.client.async_login()
        elif k=='nextcloud':
            self.client=nextcloud.NextcloudClient(self.hass,d['url'],d['username'],d['password'],d.get('folder',''));await self.client.async_validate()
        elif k=='nextcloud_public':
            parsed=nextcloud.parse_share_link(d['album_url'])
            if not parsed:raise ValueError('invalid_url')
            base,token=parsed;origin(base);self.client=nextcloud.NextcloudPublicClient(self.hass,base,token);await self.client.async_validate()
        elif k=='ente':
            share=ente.parse_share_link(d['album_url'])
            if not share:raise ValueError('invalid_url')
            api=d.get('url') or None
            self.client=ente.EnteClient(self.hass,share,api);await self.client.async_validate()
        elif k=='google':public_link(d['album_url'],{'photos.google.com','photos.app.goo.gl'})

    async def choices(self):
        if self.kind not in ('immich','photoprism','synology','ugreen'):return {}
        result={}
        methods={'albums':'async_list_albums','people':'async_list_people'}
        if self.kind=='synology':methods.update(places='async_list_places',tags='async_list_tags',subjects='async_list_subjects')
        for key,method in methods.items():
            if not hasattr(self.client,method):continue
            try:values=await getattr(self.client,method)()
            except Exception:
                if key=='albums':raise
                continue
            options={}
            for value in values:
                ident=value.get('id',value.get('UID',value.get('album_uuid')))
                if self.kind=='synology' and value.get('passphrase'):ident='shared:'+value['passphrase']
                if ident is None:continue
                label=value.get('albumName') or value.get('album_name') or value.get('name') or value.get('Name') or value.get('title') or str(ident)
                if self.kind=='ugreen':ident=json.dumps([str(ident),value.get('album_type',1)])
                options[str(ident)]=str(label)
            result[key]=options
        return result

    async def records(self):
        if self.client is None:await self.connect()
        d=self.data;k=self.kind;selection=d.get('selection',{})
        records=[]
        if k=='google':
            _,items,_=await google_scraper.fetch_album(async_get_clientsession(self.hass),d['album_url'])
            for p in items:
                host=urlparse(p.url).hostname or ''
                if urlparse(p.url).scheme=='https' and (host=='googleusercontent.com' or host.endswith('.googleusercontent.com')):
                    records.append({'source_id':p.source_id or p.url,'url':p.url,'width':p.width,'height':p.height})
        elif k=='immich':
            query=json.loads(d['search']) if d.get('search') else None
            assets=await self.client.async_collect_assets('composite',json.dumps(selection),query,False)
            for p in assets:
                if p.get('id'):records.append({'source_id':p['id'],'url':immich.build_image_url(self.client.base_url,p['id'],'preview'),'headers':self.client.image_headers,'width':p.get('width'),'height':p.get('height')})
        elif k=='photoprism':
            assets=await self.client.async_collect_assets('composite',json.dumps(selection),d.get('search'))
            if not self.client.preview_token:raise ValueError('No preview token')
            for p in assets:
                if p.get('UID') and p.get('Hash'):records.append({'source_id':p['UID'],'url':photoprism.build_image_url(self.client.base_url,p['Hash'],self.client.preview_token,'fit_1280'),'width':p.get('Width'),'height':p.get('Height')})
        elif k=='synology':
            albums=selection.get('albums',[])
            sel={'album_ids':[a for a in albums if not a.startswith('shared:')],'passphrases':[a[7:] for a in albums if a.startswith('shared:')],'person_ids':selection.get('people',[]),'geocoding_ids':selection.get('places',[]),'tag_ids':selection.get('tags',[]),'concept_ids':selection.get('subjects',[]),'favorites':selection.get('favorites',False)}
            for p in await self.client.async_collect_composite(sel):
                ref=synology.thumbnail_ref(p)
                if not ref:continue
                meta=synology.parse_photo_meta(p)
                records.append({'source_id':str(p.get('_passphrase',''))+':'+str(p['id']),'url':synology.build_thumbnail_url(self.client.base_url,*ref,'xl',d.get('space','personal'),passphrase=p.get('_passphrase')),'headers':self.client.image_headers,'width':meta.get('width'),'height':meta.get('height')})
        elif k=='ugreen':
            for selected in selection.get('albums',[]):
                album,album_type=json.loads(selected)
                for p in await self.client.async_list_album_pictures(album,album_type):
                    if p.get('picture_id') is None:continue
                    meta=ugreen.parse_photo_meta(p)
                    records.append({'source_id':str(p['picture_id']),'url':ugreen.build_image_url(self.client.base_url,p['picture_id'],album,source_album_type=album_type,upload_time=p.get('upload_time',0)),'headers':self.client.image_headers,'params':self.client.image_params,'width':meta.get('width'),'height':meta.get('height')})
        elif k in ('nextcloud','nextcloud_public'):
            items=await self.client.async_list_photos(**({'recursive':d.get('recursive',False)} if k=='nextcloud' else {}))
            for p in items:
                if p.get('href'):
                    records.append({'source_id':p.get('file_id') or p['href'],'url':p['href'],'headers':getattr(self.client,'image_headers',{})})
        elif k=='ente':
            def unpack(raw):
                key=ente.decrypt_file_key(raw,self.client.share.collection_key)
                metadata=ente.decrypt_metadata(raw,key)
                if not ente.is_image(metadata):return None
                attrs=raw.get('thumbnail') or {}
                if not attrs.get('decryptionHeader'):return None
                return {'source_id':str(raw['id']),'ente_id':raw['id'],'key':key,'header':attrs['decryptionHeader'],'width':metadata.get('width'),'height':metadata.get('height')}
            for item in await self.client.async_list_files():
                try:record=await self.hass.async_add_executor_job(unpack,item)
                except Exception:continue
                if record:records.append(record)
        elif k=='local':
            records=await self.hass.async_add_executor_job(scan_folder,d['folder'],d.get('recursive',True),self.allowed_path)
        elif k=='media_source':
            from homeassistant.components import media_source
            seen=set()
            async def walk(content_id,depth=0):
                if content_id in seen or depth>12 or len(records)>=MAX_ITEMS:return
                seen.add(content_id)
                item=await media_source.async_browse_media(self.hass,content_id)
                if str(getattr(item,'media_content_type','')).startswith('image/') and not item.children:
                    records.append({'source_id':content_id,'media_id':content_id});return
                for child in item.children or []:
                    if len(records)>=MAX_ITEMS:break
                    if str(child.media_content_type).startswith('image/') or str(child.media_class)=='image':records.append({'source_id':child.media_content_id,'media_id':child.media_content_id})
                    elif child.can_expand:await walk(child.media_content_id,depth+1)
            await walk(d['media_content_id'])
        # Providers cannot redirect image credentials away from their chosen server.
        if self.client is not None and k not in ('ente',):
            base=getattr(self.client,'base_url',None)
            if base:records=[p for p in records if 'url' not in p or origin(p['url'])==origin(base)]
        return records[:MAX_ITEMS]

    async def image(self,item):
        if 'path' in item:
            def read():
                path=Path(item['path']).resolve(strict=True);root=Path(item['root'])
                if not path.is_relative_to(root) or not self.allowed_path(path):raise ValueError('invalid_path')
                with path.open('rb') as source:data=source.read(MAX_BYTES+1)
                if len(data)>MAX_BYTES:raise ValueError('Photo too large')
                return data
            return await self.hass.async_add_executor_job(read)
        if 'ente_id' in item:
            return await self.client.async_fetch_image(item['ente_id'],item['key'],item['header'],True)
        url=item.get('url')
        if 'media_id' in item:
            from homeassistant.components import media_source
            from homeassistant.helpers.network import get_url
            from homeassistant.components.http.auth import async_sign_path
            result=await media_source.async_resolve_media(self.hass,item['media_id'],None)
            url=result.url
            if url.startswith('/'):
                if url.startswith('//'):raise ValueError('invalid_url')
                url=urljoin(get_url(self.hass,prefer_external=False),async_sign_path(self.hass,url,timedelta(seconds=60)))
        origin(url)
        async with async_get_clientsession(self.hass).get(url,headers=item.get('headers',{}),params=item.get('params',{}),allow_redirects=False,timeout=ClientTimeout(total=35)) as response:
            return await bounded_read(response)

    async def close(self):
        if self.kind=='synology' and self.client and self.client.sid:
            try:await self.client.async_logout()
            except Exception:pass
