# PLC Training

A browser-based trainer for PLC programming, with a 2D and 3D simulator of a Mitsubishi FX3U training kit. Nothing to install.

Open `plc-training-kit-sim.html` in a browser, or use GitHub Pages (`index.html` redirects to the main page).

## Languages (IEC 61131-3)

| Tab | Language | Notes |
|---|---|---|
| LD | Ladder Diagram | GX Works2-style editing: F5 contact, Shift+F5 parallel, F7 coil, F8 instruction; live monitor while running |
| IL | Instruction List | MELSEC IL, Siemens STL and Allen-Bradley rung text; open as Ladder or export to CSV |
| ST | Structured Text | CODESYS style; I/O as `X0` or `%IX0.0` |
| SFC | Sequential Function Chart | Steps and transitions, N/S/R actions, step time in conditions such as `Check.T >= T#2S` |
| FBD | Function Block Diagram | Drag AND, OR, NOT, SR, RS, TON, TOF, TP, CTU and comparators, then wire them |

## Training kit I/O

| Input | Function | Output | Function |
|---|---|---|---|
| X0 | START button, green | Y0 | Green lamp |
| X1 | STOP button, red | Y1 | Yellow lamp |
| X2 | Part sensor at the pick point (left) | Y2 | Red lamp |
| X3 | Metal sensor, green head | Y3 | Kicker cylinder (right) |
| X4 to X7 | Spare | Y4 | Gripper cylinder |
| | | Y5 | Left-right cylinder |
| | | Y6 | Up-down cylinder |
| | | Y7 | Conveyor motor (runs to the right) |

A part waits at the pick point (X2). The gripper moves it to the conveyor, which carries it past the metal sensor (X3). Metal parts are kicked into the bin by Y3; plastic parts run to the end of the conveyor.

The real kit has no cylinder position sensors, so the example programs use timers. The times are estimates and may need tuning on the real machine.

## GX Works2

- **CSV exchange:** in GX Works2, right-click the Ladder window and choose Read from CSV File or Write to CSV File.
- **Real time with GX Simulator2:** run `gx_bridge.py` (needs MX Component).

```
pip install pywin32 websockets
python gx_bridge.py --station 1
```

Then open `plc-training-kit-sim.html` from your computer (not the online page) and press Connect.

## Notes

- The 3D view downloads Three.js from a CDN the first time, so it needs an internet connection.
- Programs are saved in the browser's localStorage on the device you use.
