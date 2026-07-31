# CANDU Nuclear Reactor Simulator

# Project Overview
This project is a hardware-integrated CANDU reactor simulator built using Python, PyQt6, Raspberry Pi GPIO, ADC/DAC hardware, and a real-time reactor simulation backend as a part of the University of Saskatchewan's 2025/26 engineering capstone. The system provides physical controls and indicators for interacting with a simulated reactor plant. This repository also houses a software only version of the simulation which can be run on any computer and does not require hardware inputs.

---

# Repository Structure

Describe the purpose of each major file/folder.

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

List all physical components required.

## Core Hardware

* Raspberry Pi (Specify model)
* MicroSD Card (Minimum recommended size)
* Power Supply
* Display/Monitor
* Keyboard/Mouse (if applicable)

## I/O Hardware

* ADS1256 ADC Module
* DAC8532 DAC Module
* Potentiometers / Rotary Knobs
* Toggle Switches
* Push Buttons
* LEDs / Indicator Lights
* Siren / Buzzer
* Wiring / Breadboard / PCB

## Optional Hardware

* Enclosure / Panel
* Cooling fan
* External speakers

---

# Software Requirements

List all software dependencies.

## Operating System

* Raspberry Pi OS Version:

  * Example: Raspberry Pi OS Bookworm 64-bit

## Python Version

* Python 3.X Recommended

## Required Python Libraries

```bash
pip install pyqt6
pip install pyqtgraph
pip install numpy
pip install RPi.GPIO
```

## Additional Packages

List any apt/system packages required:

```bash
sudo apt update
sudo apt install python3-pyqt6
sudo apt install qt6-tools-dev-tools
```

---

# Raspberry Pi Setup Instructions

## 1. Flash Raspberry Pi OS

Describe:

* Download Raspberry Pi Imager
* Select OS
* Flash SD Card
* Enable SSH/Wi-Fi if desired

## 2. Initial Configuration

```bash
sudo raspi-config
```

Recommended settings:

* Enable SPI
* Enable I2C (if used)
* Set hostname
* Configure locale/timezone

## 3. Enable Required Interfaces

Example:

```bash
sudo raspi-config
# Interface Options → SPI → Enable
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

# Installation Instructions

## Clone Repository

```bash
git clone <repository_url>
cd <repository_name>
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

---

# Running the Program

## Launch Application

```bash
python3 main_gui.py
```

## Auto-Start on Boot (Optional)

Explain if applicable:

* systemd service setup
* desktop autostart setup

---

# Calibration / Configuration

## ADC Calibration

Explain:

* Expected voltage ranges
* Potentiometer calibration procedure
* Noise thresholds

## DAC Calibration

Explain:

* Gauge/light scaling
* Output voltage verification

---

# How to Use the Simulator

## Startup Procedure

1. Power on Raspberry Pi
2. Launch software
3. Wait for initialization
4. Reset to steady state

## Controls Overview

Describe each control:

### Liquid Zone Control

* Function:
* Range:
* Effect on simulation:

### Adjuster Rods

* Function:
* Range:
* Effect on simulation:

### SDS1 / SDS2

* Function:
* Trigger behavior:

### Safety Toggle

* Function:
* Effect:

---

# Operating Logic / Safety Features

Document:

* Meltdown conditions
* Siren logic
* Automatic reset behavior
* Pause/Resume logic
* Safety interlocks

---

# Troubleshooting

## GUI Will Not Launch

Possible causes:

* Missing PyQt6
* Incorrect Python version
* Missing UI file

## Hardware Not Responding

Possible causes:

* SPI disabled
* Wiring incorrect
* GPIO permissions issue

## ADC Reads Incorrect Values

Possible causes:

* Loose wiring
* Incorrect reference voltage
* Calibration required

---

# Known Issues / Limitations

Document any limitations:

* GUI blocks briefly during reset
* No hardware debounce beyond software
* ADC noise under certain conditions

---

# Future Improvements

List planned enhancements:

* Add hardware watchdog
* Improve meltdown reset UI
* Add data logging/export
* Add calibration GUI

---

# Contributors

List team members and roles.

| Name        | Role                            |
| ----------- | ------------------------------- |
| Your Name   | Software / Hardware Integration |
| Team Member | Simulation Backend              |

---

# License

Specify project license if applicable.

Example:

> This project is licensed under the MIT License.

---

# Appendix

## Electrical Schematics

Link or include:

* Wiring diagrams
* PCB schematics
* Breadboard layouts

## References

Include:

* Hardware datasheets
* Simulation references
* External libraries used

---
