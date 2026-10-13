# Provider client provenance

Adapted from https://github.com/eyalgal/album_slideshow at commit `93dbe332f16e1beb7160e50647819c776225a489` (MIT, copyright Eyal Gal). See LICENSE.

Local modifications: asyncio timeout compatibility, a small standalone MediaItem model, removal of sensitive values from Google failure logging. These modules are used only as API clients; the upstream camera, coordinator, dashboard card, metadata enrichment and geocoding are not included.
