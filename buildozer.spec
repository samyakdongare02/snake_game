[app]

# (str) Application name
title = Nokia Snake

# (str) Application version
version = 0.1

# (str) Package name
package.name = nokiasnake

# (str) Package domain
package.domain = org.snakegame

# (str) Source directory
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,spec,txt

# (str) Script buildozer runs on device (must exist)
source.main = main.py

# (list) Extra source files
source.include_patterns = main.py,snake_game_android.py,buildozer.spec

# Custom recipes (fixed libffi - no autogen)
p4a.local_recipes = ./p4a-recipes

# (list) Application dependencies
requirements = python3,pygame,sdl2,pyjnius

# Orientation
orientation = landscape
fullscreen = 1

# Android API / min SDK (21 breaks libffi on modern runners)
android.api = 34
android.minapi = 24

# Single modern arch - avoids armeabi-v7a/libffi autotools failure
android.archs = arm64-v8a

# Known-good NDK for p4a recipes
android.ndk = 25b

# Bootstrap
p4a.bootstrap = sdl2
android.enable_androidx = True
android.permissions =

android.accept_sdk_license = True
android.skip_update = False
log_level = 2

[buildozer]
log_level = 2
warn_on_root = 1
