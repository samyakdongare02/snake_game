# Nokia Snake — Android APK build guide

## Files in this folder
- `snake_game_android.py` — Android-ready game (swipe + tap, fullscreen scale)
- `buildozer.spec` — buildozer packaging config
- `demo.py` — original PC keyboard version

## You cannot build an APK on Windows alone
Buildozer needs **Linux**. Use one of:

1. **WSL2 + Ubuntu** (recommended on Windows)
2. A real Ubuntu PC/VM
3. Google Colab / cloud Linux (advanced)

---

## Step-by-step (WSL2 Ubuntu)

### 1. Install WSL2 + Ubuntu
In PowerShell:
```powershell
wsl --install -d Ubuntu
```
Reboot, open Ubuntu, create a user.

### 2. Install build tools
```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev
pip3 install --upgrade buildozer cython virtualenv
```

### 3. Copy this project into WSL
Example (from Windows path):
```bash
mkdir -p ~/snake
cp "/mnt/d/vscode/snake game/snake_game_android.py" ~/snake/
cp "/mnt/d/vscode/snake game/buildozer.spec" ~/snake/
cd ~/snake
```

### 4. First build (downloads Android SDK — can take 10–30+ min)
```bash
buildozer android debug
```

### 5. Install on phone
- Enable **Developer options** → **USB debugging** on Android
- Connect phone, accept prompt
```bash
adb install -r bin/nokiasnake-0.1-debug.apk
```
Or copy the `.apk` from `bin/` to your phone and install it (allow unknown sources).

---

## Controls on phone
| Gesture | Action |
|---------|--------|
| **Swipe** | Steer snake |
| **Tap "TAP TO START"** | Start game |
| **Tap "II"** | Pause |
| **Tap RESTART / MENU** | After game over |

---

## Troubleshooting
- **`buildozer: command not found`** → `pip3 install buildozer` or use `python3 -m buildozer`
- **Java errors** → install `openjdk-17-jdk`, set `JAVA_HOME`
- **Black screen** → check `requirements` includes `pygame` and `sdl2`
- **Swipe feels dead** → swipe at least ~24px; try again
- Rebuild clean: `buildozer android debug clean`
