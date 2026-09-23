[app]

# (str) Application name
title = Nokia Snake

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

# (list) Application dependencies
requirements = python3,pygame,sdl2,pyjnius

# Orientation
orientation = landscape
fullscreen = 1

# Android API
android.api = 33
android.minapi = 21
android.ndk = 25b

# Bootstrap
p4a.bootstrap = sdl2
android.enable_androidx = True
android.permissions =

# Reduce CI noise / first-build time a bit
android.skip_update = False
log_level = 2

[buildozer]
log_level = 2
warn_on_root = 1
