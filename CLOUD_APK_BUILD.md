# Get your APK (no Ubuntu needed)

This folder is set up to build the **Android APK in the cloud** with GitHub Actions.

## Files for the build
- `main.py` — entry point
- `snake_game_android.py` — the game
- `buildozer.spec` — packaging config
- `.github/workflows/build-apk.yml` — auto-build workflow

## Steps (about 10–20 minutes)

1. Create a free account: https://github.com
2. Create a **new public repository** (e.g. `nokia-snake-apk`)
3. Upload these files to the repo root (keep folders):
   - `main.py`
   - `snake_game_android.py`
   - `buildozer.spec`
   - `.github/workflows/build-apk.yml`
4. Open the repo → **Actions** tab → select **Build Android APK**
5. Wait for the green check (first run is long: downloads Android SDK)
6. On the finished run, open **Artifacts** → download **`nokia-snake-apk`**
7. Unzip → you get **`nokiasnake-0.1-debug.apk`**
8. Copy APK to your phone → install (allow unknown sources)

You can also press **Run workflow** on the Actions tab to rebuild anytime.

## Phone install
- Settings → Apps → Special access → **Install unknown apps** → enable for your file manager/Chrome
- Open the APK → **Install**
