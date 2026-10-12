[app]

# (str) Title of your application (shown under the launcher icon)
title = Snake

# (str) Package name (must be a valid java package segment)
package.name = snake

# (str) Package domain (reverse-DNS prefix, used for the java package id)
package.domain = org.samyakdongare

# (str) Source code where the main package is located
source.dir = .

# (list) Source files to include (leave empty to include everything)
# Everything we ship is generated procedurally, so we only need python sources
# plus the procedurally generated launcher artwork.
source.include_exts = py,png

# (list) Directories to exclude from the packaged source
source.exclude_dirs = bin,.buildozer,__pycache__,.git,.github,.vscode,p4a-recipes

# (list) Patterns excluded from the packaged source (dev / test artefacts).
# snake.py is the desktop Tkinter build -- it is kept in the repo for reference
# but is not part of the mobile app.
source.exclude_patterns = shot_*.png,gui_log*.txt,coord*.png,push_to_github.py,snake.py,buildozer.spec,*.md

# (str) Application versioning
version = 1.0.0

# (list) Application requirements
#   python3  - the interpreter provided by python-for-android
#   kivy     - the UI toolkit / renderer (pinned to the version used locally)
#   plyer    - cross-platform API used for the vibrator (haptics)
#   pyjnius  - JNI bridge plyer's Android backends need
requirements = python3,kivy==2.3.1,plyer,pyjnius

# (str) Supported orientation.  The whole UI is designed for landscape.
orientation = landscape

# (bool) Do NOT run immersive/fullscreen: keeping the system bars visible means
# Android insets the window so the control strip can never sit underneath the
# navigation bar or a display cut-out.  (Set to 1 for an edge-to-edge look.)
fullscreen = 0

# (str) Splash image (generated procedurally by tools/make_branding.py)
presplash.filename = %(source.dir)s/presplash.png

# (str) Launcher icon (generated procedurally by tools/make_branding.py)
icon.filename = %(source.dir)s/icon.png

# ---------------------------------------------------------------------------
# Android specific
# ---------------------------------------------------------------------------
android.permissions = VIBRATE

# (int) Target Android API level
android.api = 34

# (int) Minimum Android API level we support
android.minapi = 24

# (int) NDK API level to compile against (a minimum; must be <= android.api).
# 24 is python-for-android's recommended value.
android.ndk_api = 24

# (str) Android NDK version.
# Deliberately NOT pinned here: when this key is absent buildozer asks the
# pinned python-for-android checkout for its RECOMMENDED_NDK_VERSION and
# downloads exactly that, so the NDK can never drift out of sync with the
# toolchain (NDK 28c for the p4a revision pinned below).

# (list) CPU architectures to build for.
# arm64-v8a covers every Android device from roughly 2017 onwards and keeps CI
# to a single (much faster, far less failure-prone) build pass.  Add
# "armeabi-v7a" if pre-2017 32-bit devices must also be supported.
android.archs = arm64-v8a

# (str) python-for-android revision to build with.  Pinning the newest tagged
# p4a release makes CI reproducible instead of tracking a moving `master`
# (that release ships Python 3.14 and the Kivy 2.3.1 recipe we pin above).
p4a.branch = v2026.05.09

# (str) Local recipe overrides.  Currently holds a libffi recipe that builds
# from the release tarball, avoiding the autotools/`LT_SYS_SYMBOL_USCORE`
# failure the upstream recipe hits on modern Ubuntu runners.
p4a.local_recipes = ./p4a-recipes

# Accept the Android SDK licence automatically (CI is non-interactive)
android.accept_sdk_license = True

# Use AndroidX so the generated Gradle project builds with current tooling
android.enable_androidx = True

# Produce a plain APK (not an AAB) so it can be sideloaded directly
android.release_artifact = apk

# (str) Android entry point -- the p4a default (org.kivy.android.PythonActivity)
# is correct for the SDL2 bootstrap, so we leave it unset to avoid pinning a
# value that may change between python-for-android releases.
# android.entrypoint = org.kivy.android.PythonActivity

# ---------------------------------------------------------------------------
[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root
warn_on_root = 1
