# CANDU Nuclear Reactor Simulator

# Project Overview
This project is a hardware-integrated CANDU reactor simulator built using Python, PyQt6, Raspberry Pi GPIO, ADC/DAC hardware, and a real-time reactor simulation backend. The system provides physical controls and indicators for interacting with a simulated reactor plant. This repository also houses a software only version of the simulation which can be run on any computer and does not require hardware inputs.

---

# Repository Structure

```text
main/
├── Current Design Files/        # Contains all hardware information
    ├── Datasheets/                  # Contains datasheets for parts used in the original design
    ├── Case Files/                  # Contains .SLDPRT drawings for the case and parts used
    ├── Circuitry Files/             # Contains modular circuit designs for each type of input
    ├── Fission Vision - Simulator Parts list.xlsx # Master list of all parts and costings
├── Hardware Version/            # Scripts for simulation with hardware
    ├── ADS1256.py                   # ADC driver
    ├── DAC8532.py                   # DAC driver
    ├── Hardware_Integrated_GUI.ui   # Qt Designer UI file
    ├── candu_realtime_sim.py        # Reactor simulation backend
    ├── main.py                      # hardware main script
    ├── pinouts.py                   # Raspberry Pi Pin out config
├── Software-Only Version/       # Scripts for simulation with software only
    ├── Software_Only_GUI.ui         # Qt Designer UI file
    ├── candu_realtime_sim.py        # Reactor simulation backend
    ├── main.py                      # software-only main script
└── README.md
```

---

# Hardware Requirements
The full parts list can be found in ```main/Current Design Files/Fission Vision - Simulator Parts List.xlsx ```

## Core Hardware

* Raspberry Pi 4 or 5
* MicroSD Card
* Power Supply
* Display/Monitor
* Keyboard/Mouse

## I/O Hardware

* ADS1256 ADC Module
* DAC8532 DAC Module
* Potentiometers / Rotary Knobs
* Toggle Switches
* Push Buttons
* LEDs / Indicator Lights
* Siren / Buzzer
* Wiring / Breadboard / PCB

---

# Software Requirements
## Operating System

* Raspberry Pi OS: Raspberry Pi OS (64-bit)

## Python Version

* Python 3.X Recommended

## Required Python Libraries

```bash
pip install pyqt6
pip install pyqtgraph
pip install numpy
pip install RPi.GPIO
pip install time
pip install threading
```
---

# Wiring / Pinout Documentation

## GPIO Pin Assignments

Include a table like:

| Function      | GPIO Pin | Physical Pin | Direction |
| ------------- | -------- | ------------ | --------- |
| SDS1 Button   | GPIO17   | Pin 11       | Input     |
| SDS2 Button   | GPIO27   | Pin 13       | Input     |
| Safety Toggle | GPIO22   | Pin 15       | Input     |
| Siren Output  | GPIO23   | Pin 16       | Output    |
| Pause Light   | GPIO24   | Pin 18       | Output    |

---

## ADC Channel Assignments

| Control             | ADC Channel |
| ------------------- | ----------- |
| Liquid Zone Control | CH0         |
| Adjuster Rods       | CH1         |
| MCA                 | CH2         |
| Refuel Rate         | CH3         |
| Simulation Speed    | CH4         |

---

## DAC Channel Assignments

| Output            | DAC Channel |
| ----------------- | ----------- |
| Temperature Gauge | DAC0        |
| Power Gauge       | DAC1        |

---

# How to Use the Simulator

## Startup Procedure

1. Power on Raspberry Pi
2. Launch software
3. Wait for initialization
4. Reset to steady state

## Software controls Overview

### `speed`
Sets the reactor simulation speed relative to real time.

- **Units:** Reactor seconds per wall-clock second
- **Example:**
  ```text
  speed = 60
  ```
  This means **1 real second = 1 reactor minute**.

---

### `goal`
Sets the operator's target power fraction.

This value is intended primarily for the simulator's game mode, where the operator attempts to match the requested power level.

---

### `lzc`
Sets the average Liquid Zone Controller (LZC) fill level.

- **Units:** Percent (%)
- **Neutral value:** `50%`
- **Behavior:**
  - Lower fill → Positive reactivity → Reactor power tends to increase.
  - Higher fill → Negative reactivity → Reactor power tends to decrease.

---

### `adj`
Sets the adjuster rod withdrawal fraction.

- **Range:** `0–1`
- **Behavior:**
  - Higher values correspond to greater adjuster rod withdrawal.
  - Increased withdrawal adds **positive reactivity**.

---

### `mca`
Sets the Mechanical Control Absorber (MCA) insertion fraction.

- **Range:** `0–1`
- **Behavior:**
  - Higher insertion results in **more negative reactivity**.

---

### `refuel`
Sets the continuous online refuelling command.

- **Range:** `0–2`
- Implemented as a continuous control rather than discrete fuelling events.
- Designed to map naturally to GUI sliders or analogue hardware controls.

---

### `safety`
Enables or disables the automatic reactor protection system.

When enabled, automatic **stepback** and **shutdown** logic will operate if required.

---

### `trip sds1`
Manually initiates a shutdown using **Shutdown System 1 (SDS1)**.

---

### `trip sds2`
Manually initiates a shutdown using **Shutdown System 2 (SDS2)**.

---

### `reset sds`
Clears the shutdown latches.

This command is only accepted when reactor power is **below 1% full power**.

---

### `reset steady`
Resets the simulator to the nominal startup state.

This performs a complete re initialization of the reactor state.


# Known simulation simplifications
* one delayed-neutron group instead of six
* lumped thermal states instead of detailed HTS / SG thermodynamics
* normalized poison states instead of full iodine/xenon number densities
* simplified shutdown logic compared with plant-grade 2-out-of-3 voting

---

# Future Improvements

List planned enhancements:

* Add hardware watchdog
* Improve meltdown reset UI
* Add data logging/export
* Add calibration GUI

---
