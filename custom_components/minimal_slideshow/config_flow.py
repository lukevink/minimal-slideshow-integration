"""Provider setup and reconfiguration without dashboard credentials."""
import hashlib
import json
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN
from . import icloud
from .providers import PROVIDERS, Provider
from .vendor.synology import SynologyOtpRequired

PASSWORD=selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
PICKERS={'immich','photoprism','synology','ugreen'}

def source_schema(provider, defaults=None):
    defaults=defaults or {}; fields={vol.Required('name',default=defaults.get('name','Photos')):str}
    def add(key,required=True,default=None,password=False):
        spec={}
        if key in defaults:spec['default']=defaults[key]
        elif default is not None:spec['default']=default
        fields[(vol.Required if required else vol.Optional)(key,**spec)]=PASSWORD if password else str
    if provider in ('icloud','google','nextcloud_public','ente'):add('album_url',password=True)
    if provider in ('immich','photoprism','synology','ugreen','nextcloud'):add('url')
    if provider=='ente':add('url',False)
    if provider=='immich':add('api_key',password=True)
    if provider=='photoprism':
        fields[vol.Required('auth_method',default=defaults.get('auth_method','app_password'))]=vol.In({'app_password':'App password','password':'Username and password'})
        add('api_key',False,password=True);add('username',False);add('password',False,password=True)
    if provider in ('synology','ugreen','nextcloud'):add('username');add('password',password=True)
    if provider=='synology':
        fields[vol.Required('space',default=defaults.get('space','personal'))]=vol.In({'personal':'Personal','shared':'Shared Space'})
        add('otp_code',False,password=True)
    if provider in ('nextcloud','local'):
        add('folder',provider=='local',defaults.get('folder',''))
        fields[vol.Optional('recursive',default=defaults.get('recursive',True))]=bool
    if provider=='media_source':
        fields[vol.Required('media',default=defaults.get('media',{'media_content_id':defaults.get('media_content_id','media-source://media_source'),'media_content_type':'image'}))]=selector.MediaSelector()
    return vol.Schema(fields)

async def validate(hass,values):
    """Validate an iCloud source. Kept separate for the legacy migration."""
    parsed=icloud.parse_share(values['album_url'])
    if not parsed:raise ValueError('invalid_url')
    token,backend=parsed
    client=icloud.IcloudCloudKitClient if backend=='cloudkit' else icloud.IcloudClient
    await client(hass,token).async_validate()
    return {'provider':'icloud','token':token,'backend':backend},values.get('name') or 'Photos'

class MinimalSlideshowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION=1
    def __init__(self):
        self._data={};self._provider=None;self._client=None;self._choices={};self._title='Photos';self._reconfigure=False

    async def async_step_user(self,user_input=None):
        if user_input:
            self._provider=user_input['provider']
            if self._provider=='existing_icloud':return await self.async_step_existing_icloud()
            return await self.async_step_source()
        options=dict(PROVIDERS)
        if self._existing_icloud():options['existing_icloud']='Existing iCloud source (copy settings)'
        return self.async_show_form(step_id='user',data_schema=vol.Schema({vol.Required('provider',default='icloud'):vol.In(options)}))

    def _existing_icloud(self):
        return {e.entry_id:e for e in self.hass.config_entries.async_entries('album_slideshow') if e.data.get('icloud_token')}

    async def async_step_existing_icloud(self,user_input=None):
        entries=self._existing_icloud();errors={}
        if not entries:return self.async_abort(reason='no_existing_source')
        if user_input:
            entry=entries.get(user_input['entry_id'])
            if entry:
                self._data={'provider':'icloud','token':entry.data['icloud_token'],'backend':entry.data.get('icloud_backend','sharedstreams')};self._title=entry.title
                client=icloud.IcloudCloudKitClient if self._data['backend']=='cloudkit' else icloud.IcloudClient
                try:
                    await client(self.hass,self._data['token']).async_validate()
                    return await self._save()
                except Exception:errors['base']='cannot_connect'
        return self.async_show_form(step_id='existing_icloud',data_schema=vol.Schema({vol.Required('entry_id'):vol.In({key:e.title for key,e in entries.items()})}),errors=errors)

    async def async_step_reconfigure(self,user_input=None):
        entry=self._get_reconfigure_entry();self._reconfigure=True
        self._data=dict(entry.data);self._provider=self._data.get('provider','icloud');self._title=entry.title
        return await self.async_step_source()

    async def async_step_source(self,user_input=None):
        errors={}
        if user_input:
            self._title=user_input.get('name') or 'Photos'
            values={**self._data,**user_input,'provider':self._provider};values.pop('name',None)
            if 'media' in values:values['media_content_id']=values.pop('media')['media_content_id']
            client=None
            try:
                if self._provider=='icloud':
                    values,_=await validate(self.hass,user_input)
                else:
                    client=Provider(self.hass,values);await client.connect()
                    if self._provider in PICKERS:
                        self._choices=await client.choices();self._data=values
                        return await self.async_step_selection()
                    if not await client.records():raise ValueError('no_photos')
                self._data=values
                return await self._save()
            except SynologyOtpRequired:errors['base']='otp_required'
            except ValueError as error:errors['base']=str(error) if str(error) in ('invalid_url','invalid_path','no_photos') else 'cannot_connect'
            except Exception:errors['base']='cannot_connect'
            finally:
                if client:await client.close()
        defaults={**self._data,'name':self._title}
        # Preserve a Synology trusted-device token but never prefill a transient OTP.
        defaults.pop('otp_code',None)
        return self.async_show_form(step_id='source',data_schema=source_schema(self._provider,defaults),errors=errors,description_placeholders={'provider':PROVIDERS[self._provider]})

    async def async_step_selection(self,user_input=None):
        errors={};saved=self._data.get('selection',{})
        if user_input is not None:
            selection={k:v for k,v in user_input.items() if k!='search'}
            values={**self._data,'selection':selection,'search':user_input.get('search','')}
            client=Provider(self.hass,values)
            try:
                if self._provider=='immich' and values['search']:
                    if not isinstance(json.loads(values['search']),dict):raise ValueError('invalid_search')
                if self._provider=='ugreen' and not selection.get('albums'):raise ValueError('no_photos')
                if not await client.records():raise ValueError('no_photos')
                self._data=values;return await self._save()
            except ValueError as error:errors['base']=str(error) if str(error) in ('no_photos','invalid_search') else 'cannot_connect'
            except Exception:errors['base']='cannot_connect'
            finally:await client.close()
        fields={}
        for key,choices in self._choices.items():
            # Keep saved choices even if temporarily unavailable at the server.
            choices={**{str(v):str(v)+' (saved)' for v in saved.get(key,[])},**choices}
            fields[vol.Optional(key,default=saved.get(key,[]))]=selector.SelectSelector(selector.SelectSelectorConfig(options=[{'value':k,'label':v} for k,v in choices.items()],multiple=True,mode=selector.SelectSelectorMode.DROPDOWN))
        if self._provider!='ugreen':fields[vol.Optional('favorites',default=saved.get('favorites',False))]=bool
        if self._provider in ('immich','photoprism'):fields[vol.Optional('search',default=self._data.get('search',''))]=str
        return self.async_show_form(step_id='selection',data_schema=vol.Schema(fields),errors=errors)

    async def _save(self):
        # Identity uses source location/account/selection, never an exposed credential.
        identity={k:v for k,v in self._data.items() if k not in ('password','api_key','device_id','otp_code')}
        unique=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        if self._reconfigure:
            entry=self._get_reconfigure_entry()
            if any(other.entry_id!=entry.entry_id and other.unique_id==unique for other in self._async_current_entries()):return self.async_abort(reason='already_configured')
            self.hass.config_entries.async_update_entry(entry,title=self._title,unique_id=unique)
            return self.async_update_reload_and_abort(entry,data_updates=self._data)
        await self.async_set_unique_id(unique);self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self._title,data=self._data)
