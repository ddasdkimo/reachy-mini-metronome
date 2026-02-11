---
title: Reachy Mini Metronome
emoji: 🎵🤖
colorFrom: indigo
colorTo: purple
sdk: static
pinned: false
tags:
  - reachy-mini-app
---

# Reachy Mini Metronome + Practice Timer

A visual and audible metronome for Reachy Mini that uses both antennas as a pendulum (mirror motion) while producing synthesized click sounds, with built-in practice time tracking.

## Features

- BPM control (40-208) with tempo presets
- Time signatures (2/4, 3/4, 4/4, 5/4, 6/8)
- Accented downbeats (higher pitch on beat 1)
- Mirror antenna motion (both swing in opposite directions)
- Practice timer: tracks current session and total accumulated practice time
- Session history with BPM and time signature per session

## Installation

```bash
cd reachy_mini_metronome
python -m venv venv
source venv/bin/activate
pip install -e .
pip install "reachy-mini[mujoco]"  # For simulator support
```

## Running the App

### 1. Start the daemon

**Simulator (macOS):**
```bash
source venv/bin/activate
mjpython -m reachy_mini.daemon.app.main --sim
```

**Real Robot:**
```bash
reachy-mini-daemon
```

### 2. Open the dashboard
Go to `http://localhost:8000` in your browser.

### 3. Start the app
Your app will appear in the **Applications** section. Toggle **On** to start it.

### 4. Open the app UI
Click the gear icon on the running app tile, or go directly to `http://localhost:8042` to control BPM, time signature, practice timer, and start/stop.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/status` | GET | Get current metronome status and practice time |
| `/bpm` | POST | Update BPM (`{"bpm": 120}`) |
| `/time_signature` | POST | Update time signature (`{"beats": 4}`) |
| `/start` | POST | Start metronome and practice timer |
| `/stop` | POST | Stop metronome and record practice session |
| `/practice/reset` | POST | Reset accumulated practice time |
| `/practice/history` | GET | Get all recorded practice sessions |
