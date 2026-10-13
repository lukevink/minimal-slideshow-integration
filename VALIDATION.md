# Local validation — 13 October 2026

## Card

- Node layout tests: passed screen-orientation selection, proportional crop selection, fresh-photo priority, local grid changes, and contiguous tile paths to screen edges.
- Browser tests: passed 24 transitions across six styles, four clock corners, and disconnect cleanup.
- Browser geometry run: passed 24 mask/tile transitions over 719 sampled frames, with no intersecting scene tiles and aligned clock/date edges. Shifting Tiles uses uniform scale-away and whole-tile side entry with a bounded rebound, not shutter reveals.
- Automation event test: Next changes the image; Previous restores the preceding frame; Next restores forward history; Restart resets playback; commands for another source are ignored; subscription is removed on disconnect.

## Integration

44 offline tests passed against Home Assistant 2026.10.1 on Python 3.14. Coverage includes all eleven provider setup schemas, source adapter contracts, thumbnail sizes, Synology trusted-device handling, local symlink protection, cross-origin credential filtering, image proportions/metadata stripping, opaque photo API responses, setup errors, unloading and the three button commands. Provider responses in the automated tests are mocked. Live iCloud setup and photo rendering were verified in Home Assistant. That check found video derivatives in Shared Streams; they are now excluded and covered by a regression test. Other providers still require account-based acceptance testing. The deployed source reports 2,395 still photos, ready status, and all three command events (last: restart). The tablet reload action completed and its current-page sensor confirmed the updated slideshow URL. GitHub Node tests, Python tests and hassfest passed; HACS remains skipped while private.

## Release status

GitHub HACS/hassfest workflows are included. Source and distribution files are prepared for the v1.2.0 release. A GitHub release and HACS default-catalog submission are separate publishing steps. HACS remote validation requires a public repository because it retrieves raw files anonymously; that job is skipped while the repositories are private.
