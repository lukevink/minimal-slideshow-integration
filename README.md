# Minimal Slideshow integration

Connect your photo library to [Minimal Photo Slideshow](https://github.com/lukevink/minimal-slideshow) and control playback from Home Assistant automations. Individual photo files go to the card, with provider credentials kept on the Home Assistant server.

## Photo sources

| Source | Connect with | Choose photos |
| --- | --- | --- |
| iCloud | Public shared-album link | That shared album |
| Google Photos | Shared-album link | That shared album |
| Immich | Server URL and read-only API key | Albums, people, favorites, whole library, optional JSON search |
| PhotoPrism | Server URL and app password, or username/password | Albums, people, favorites, whole library, optional search |
| Synology Photos | DSM URL and account; optional initial two-factor code | Personal/shared library, albums, people, places, tags, subjects, favorites |
| UGREEN Photos | UGOS server URL and account | One or more albums; experimental API |
| Nextcloud folder | Server URL, username and app password | WebDAV folder, optionally including subfolders |
| Nextcloud public album | Public Photos album link | That shared album |
| Ente Photos | Public album link containing its decryption key | That shared album; optional custom Ente API origin |
| Local folder / NAS | Folder readable by Home Assistant | Folder, optionally including subfolders |
| Home Assistant Media Source | A folder selected in the media browser | Images in that folder and its subfolders |

This integration is for still photos. It does not import the upstream camera, video playback, face recognition, metadata enrichment, geocoding, or slideshow renderer.

## Install through HACS

1. Add `https://github.com/lukevink/minimal-slideshow-integration` as an **Integration** custom repository in HACS.
2. Download and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Minimal Slideshow**.
4. Choose a provider and enter its connection details. Server-based libraries offer a second step for choosing albums and other collections.
5. Install the [card](https://github.com/lukevink/minimal-slideshow) as a separate HACS **Dashboard** repository. Choose your configured source in its visual editor.

Add another integration entry for another source. Use **Reconfigure** on an entry to update its credentials or photo selection. Manual installation: copy `custom_components/minimal_slideshow` to `/config/custom_components/` and restart. Tested with Home Assistant 2026.10.1; minimum declared version is 2026.10.0.

## Provider setup notes

- **iCloud:** enable **Public Website** for a Shared Album in Apple Photos and copy its link. Both legacy `www.icloud.com/sharedalbum/#…` and newer `photos.icloud.com/shared/album/…` links are supported. This does not sign into or read an entire private iCloud Photos library.
- **Google Photos:** enable link sharing and copy the album link. Listing uses Google's shared-album web endpoints directly; no third-party scraping service receives the link.
- **Immich:** use read scopes including `server.about`, `asset.read`, `asset.view`, `asset.download`, `album.read`, and `person.read`. Multiple selections are combined and deduplicated. Search is a JSON object, for example `{"city":"Amsterdam"}`.
- **PhotoPrism:** an app password is recommended. Search accepts ordinary PhotoPrism query text, for example `year:2025`. Display uses 1280-pixel previews before the common image pipeline.
- **Synology:** use a non-admin account with access to the desired Photos library. When required, enter a current two-factor code; the integration retains the returned trusted-device token, not the one-time code. Available categories depend on the selected library and permissions.
- **UGREEN:** select at least one album. The API is undocumented and may change between UGOS versions. Certificate verification stays enabled.
- **Nextcloud:** folder mode uses an app password over WebDAV. The public-link option is for a Nextcloud **Photos album** share, not an arbitrary file-share URL. Some servers disable recursive WebDAV listings; disable “Include subfolders” in that case.
- **Ente:** the full public link includes the album key after `#`. Decryption occurs on Home Assistant. The optional server URL must be an Ente API origin. Password-protected album links are not supported.
- **Local/NAS:** mount network storage in Home Assistant first. Choose a directory in `media_dirs` or add it to `homeassistant.allowlist_external_dirs`. Scanning and reading check resolved paths and skip symlinks that escape the selected folder. JPEG, PNG, WebP, GIF, BMP and TIFF files are accepted; animated formats display a still frame.
- **Media Source:** select a folder that the installed media-source integration exposes. Browsing is recursive and bounded; images are resolved on demand. The upstream provider determines which files it makes available.

Public share links remain public at their original providers to anyone who has the link. Some shared-album/NAS endpoints are unofficial and may require updates if their providers change them.

## Automation controls

Every configured source creates:

- **Next Image** button: advances the slideshow in open cards displaying that source.
- **Previous Image** button: restores the previous photo composition from that card's session history.
- **Restart** button: returns to the start of that card's current shuffled playlist and clears its history.
- **Photos** sensor: photo count, source ID, number of photos served, last command and command sequence.

Use **Button: Press** (`button.press`) in any Home Assistant automation. Actual entity IDs depend on the source name and any renaming in your installation. Example:

```yaml
actions:
  - action: button.press
    target:
      entity_id: button.family_photos_next_image
```

Choose the actual button from the entity picker. There are no custom services to register. Commands are scoped to the source and affect every currently open Minimal card using it. They are not queued for closed browsers. Each browser keeps its own shuffled playlist and up to 30 history frames; this is not synchronized video playback. In a grid, “Next Image” advances the next animation beat, which may change one or two photos or the layout. Floating history restores the last introduced photo.

Tablet power, idle timing, proximity and dashboard routing remain separate Home Assistant/Fully Kiosk automations.

## Card example

```yaml
type: custom:minimal-photo-slideshow
source: minimal_slideshow
# Select album_id in the card's visual editor for multiple configured sources.
effect: origami
interval: 8
duration: 1800
```

## Data handling

Config entries store connection credentials. API responses and sensor attributes expose opaque photo IDs and dimensions, never provider passwords, signed URLs, local file paths or Ente keys. The photo routes require Home Assistant authentication; authenticated Home Assistant users can access configured sources, so this is not a per-user album permission system.

Images are resized proportionally to at most 1800 pixels on the longest edge. Orientation is applied and JPEG output omits original EXIF metadata. Downloads are bounded to 32 MiB and decoded images to 45 megapixels. Each source caches up to 24 MiB in memory and permits two concurrent image downloads. Catalogs refresh every two hours; a requested refresh or expired-image retry also renews provider sessions. Image credentials are not forwarded to a different server origin.

## Development and release

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

Tests use synthetic images and mocked provider responses, not personal accounts. See [VALIDATION.md](VALIDATION.md) for what has actually been tested. Cross-provider account testing is still needed before claiming universal compatibility.

CI runs tests, HACS validation and hassfest. Push the repository, let CI pass, then publish a GitHub release tagged `v1.2.0`; the workflow attaches `minimal_slideshow.zip`. HACS uses the single folder under `custom_components`. Default-catalog inclusion requires a separate [HACS submission](https://www.hacs.dev/docs/publish/start/) and brand assets submitted to [Home Assistant brands](https://github.com/home-assistant/brands).

## License

MIT. The adapted provider clients retain Eyal Gal's MIT license and provenance in `custom_components/minimal_slideshow/vendor/`. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Inspiration

Inspired by [Eyal Gal’s Album Slideshow](https://github.com/eyalgal/album_slideshow) and its broad photo-source support, paired with Minimal's independent dashboard animations.
