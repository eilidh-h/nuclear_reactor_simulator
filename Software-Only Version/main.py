"""
CANDU Reactor Real-Time Simulation GUI
--------------------------------------
PyQt6-based graphical interface for interacting with the CANDU reactor
real-time simulation backend. Displays live reactor data, accepts user
control inputs, and manages simulation events such as pause, reset, and
meltdown handling.

Author: Adrienne Kolkman
Last Edited: March 23, 2026
"""
# ============================================================
# Imports
# ============================================================

from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QMainWindow
)
from PyQt6.QtCore import QTimer
from PyQt6.uic import loadUi

import numpy as np
import pyqtgraph as pg
from candu_realtime_sim import CanduRealtimeSim, PlantParams
import time

# ============================================================
# Main GUI Window Class
# ============================================================
class MainGUIWindow(QMainWindow):
    """
       Main application window for the CANDU reactor simulator GUI.

       Handles:
           - User input controls
           - Real-time graph plotting
           - Display updates
           - Simulation pause/reset functionality
           - Reactor event handling
       """

    TEMP_WARNING = 720
    TEMP_CRITICAL = 800
    DEFAULT_LZC = 50
    DEFAULT_ADJ = 0
    DEFAULT_TIMESCALE = 1
    DEFAULT_MCA = 0
    DEFAULT_SAFETY = True
    DEFAULT_REFUEL_RATE = 0.97

    def __init__(self):
        """
        Initialize the GUI window, simulation backend, and all UI elements.
        """
        super().__init__()
        loadUi("Software_Only_GUI.ui", self)

        #self.window = loadUi("Sim_Integration_GUI.ui")
        self.showMaximized()
        self.sim = CanduRealtimeSim(PlantParams())
        self.sim.run()

        self.plot_window = 20
        self.display_refresh_rate = 33 #ms

        # Setup all UI components
        self.setup_plots()
        self.setup_inputs()
        self.setup_outputs()
        self.setup_timers()

    def setup_plots(self):
        """
        Configure all real-time plot widgets and initialize plot lines.
        """
        # Neutron Power Graph
        self.neutronPowerGraph.setXRange(0, self.plot_window)
        self.neutronPowerGraph.setLabel('bottom', 'Time (seconds)')
        self.neutronPowerGraph.setLabel('left', 'Power (%FP)')
        self.neutronPowerGraph.setTitle('Neutron Power')
        self.neutronLine = self.neutronPowerGraph.plot()

        # Electric Power Graph
        self.electricPowerGraph.setLabel('bottom', 'Time (seconds)')
        self.electricPowerGraph.setLabel('left', 'Power (MW)')
        self.electricPowerGraph.setTitle('Electric Power (Scaled)')
        self.electricLine = self.electricPowerGraph.plot()

        # Temperature Graph Setup
        self.temperatureGraph.setXRange(0, self.plot_window)
        self.temperatureGraph.setLabel('bottom', 'Time (seconds)')
        self.temperatureGraph.setLabel('left', 'Temp (Degrees Celsius)')
        self.temperatureGraph.setTitle('Temperatures')
        self.lineTf = self.temperatureGraph.plot(name="Tf")

        # Pressure Graph Setup
        self.pressureGraph.setXRange(0, self.plot_window)
        self.pressureGraph.setLabel('bottom', 'Time (seconds)')
        self.pressureGraph.setLabel('left', 'Pressure (MPa)')
        self.pressureGraph.setTitle('Turbine/SC Pressure Proxy')
        self.pressureLine = self.pressureGraph.plot()

    def setup_inputs(self):
        """
        Initialize all interactive user input widgets and connect signals.
        """
        # Liquid Zone Control
        self.lzcSlider.setMinimum(0)
        self.lzcSlider.setMaximum(100)
        self.lzcSlider.setValue(int(self.sim.ctrl.lzc_fill_pct))
        # SCRAM Buttons
        self.sds1Button.clicked.connect(
            lambda: setattr(self.sim.ctrl, "trip_sds1", True)
        )
        self.sds2Button.clicked.connect(
            lambda: setattr(self.sim.ctrl, "trip_sds2", True)
        )
        # Reset Steady State Button
        self.steadyStateReset.clicked.connect(self.reset_steady)
        # Pause Button
        self.pauseButton.clicked.connect(self.pause_sim)
        # Adjuster Rod Slider Setup
        self.adjSlider.setValue(int(self.sim.ctrl.adj_out_frac))
        # Simulation Speed Slider
        self.timescaleSlider.setValue(int(self.sim.ctrl.time_scale))
        # MCA Slider
        self.mcaSlider.setValue(int(self.sim.ctrl.mca_in_frac * 10))
        # Safety Enable Checkbox
        self.safetyEnabledBox.setChecked(self.sim.ctrl.safety_enabled)
        # Refueling Input Setup
        self.refuelSlider.setValue(int(self.sim.ctrl.refuel_rate_cmd * 10))

    def setup_outputs(self):
        """
        Initialize output displays, LCDs, labels, and console log.
        """
        # Temperature & Power LCD
        self.temperatureLCD.display(self.sim.x.Tf)
        self.powerOutputLCD.display(self.sim.x.P)
        # Liquid Zone Control Value
        self.lzcValue.setText(f"{self.sim.ctrl.lzc_fill_pct}%")
        # Console log
        logText = "Window Initialized"
        self.consoleLog.setText(logText)
        self.consoleLog.ensureCursorVisible()

    def setup_timers(self):
        """
        Configure update timers for display refresh and elapsed time clock.
        """
        self.elapsed_minutes = 0
        self.displayTimer = QTimer()
        self.displayTimer.timeout.connect(self.update_display)
        self.displayTimer.start(self.display_refresh_rate)

        self.LCDTimer = QTimer()
        self.LCDTimer.timeout.connect(self.update_LCD)
        self.LCDTimer.start(60000)
    def update_plots(self):
        """
        Refresh all plot data using the latest simulation history.

        Dynamically adjusts:
            - X-axis units (seconds/minutes)
            - Plot window scaling
            - Axis ranges
        """

        if not self.sim._running:
            return

        if self.sim.ctrl.paused:
            return
        if self.sim.x.exploded:
            return

        t = np.asarray(self.sim.t_wall_hist)*self.sim.ctrl.time_scale
        P = np.asarray(self.sim.P_hist)
        Tf = np.asarray(self.sim.Tf_hist)
        Pe = np.asarray(self.sim.Pe_hist)
        pp = np.asarray(self.sim.p_hist)

        scaled_plot_window = self.plot_window*self.sim.ctrl.time_scale
        # Adjust X-Axis label based on time units
        if self.sim.ctrl.time_scale < 60:
            self.neutronPowerGraph.setLabel('bottom', 'time (seconds)')
            self.electricPowerGraph.setLabel('bottom', 'time (seconds)')
            self.pressureGraph.setLabel('bottom', 'time (seconds)')
            self.temperatureGraph.setLabel('bottom', 'time (seconds)')
        else:
            t = t/60 # Convert the plot axis to minutes
            scaled_plot_window = scaled_plot_window/60
            self.neutronPowerGraph.setLabel('bottom', 'time (minutes)')
            self.electricPowerGraph.setLabel('bottom', 'time (minutes)')
            self.pressureGraph.setLabel('bottom', 'time (minutes)')
            self.temperatureGraph.setLabel('bottom', 'time (minutes)')

        self.neutronLine.setData(t, 100.0 * P)
        self.lineTf.setData(t, Tf)
        self.electricLine.setData(t, Pe)
        self.pressureLine.setData(t, pp)

        # Handle x range of plot
        if t[-1] > scaled_plot_window:
            self.neutronPowerGraph.setXRange(t[-1] - scaled_plot_window, t[-1])
            self.electricPowerGraph.setXRange(t[-1] - scaled_plot_window, t[-1])
            self.pressureGraph.setXRange(t[-1] - scaled_plot_window, t[-1])
            self.temperatureGraph.setXRange(t[-1] - scaled_plot_window, t[-1])
        else:
            self.neutronPowerGraph.setXRange(0, scaled_plot_window)
            self.electricPowerGraph.setXRange(0, scaled_plot_window)
            self.pressureGraph.setXRange(0, scaled_plot_window)
            self.temperatureGraph.setXRange(0, scaled_plot_window)

        # Handle y range of plot
        self.neutronPowerGraph.setYRange(0, max(100.0 * P))
        if max(Pe) < 10 ** -6:
            self.electricPowerGraph.setYRange(0, 10 ** -6)
        else:
            self.electricPowerGraph.setYRange(0, max(Pe))
        self.pressureGraph.setYRange(0, max(pp))
        self.temperatureGraph.setYRange(0, max(Tf))


    def sample_inputs(self):
        """
        Read current GUI control values and apply them to simulation inputs.
        """
        # Liquid zone control
        self.sim.ctrl.lzc_fill_pct = self.lzcSlider.value()
        # Adjuster rods
        self.sim.ctrl.adj_out_frac = self.adjSlider.value() * 0.2
        # Timescale/speed
        if self.timescaleSlider.value() == 0:
            self.sim.ctrl.time_scale = 1
        else:
            self.sim.ctrl.time_scale = self.timescaleSlider.value()*60

        # Safety
        self.sim.ctrl.safety_enabled = self.safetyEnabledBox.isChecked()
        # mca Slider
        self.sim.ctrl.mca_in_frac = self.mcaSlider.value() / 10

        # refuel rate slider
        self.sim.ctrl.refuel_rate_cmd = self.refuelSlider.value() / 10

    def update_timescale_LCD(self):
        """
        Update timescale display labels and conversion LCD based on
        current simulation speed.
        """
        self.timescaleValue.setText(f"{self.sim.ctrl.time_scale}")
        if self.sim.ctrl.time_scale < 60:
            # Seconds case
            self.timescaleConversionLCD.display(self.sim.ctrl.time_scale)
            self.timescaleConversionLabel.setText("second in simulation")
        elif self.sim.ctrl.time_scale == 60:
            self.timescaleConversionLCD.display(self.sim.ctrl.time_scale / 60)
            self.timescaleConversionLabel.setText("minute in simulation")
        else:
            self.timescaleConversionLCD.display(self.sim.ctrl.time_scale / 60)
            self.timescaleConversionLabel.setText("minutes in simulation")

    def update_display(self):
        """
        Main periodic GUI refresh loop.

        Performs:
            - Input sampling
            - Plot updates
            - LCD/label refresh
            - Event log updates
            - Meltdown detection
        """
        self.sample_inputs()

        # update the data on the plots
        self.update_plots()

        self.temperatureLCD.display(f"{self.sim.x.Tf:.0f}")
        if self.sim.x.Tf > self.TEMP_CRITICAL:
            self.temperatureLCD.setStyleSheet("QLCDNumber { color: red; }")
        elif self.sim.x.Tf > self.TEMP_WARNING:
            self.temperatureLCD.setStyleSheet("QLCDNumber { color: orange; }")
        else:
            self.temperatureLCD.setStyleSheet("QLCDNumber { color: #00ff00; }")

        Power = self.sim.p.eta_electric * self.sim.x.P * self.sim.p.Q_th_full_MW
        self.powerOutputLCD.display(f"{Power:.0f}")

        # Liquid zone control
        self.lzcValue.setText(f"{self.sim.ctrl.lzc_fill_pct}%")
        self.sds1Button.setEnabled(not self.sim.x.sds1_active)
        self.changeIndicatorLight(self.SDS1Light, self.sim.x.sds1_active)
        self.sds2Button.setEnabled(not self.sim.x.sds2_active)
        self.changeIndicatorLight(self.SDS2Light, self.sim.x.sds2_active)
        # Adjuster rods
        self.adjValue.setText(f"{self.adjSlider.value() * 0.2:.1f}")
        # Timescale/speed
        self.update_timescale_LCD()

        # mca Slider
        self.mcaValue.setText(f"{self.mcaSlider.value() * 0.1:.1f}")
        # Refueling value
        self.refuelValue.setText(f"{self.refuelSlider.value() * 0.1:.1f}")

        # Update event status log
        for log in self.sim.ctrl.event_status:
            self.consoleLog.append(log)
            self.sim.ctrl.event_status.remove(log)

        # Handle reactor meltdown case
        if self.sim.x.exploded:
            self.reactorMeltdown()

    def update_LCD(self):
        """
        Increment and display elapsed simulation runtime in minutes.
        """
        self.elapsed_minutes += 1
        self.LCDClock.display(self.elapsed_minutes)

    def reset_steady(self):
        """
        Reset simulation to steady-state operating conditions and
        restore all GUI controls to default values.
        """
        self.consoleLog.append("~~~~ Resetting System to Steady State ~~~~")
        # set simulation parameter
        self.sim.ctrl.request_reset_steady = True

        # reset all elements to default
        self.lzcSlider.setValue(self.DEFAULT_LZC)
        self.adjSlider.setValue(self.DEFAULT_ADJ)
        self.timescaleSlider.setValue(self.DEFAULT_TIMESCALE)
        self.mcaSlider.setValue(self.DEFAULT_MCA)
        self.safetyEnabledBox.setChecked(self.DEFAULT_SAFETY)
        self.refuelSlider.setValue(int(self.DEFAULT_REFUEL_RATE * 10))

    def pause_sim(self):
        """
        Toggle simulation pause/resume state.

        Also tracks paused wall-clock time for synchronization.
        """
        if not self.sim.ctrl.paused:
            self.sim.ctrl.paused = True
            self.sim._pause_start = time.time()
            self.pauseButton.setText("RESUME")
            self.consoleLog.append("~~~~ Pausing Simulation ~~~~")
        else:
            self.sim.ctrl.paused = False
            self.sim._paused_wall_time += time.time() - self.sim._pause_start
            self.sim._pause_start = None
            self.pauseButton.setText("PAUSE")
            self.consoleLog.append("~~~~ Resuming Simulation ~~~~")

    def changeIndicatorLight(self, onOffLight, is_on: bool):
        """
        Change indicator light widget color based on boolean state.

        Parameters:
            onOffLight : QWidget
                GUI widget representing the indicator light.
            is_on : bool
                True sets light green, False sets light red.
        """
        if is_on:
            color = "green"
        else:
            color = "red"
        onOffLight.setStyleSheet(
            f"""
                 background-color: {color};
                 border-radius: 20px;
                 border: 1px solid black;
                 """
        )

    def reactorMeltdown(self):
        """
        Display reactor meltdown warning dialog and prompt user
        to reset simulation.
        """
        msg = QMessageBox()
        msg.setWindowTitle("Reactor Meltdown")
        msg.setText(f"Reset reactor to steady state to play again")

        reset = msg.addButton("Reset", QMessageBox.ButtonRole.AcceptRole)
        msg.exec()

        if msg.clickedButton() == reset:
            self.reset_steady()


    def closeEvent(self, event):
        """
        Safely stop simulation thread when application window closes.

        Parameters:
            event : QCloseEvent
                Qt close event object.
        """
        self.sim._running = False
        event.accept()


# ============================================================
# Application Entry Point
# ============================================================
if __name__ == "__main__":
    app = QApplication([])

    globals()["PlotWidget"] = pg.PlotWidget

    window = MainGUIWindow()
    window.show()

    app.exec()

