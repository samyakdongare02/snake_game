# Snake — Android build (Kivy)

Animated neon Snake, written in Python, packaged as a **ready-to-install Android
APK by GitHub Actions**. You do **not** need Android Studio, the Android SDK,
Java, Buildozer, ADB, `keytool` or `apksigner` — you only download and install
the APK.

The gameplay logic is pure Python and shared with the desktop version; the
mobile UI uses [Kivy](https://kivy.org). Everything you see and hear is drawn or
synthesised **from code at runtime** — the project contains no image or audio
assets.

---

## Get the signed APK

1. Open the **Actions** tab of this repository.
2. Select the newest successful **Android APK** run.
3. Download the **`Snake-1.0.0-apk`** artefact (a `.zip` containing
   `Snake-1.0.0.apk`).
4. Copy the `.apk` to your phone and open it. Android will ask you to allow
   installing apps from this source — accept, install, play.

Tagged releases (`v*`) additionally attach the APK to a **GitHub Release**, so
you can also grab it straight from the *Releases* page.

> The workflow builds and signs the APK itself. When no signing key has been
> configured (see below) an ephemeral key is generated for that build, which is
> perfectly fine for installing and playing.

---

## Installation notes

* The APK is a **release** build, signed with `apksigner` and verified in CI.
* Minimum Android version: **7.0** (API 24); targets API 34.
* Architecture: `arm64-v8a` (every phone from roughly 2017 onwards). Add
  `armeabi-v7a` to `android.archs` in `buildozer.spec` if you also need
  pre-2017 32-bit devices.
* On first launch Android may show *“Install unknown apps”* — enable it for your
  browser/file manager, install, then you can turn it back off.

### Upgrading

Android only allows an app to be updated by an APK signed with the **same key**.
Without a configured key every CI build uses a fresh, throwaway key, so to
upgrade you must uninstall the old version first. To make upgrades seamless,
add a persistent key (below) — you only have to do it once.

---

## Controls

| Action | How |
| --- | --- |
| Start / Restart | The big on-screen **TAP TO START** / **RESTART** button |
| Turn | **D-pad** in the bottom-left (Up / Left / Down / Right) |
| Turn (alternative) | **Swipe** anywhere on the playfield |
| Pause / Resume | The **Pause** button on the bottom-right |
| Sound on/off | The speaker button in the top-right HUD |

* Every direction button is at least **80 × 80 dp**, laid out as a cross so your
  thumb never has to travel far.
* Buttons show a visible **pressed** state, and the phone gives a short
  **haptic buzz** on each direction press (if the device supports it and the
  system hasn't disabled haptics).
* Turns are **queued** (up to two) and **reverse turns are ignored**, exactly
  like the desktop version, so fast double-taps can never make the snake run
  into itself.
* Controls are ignored while paused (except Pause/Resume).

### Why landscape?

The playfield is a wide 25 × 17 grid and the D-pad is placed in a bottom strip,
which only fits comfortably in landscape. The app is therefore locked to
landscape, and the layout is fully responsive: it re-computes the HUD, board and
control strip from the real screen size in *dp*, so it works from small phones
to tablets.

The app deliberately runs with the **system bars visible** (not edge-to-edge) so
Android insets the window and the control strip can never sit underneath the
navigation bar or a display cut-out. Flip `fullscreen = 1` in `buildozer.spec`
if you prefer an immersive look.

---

## Repository layout

| File | Purpose |
| --- | --- |
| `main.py` | Kivy app: rendering, touch controls, screens, sound manager. |
| `snake_core.py` | Pure-Python game logic, high scores, sound synthesis (no GUI). |
| `snake.py` | The original desktop (Tkinter) version — kept for reference. |
| `buildozer.spec` | Android packaging configuration (landscape, VIBRATE, ARM). |
| `p4a-recipes/libffi/__init__.py` | Local fix for p4a's libffi autotools failure (see below). |
| `tools/make_branding.py` | Draws `icon.png` / `presplash.png` procedurally. |
| `push_to_github.py` | Publishes this project to GitHub (git CLI or REST API). |
| `.github/workflows/android.yml` | CI: test → build → sign → publish the APK. |

---

## Publish the source to GitHub

`push_to_github.py` uploads the project in one step. It uses the `git` command
line when available, and otherwise falls back to the GitHub REST API using only
the standard library — so it works even on a machine without Git installed.

```bash
python push_to_github.py --dry-run          # preview, no network / no token
python push_to_github.py                     # prompts for a token (hidden)
python push_to_github.py --owner samyakdongare02 --repo snake_game --token ghp_xxx
python push_to_github.py --no-prune          # additive push: delete nothing
```

The token is read from `--token`, `$GITHUB_TOKEN` / `$GH_TOKEN`, or an
interactive prompt, and is **never written to disk**. A classic token needs the
`repo` scope; a fine-grained token needs *Contents: Read and write*. Fine-grained
tokens often **cannot create** repositories — if creation is refused with HTTP
403, make an empty repo on github.com and re-run with `--no-create`.

Commits are attributed to `samyakdongare02 <samyakdongare02@gmail.com>`; override
with `--author-name` / `--email`. By default the remote is kept in sync with your
working tree (files absent locally are deleted there, though always recoverable
from history) — `--no-prune` makes the push purely additive.

---

## Configure a persistent signing key (optional, recommended for upgrades)

Nothing secret ever lives in the repository. To sign with your own key, create
one and store its base64 in GitHub **Settings → Secrets and variables →
Actions**:

```bash
keytool -genkeypair -v -keystore release.keystore -alias snake \
  -keyalg RSA -keysize 2048 -validity 10000
base64 -w0 release.keystore > release.keystore.b64   # macOS: base64 -i
```

Add these repository secrets:

| Secret | Value |
| --- | --- |
| `ANDROID_KEYSTORE_BASE64` | contents of `release.keystore.b64` |
| `ANDROID_KEYSTORE_PASSWORD` | keystore password |
| `ANDROID_KEY_PASSWORD` | key password (often the same) |
| `ANDROID_KEY_ALIAS` | `snake` |

Keep `release.keystore` (and its passwords) somewhere safe — lose it and you
can no longer update apps you already published. Never commit it: `.gitignore`
already blocks `*.keystore` / `*.jks` / `*.p12` / `.env`.

---

## Building locally (optional)

You do not need this to get an APK — CI does it for you. To reproduce the build
locally you need **Linux** (or WSL2) because python-for-android does not run on
native Windows:

```bash
sudo apt-get install -y build-essential ccache git zip unzip \
  autoconf automake libtool libtool-bin autoconf-archive pkg-config \
  zlib1g-dev libncurses-dev libtinfo6 cmake libltdl-dev libffi-dev \
  libssl-dev openjdk-17-jdk python3-pip
python3 -m pip install "buildozer==1.6.0" "cython==3.0.12"
python3 tools/make_branding.py
buildozer -v android release     # -> bin/*-release-unsigned.apk (sign with apksigner)
```

### Toolchain pinning, and the `libffi` recipe

`buildozer.spec` pins python-for-android to the tagged release
**`v2026.05.09`** (`p4a.branch`) so a build does not silently change under you,
and leaves `android.ndk` **unset** so buildozer downloads whatever NDK that p4a
revision recommends (NDK 28c) instead of a hard-coded value that can drift out
of sync. Cython is capped at `3.0.12` because p4a's Kivy recipe declares
`cython>=0.29.1,<=3.0.12`.

`p4a-recipes/libffi/__init__.py` overrides p4a's own libffi recipe. That matters
because p4a's `python3` recipe **hard-depends on libffi** (it provides
`_ctypes`), and upstream's recipe builds from the GitHub *source archive*, which
ships no `configure` — so it must bootstrap autotools, which fails on modern
Ubuntu runners with *“possibly undefined macro: LT_SYS_SYMBOL_USCORE”*. Our
recipe downloads the **release tarball** instead (which already contains a
generated `configure`) and reproduces upstream's `remove-version-info.patch`
through a make-time flag override, so `automake` never has to run and the
bundled `libffi.so` still carries the unversioned soname that `_ctypes.so`
expects.

On Windows you can still run the game itself and both self-tests:

```powershell
py -3.11 -m pip install kivy plyer
py -3.11 snake_core.py           # 17 headless logic checks
py -3.11 main.py                 # play on the desktop (touch controls are mouse-driven)
py -3.11 main.py --self-test-gui # 13 scripted UI/touch checks + screenshots
```

---

## Testing status

* `snake_core.py` — 17/17 logic checks pass.
* `main.py --self-test-gui` — 13/13 checks pass: it opens a real window and
  drives the UI through genuine Kivy touch events (taps on the D-pad, swipe on
  the board, Pause/Resume, tap-to-start, tap-to-restart) and exports
  screenshots for inspection.
* The rendering pipeline was verified pixel-by-pixel from those screenshots
  (playfield, snake with eyes, pulsing food, particles, flash/dim overlays).
* **Not verified on a physical Android device from this environment** (no
  ADB/SDK/emulator available here). The CI build is the first place the APK is
  produced; install it and report anything that looks off.
