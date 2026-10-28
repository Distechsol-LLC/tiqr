# Windows installer: assumptions and open items

`tiqr.iss` is an Inno Setup 6.2+ (Unicode) script. Compile it after the release workflow assembles the
bundle: `iscc /DBundleDir=bundle\tiqr-Windows-X64 /DAppVersion=<version> packaging\windows\tiqr.iss`.
`timezones.txt` is its time zone list; regenerate it with `uv run python packaging/windows/gen_timezones.py`.

## Needs your decision (not changed, flagged)

1. **Name.** The installer builds as `tiqr_setup.exe`, as requested. The packaged app stays `tiqr.exe`.
2. **Where the app reads the file.** The frozen Windows app, with `TIQR_HOME` unset, reads
   `%ProgramData%\TiQR` (`settings._project_root`). The installer writes `tiqr_brand.jsonc` and the logo
   there, and also copies them beside `tiqr.exe`. The app runtime is unchanged.
3. **Running `tiqr install`.** The installer runs `tiqr.exe install --source <install folder> --host <host>
   --port <port>` after copying files. `tiqr install` keeps an existing branding file in the data folder,
   so the installer first saves that file as `tiqr_brand.jsonc.bak` and replaces it with the wizard's
   file. A reinstall therefore takes the new wizard values. The docs say a reinstall keeps the branding
   already in place, so confirm this is the intended behaviour.
4. **"Takes effect without reinstalling."** The app reads the file on every start, so a hand edit applies
   after a restart (the file's own header says so), not live. No app change was made for live reload.
5. **TLS on/off.** The schema has no TLS flag, only `tls_cert` and `tls_key` (both or neither). "On"
   therefore asks for a certificate and a key file on an extra page; "off" writes both as `null`.
   Files are referenced where they are, not copied, so the private key never lands in Program Files.
6. **Service.** The installer runs `tiqr install` (service, firewall, health check). It does not create the
   first admin account, which `tiqr install` asks for only at a terminal. Set one with `tiqr user add`
   afterwards. The bundle's `INSTALL.txt` still mentions `install.cmd`, which the installer does not ship.

## Assumptions about the schema

- Keys, order and comments are those of the committed `tiqr_brand.jsonc`; no key is added or renamed.
  `tests/test_windows_installer.py` fails if the generator's keys drift from that file.
- A blank optional field is written as `null` (keeps the lower layer). The pages are pre-filled with the
  constructor's defaults, so they are written explicitly unless the user clears them.
- `theme`: the 24 names in `apps/web/src/data/themes.ts`. `vintage` is written as `"default"`, the
  constructor's value for it.
- `languages`: `en-US`, `ru-RU`, `az-AZ`, `kk-KZ`. The app also accepts other language/region pairs
  (for example `en-RU`); the installer offers only the four canonical ones. The first ticked is the default.
- `prefix`: exactly 3 printable ASCII characters, none of `:` `-`.
- `default_tz`: any name in `timezones.txt` (598 names from `zoneinfo`), case-sensitive.
- `port`: integer 1-65535. `sync_interval`, `cleanup_interval`: whole seconds, 0 or more (0 = off).
  Values are capped at 9 digits; the app has no upper limit.
- `host`: letters, digits, `.`, `-`, `_`, `:` only. The app does no check; this is a sanity filter.
- `server_printing`, `verify_tls`: JSON booleans. `timeout`: positive number (`2.5` allowed);
  `door_open_duration`, `door_open_timeout`: integers of 1 or more.
- BioStar: all-or-nothing. Local mode writes every field `null`. With BioStar, `base_url` (HTTPS, no
  credentials, ends at the host or `/api`), `username` and at least one device ID are required.
- `device_ids` is written as a JSON array of strings (the template shows only `null`). The app accepts
  an array or a string either way.
- **Passwords are not collected.** The BioStar password is not a key in the file and must go in
  `.env.local` as `TIQR_BIOSTAR_PASSWORD`; the app refuses a BioStar block without it.
- Output is pure ASCII: non-ASCII text (for example a Russian app name) is written as `\uXXXX`
  escapes. It is valid JSON, and avoids the byte order mark the app's parser rejects.

## Behaviour

- **Logo.** Validated on the page and again in `PrepareToInstall`: extension in `.png .svg .jpg .jpeg`,
  file readable, up to 20 MB, and content matches the type (PNG/JPEG signature, `<svg` tag). It is copied
  to a temporary folder when the user confirms; a failure returns an error that stops the install. Setup
  then installs it as `logo.<original extension>` and the JSON says `"logo.<ext>"`. The original is never
  referenced after that.
- **Reinstall.** An existing `tiqr_brand.jsonc` in the install folder and in the data folder is saved as
  `tiqr_brand.jsonc.bak` before it is replaced, and logos with a different extension from an earlier
  install are removed.
- **Uninstall.** Removes `tiqr_brand.jsonc`, its `.bak` and the logo from both the install folder and the
  data folder. The user's original image is not in the list. The service, database and
  `%ProgramData%\TiQR` are not touched; unregistering the service is still a manual step.
- **Skeleton link.** `https://www.skeleton.dev/docs/svelte/design/themes` (found by search; the
  `[SKELETON_UI_THEME_URL]` and `[SUPPORTED_LANGUAGES]` placeholders in the task were left unfilled, so the
  language list comes from `core/languages.py`).

## Not verified

- **The script has not been compiled or run.** There is no Inno Setup, Wine or Windows here. Syntax and
  the Pascal Script calls (`FileSize`, `LoadStringFromFile`, `{code:}` in `[Files]`) follow the Inno
  documentation from memory. Compile it with `iscc` and run through the wizard once before releasing.
- What is checked (`tests/test_windows_installer.py`): the theme, language, default, key-order and time
  zone lists against the app, and a sample of the generated file against `settings.load_branding`.
  The generator itself was not executed.
- The acceptance checks that need a real install (logo copied, original deleted, hand edit applied,
  uninstall result) are untested.
