# Team Hub for Windows

The SaxsProjects Team Hub in its own window (Tauri 2 with the built-in Edge WebView2). It shows
https://hub.saxsprojects.co.za, the same Team Hub as on the web, and adds:

- **Windows Hello unlock** (face, fingerprint or PIN) through passkeys, after "Keep me signed in" (see docs/deploy.md, "Trusted devices").
- A Start menu entry and one window only (opening it again brings the window forward).
- Remembers the window's size and place.
- A "You're offline" page that opens the hub by itself when the internet is back.
- Downloads go to `Downloads\Team Hub`.
- **Automatic updates** from the GitHub releases: the app asks, installs in a few seconds and reopens.

The pages get no access to the computer: the hub is loaded as an ordinary website with no app commands
exposed to it. Only `hub.` and `api.saxsprojects.co.za` open inside the window; other links open in the
normal browser (`src-tauri/src/lib.rs`).

## Installing

From the latest GitHub release, download **`saxs-team-hub-windows-X.Y.Z-setup.exe`** (installs for you only,
no admin) or the `.msi` (for IT installs). Check it against `SHA256SUMS.txt` if you like.

The installer is not code-signed (a certificate costs money), so Windows SmartScreen says
"Windows protected your PC". Click **More info**, then **Run anyway**. Microsoft Defender rules that block
unknown programs may also stop it; see "Security software" below.

## Updates

Releases include `latest.json` and `.sig` files. The installed app checks
`releases/latest/download/latest.json` when it starts and only installs an update whose signature matches the
public key in `src-tauri/tauri.conf.json`. The private key lives only in the GitHub secrets
`TAURI_SIGNING_PRIVATE_KEY` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` and in the founder's backup. **If it is lost,
installed apps can't update themselves any more**; people would reinstall once from a release made with a new key.

## Building

CI builds and tests it on `windows-latest` (`.github/workflows/ci.yml`, job `windows`) and the release workflow
attaches the installers. Locally: Rust (stable, MSVC) and Node 22, then `npm ci` and `npm run build` in `desktop/`.

### Security software

A Microsoft Defender attack-surface-reduction rule ("Block executable files from running unless they meet a
prevalence, age, or trusted list criterion") blocks freshly compiled programs, including Rust build scripts,
so local builds fail with "Access is denied (os error 5)". Build in CI instead, or ask whoever manages the PC's
Defender settings for an exclusion.
