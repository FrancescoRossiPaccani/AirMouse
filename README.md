# AirMouse

Project for the Mobile and Social Sensing systems course.

Authors: Francesco Rossi Paccani, Lorenzo Bernardini \
Repository: https://github.com/FrancescoRossiPaccani/AirMouse

## Description

AirMouse lets you use a Wear OS smartwatch as a computer mouse and as a laser pointer, over Bluetooth Low Energy (BLE). The project is inspired by the paper *"Magic-hand: Turn a smartwatch into a mouse"*.

The cursor is moved by reading the watch's gyroscope data. Clicks, double clicks and dragging are recognized by analyzing quick wrist movements with a Random Forest model that we trained ourselves.

The repository contains two implementations, developed to compare power consumption and performance:

1. **PC version (`AirMouse_Pc`)**: the smartwatch streams raw gyroscope data to the PC at 20 Hz (20 bytes/packet), which handles filtering, motion computation and gesture classification.
2. **Edge version (`AirMouse_Edge`)**: tracking and model inference run directly on the smartwatch using the gyroscope. Only the final commands (relative movement, clicks) are sent to the PC, and only when an event occurs.

## Repository structure

```text
AirMouse/
├── AirMouse_Pc/                  # Version with logic on the PC
│   ├── BLE-Client/               # Wear OS app for data streaming
│   ├── bridge.py                 # BLE -> UDP bridge
│   └── serverBle/                # Kotlin PC application (tracking, model, mouse control)
├── AirMouse_Edge/                # Version with logic on the watch
│   ├── BLE-Client-Edge/          # Wear OS app with embedded Random Forest
│   ├── bridge_edge.py            # BLE -> UDP bridge for commands
│   ├── serverBle-Edge/           # PC server that executes the received commands
│   └── mis.txt                   # Battery consumption measurements (Edge version)
├── gestureRecognitionUtils/      # Data collection and model training
│   ├── data/                     # Collected data (P0-P9)
│   ├── gestureRecorder.py        # Gesture sample recording
│   ├── train.py                  # Feature extraction, training and evaluation
│   ├── trainedTree/              # Exported model (rf.json) and confusion matrices
│   └── img/                      # Metric plots
├── students_log/                 # Development activity logs
│   ├── RossiPaccani_log.txt
│   └── Bernardini_log.txt
├── battery_test.txt              # Wi-Fi vs BLE consumption (PC version)
├── Magic-hand: Turn a smartwatch into a mouse.pdf   # Reference paper
├── Presentazione Mobile_Paper+Progetto.pdf          # Presentation slides
└── README.md
```

## Requirements

- Wear OS smartwatch (e.g. Samsung Galaxy Watch)
- Linux (X11) or Windows PC with Bluetooth
- Android Studio to install the app on the watch
- JDK 17 or later for the Kotlin server
- Python 3.11 with the `bless` library (`pip install bless`)

## Running the project

### PC version (`AirMouse_Pc`)

1. Start the BLE bridge on the PC. It waits for the smartwatch to connect and forwards packets to UDP port 9000:
   ```bash
   cd AirMouse_Pc
   python bridge.py
   ```
2. In a second terminal, start the Kotlin server:
   ```bash
   cd AirMouse_Pc/serverBle
   ./gradlew run
   ```
3. Open `AirMouse_Pc/BLE-Client` in Android Studio, install the app on the smartwatch and start the session.

### Edge version (`AirMouse_Edge`)

1. Start the bridge:
   ```bash
   cd AirMouse_Edge
   python bridge_edge.py
   ```
2. In a second terminal, start the server that receives the commands:
   ```bash
   cd AirMouse_Edge/serverBle-Edge
   ./gradlew run
   ```
3. Open `AirMouse_Edge/BLE-Client-Edge` in Android Studio, install the app on the watch and press "connect".

## Supported gestures

Recognition uses a time window of gyroscope samples, classified by the Random Forest model (`rf.json`).

| Gesture | Code | Action |
| :--- | :---: | :--- |
| Roll left | RLB | Left click |
| Roll right | RRB | Right click |
| Quick up/down flick | UDB | Double click |
| Sustained movement to the left | MLB | Toggle drag & drop (left click held down) |
| Sustained movement to the right | MRB | Toggle right click hold |

## Watch controls

From the Wear OS app you can:

- switch between Mouse mode and Laser Pointer mode (shows a red circle on screen, useful for presentations);
- adjust cursor sensitivity (DPI) with the `+` and `-` buttons;
- pause and resume tracking without disconnecting;
- get a vibration on every recognized gesture.

## Datasets and measurements

- `gestureRecognitionUtils/data/`: 20 Hz sensor recordings from 10 participants (`P0`-`P9`). Each CSV file contains timestamped gyroscope, accelerometer and magnetometer data, the repetition index and the gesture label (`rest`, `RLB`, `RRB`, `UDB`, `MLB`, `MRB`).
- `battery_test.txt`: 1-hour battery tests on the PC version, Wi-Fi (about 26.7% discharge) vs BLE (about 16.3%), with the screen always on and background services active.
- `AirMouse_Edge/mis.txt`: 1-hour battery tests comparing the Edge version (13.0% discharge) with the PC version streaming only the gyroscope (13.75%).
