"""
Hardware-Integrated CANDU Reactor Simulator GUI
-----------------------------------------------

PyQt6 GUI for operating a real-time CANDU reactor simulation integrated
with physical control hardware via Raspberry Pi GPIO, ADC, and DAC modules.

Features:
    - Real-time reactor simulation visualization
    - Hardware potentiometer/switch input sampling
    - DAC analog outputs for physical gauges/lights
    - GPIO event-driven button handling
    - Reactor safety system simulation and siren control

Author: Adrienne Kolkman
Last Edited: March 23, 2026
"""

from PyQt6.QtWidgets import (
    QApplication, QMainWindow
)
from PyQt6.QtCore import QTimer
from PyQt6.uic import loadUi

import numpy as np
import pyqtgraph as pg
from candu_realtime_sim import CanduRealtimeSim, PlantParams
import time
import ADS1256
import DAC8532
import RPi.GPIO as GPIO
import pinouts

class MainGUIWindow(QMainWindow):
    """
    Main GUI window for the hardware-integrated reactor simulator.

    Manages:
        - Real-time simulation backend
        - Hardware I/O interface
        - Plot visualization
        - User interface updates
        - Hardware event callbacks
    """
    def __init__(self):
        """
        Initialize GUI window, simulation backend, hardware interface,
        plots, timers, and hardware event handlers.
        """
        super().__init__()
        loadUi("Hardware_Integrated_GUI.ui", self)

        self.showMaximized()
        self.sim = CanduRealtimeSim(PlantParams())


        self.plot_window = 20
        self.display_refresh_rate = 33 #ms
        self.max_power = 982 # MW
        self.max_temperature = 1200

        # Setup all UI components
        self.setup_plots()
        self.setup_inputs()
        self.setup_outputs()

        # Setup Hardware
        self.HW = SimHardware()
        self.HW.GPIO_pin_init()
        self.setup_Hardware_Events()

        self.sim.run()
        self.setup_timers()
        self.reset_steady()




    def setup_plots(self):
        """
        Configure all real-time graph widgets and initialize plot traces.
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
        Connect GUI button inputs to simulation control callbacks.
        """
        # Reset Steady State Button
        self.steadyStateReset.clicked.connect(self.reset_steady)
        # Pause Button
        self.pauseButton.clicked.connect(self.pause_sim)
        self.resumeButton.clicked.connect(self.resume_sim)

    def setup_outputs(self):
        """
        Initialize LCD displays, labels, and console log outputs.
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
        Configure periodic timers for display refresh and elapsed time clock.
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
        Update all real-time simulation plots using current simulation history.

        Automatically rescales:
            - Time axis units
            - X-axis scrolling window
            - Y-axis ranges
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
        self.electricPowerGraph.setYRange(0, max(Pe))
        self.pressureGraph.setYRange(0, max(pp))
        self.temperatureGraph.setYRange(0, max(Tf))


    def sample_inputs(self):
        """
        Sample all physical hardware inputs from ADC/GPIO and map them
        to simulation control parameters.

        Inputs include:
            - Liquid zone control
            - Adjuster rods
            - Simulation speed
            - Safety toggle
            - Mechanical control absorbers
            - Refuel rate
        """
        ADC_Values = self.HW.ADC.ADS1256_GetAll()

        # Liquid zone control
        Voltage = ADC_Values[pinouts.LZC_CH] * self.HW.ADC_REF_VOLTAGE / 0x7fffff
        Voltage = self.moving_average(Voltage, self.lzc_buffer)
        liquidZoneControl = Voltage/self.HW.MAX_ADC_VOLTAGE * 100
        self.sim.ctrl.lzc_fill_pct = liquidZoneControl
        # Adjuster rods
        Voltage = ADC_Values[pinouts.ADJ_RODS_CH] * self.HW.ADC_REF_VOLTAGE / 0x7fffff
        Voltage = self.moving_average(Voltage, self.adj_buffer)
        adjusterRods = (self.HW.MAX_ADC_VOLTAGE - Voltage)/ self.HW.MAX_ADC_VOLTAGE
        self.sim.ctrl.adj_out_frac = adjusterRods
        
        # Timescale/speed
        Voltage = self.HW.ADC.ADS1256_GetChannelValue(pinouts.SIM_SPEED_CH) * self.HW.ADC_REF_VOLTAGE / 0x7fffff
        
        noise_threshold = 0.2 # V
        if Voltage < noise_threshold:
            Voltage = Voltage
        elif Voltage > self.HW.MAX_ADC_VOLTAGE - noise_threshold:
            self.sim.ctrl.time_scale = 600
        elif Voltage > 5/6 * self.HW.MAX_ADC_VOLTAGE - noise_threshold:
            self.sim.ctrl.time_scale = 480
        elif Voltage > 4/6 * self.HW.MAX_ADC_VOLTAGE - noise_threshold:
            self.sim.ctrl.time_scale = 360
        elif Voltage > 3/6 * self.HW.MAX_ADC_VOLTAGE- noise_threshold:
            self.sim.ctrl.time_scale = 240
        elif Voltage > 2/6 * self.HW.MAX_ADC_VOLTAGE - noise_threshold:
            self.sim.ctrl.time_scale = 120
        else:
            self.sim.ctrl.time_scale = 60


        # Safety
        safety_enabled = GPIO.input(pinouts.SAFETY_TOGGLE_INPUT)
        self.sim.ctrl.safety_enabled = safety_enabled
        
        # mca Slider
        Voltage = ADC_Values[pinouts.MCA_CH] * self.HW.ADC_REF_VOLTAGE / 0x7fffff
        Voltage = self.moving_average(Voltage, self.mca_buffer)
        mechanicalControlAbsorbers = Voltage / self.HW.MAX_ADC_VOLTAGE
        self.sim.ctrl.mca_in_frac = mechanicalControlAbsorbers
        
        # refuel rate slider
        Voltage = ADC_Values[pinouts.REFUEL_CH] * self.HW.ADC_REF_VOLTAGE / 0x7fffff
        Voltage = self.moving_average(Voltage, self.refuel_buffer)
        refuelRate = (self.HW.MAX_ADC_VOLTAGE - Voltage)/ self.HW.MAX_ADC_VOLTAGE * 2
        self.sim.ctrl.refuel_rate_cmd = refuelRate


    def update_timescale_LCD(self):
        """
        Update simulation timescale display and unit conversion labels.
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
        Main GUI refresh loop.

        Performs:
            - Hardware input sampling
            - Plot updates
            - LCD refresh
            - DAC output updates
            - GPIO status light updates
            - Meltdown detection/handling
        """
        self.sample_inputs()
        # testing
        print("Siren enable pin:", GPIO.input(pinouts.SIREN_ENABLED))
        # update the data on the plots
        self.update_plots()

        # Handle reactor meltdown case
        if self.sim.x.exploded:
            # self.consoleLog.append("Reset Simulator to Steady State to Play Again")
            if GPIO.input(pinouts.SIREN_ENABLED):
                GPIO.output(pinouts.SIREN_OUTPUT, GPIO.HIGH)
            else:
                GPIO.output(pinouts.SIREN_OUTPUT, GPIO.LOW)
            self.reactorMeltdown()
        else:
            GPIO.output(pinouts.SIREN_OUTPUT, GPIO.LOW)

        self.temperatureLCD.display(f"{self.sim.x.Tf:.0f}")
        if self.sim.x.Tf > 800:
            self.temperatureLCD.setStyleSheet("QLCDNumber { color: red; }")
        elif self.sim.x.Tf > 720:
            self.temperatureLCD.setStyleSheet("QLCDNumber { color: orange; }")
        else:
            self.temperatureLCD.setStyleSheet("QLCDNumber { color: #00ff00; }")

        # Drive the temperature lights output
        Voltage = self.sim.x.Tf * self.HW.MAX_ADC_VOLTAGE/self.max_temperature
        self.HW.DAC.DAC8532_Out_Voltage(pinouts.TEMP_OUTPUT, Voltage)

        Power = self.sim.p.eta_electric * self.sim.x.P * self.sim.p.Q_th_full_MW
        self.powerOutputLCD.display(f"{Power:.0f}")

        # Update power output lights
        Voltage = Power * self.HW.MAX_ADC_VOLTAGE/self.max_power
        self.HW.DAC.DAC8532_Out_Voltage(pinouts.POWER_OUTPUT, Voltage)

        # Liquid zone control
        self.lzcValue.setText(f"{self.sim.ctrl.lzc_fill_pct:.0f}%")
        
        # Adjuster rods
        self.adjValue.setText(f"{self.sim.ctrl.adj_out_frac:.1f}")
        # Timescale/speed
        self.update_timescale_LCD()

        # mca Slider
        self.mcaValue.setText(f"{self.sim.ctrl.mca_in_frac:.1f}")
        # Refueling value
        self.refuelValue.setText(f"{self.sim.ctrl.refuel_rate_cmd:.1f}")

        # Update event status log
        for log in self.sim.ctrl.event_status:
            self.consoleLog.append(log)
            self.sim.ctrl.event_status.remove(log)

        # Update indicator lights
        if self.sim.ctrl.safety_enabled:
            GPIO.output(pinouts.SAFETY_ON_OUTPUT, GPIO.HIGH)
        else:
            GPIO.output(pinouts.SAFETY_ON_OUTPUT, GPIO.LOW)

        GPIO.output(pinouts.SIM_PAUSE_LIGHT_OUTPUT, self.sim.ctrl.paused)
        GPIO.output(pinouts.SIM_ON_LIGHT_OUTPUT, not self.sim.ctrl.paused)

        GPIO.output(pinouts.SDS1_STATUS, self.sim.x.sds1_active)
        GPIO.output(pinouts.SDS2_STATUS, self.sim.x.sds2_active)



    def update_LCD(self):
        """
        Increment and display elapsed simulation runtime in minutes.
        """
        self.elapsed_minutes += 1
        self.LCDClock.display(self.elapsed_minutes)

    def reset_steady(self, channel=None):
        """
        Reset simulation to steady-state conditions.

        Also:
            - Clears siren output
            - Pauses simulation after reset
            - Initializes ADC moving-average buffers

        Parameters:
            channel : int, optional
                GPIO callback channel number when triggered by hardware.
        """
        self.consoleLog.append("Resetting System to Steady State")

        # set simulation parameter
        self.sim.ctrl.request_reset_steady = True

        GPIO.output(pinouts.SIREN_OUTPUT, GPIO.LOW)
        # give sim time to reset to steadt
        time.sleep(50*0.001)
        self.sim.ctrl.paused = True
        self.sim._pause_start = time.time()
        GPIO.output(pinouts.SIM_PAUSE_LIGHT_OUTPUT, GPIO.HIGH)

        # Pre-fill buffers with current ADC readings so first sample is stable
        ADC_Values = self.HW.ADC.ADS1256_GetAll()
        init_lzc = ADC_Values[pinouts.LZC_CH] * self.HW.ADC_REF_VOLTAGE / 0x7fffff
        init_adj = ADC_Values[pinouts.ADJ_RODS_CH] * self.HW.ADC_REF_VOLTAGE / 0x7fffff
        init_mca = ADC_Values[pinouts.MCA_CH] * self.HW.ADC_REF_VOLTAGE / 0x7fffff
        init_refuel = ADC_Values[pinouts.REFUEL_CH] * self.HW.ADC_REF_VOLTAGE / 0x7fffff
        self.lzc_buffer = [init_lzc] * 5
        self.adj_buffer = [init_adj] * 5
        self.mca_buffer = [init_mca] * 5
        self.refuel_buffer = [init_refuel] * 5
        

    def pause_sim(self, channel=None):
        """
        Pause simulation and update hardware/GUI pause indicators.

        Parameters:
            channel : int, optional
                GPIO callback channel number when triggered by hardware.
        """
        self.sim.ctrl.paused = True
        GPIO.output(pinouts.SIM_PAUSE_LIGHT_OUTPUT, GPIO.HIGH)
        GPIO.output(pinouts.SIM_ON_LIGHT_OUTPUT, GPIO.LOW)
        self.sim._pause_start = time.time()
        self.pauseButton.setText("RESUME")
        self.consoleLog.append("~~~~ Pausing Simulation ~~~~")

    def resume_sim(self, channel=None):
        """
        Resume simulation and update hardware/GUI run indicators.

        Parameters:
            channel : int, optional
                GPIO callback channel number when triggered by hardware.
        """
        self.sim.ctrl.paused = False
        GPIO.output(pinouts.SIM_PAUSE_LIGHT_OUTPUT, GPIO.LOW)
        GPIO.output(pinouts.SIM_ON_LIGHT_OUTPUT, GPIO.HIGH)
        self.sim._paused_wall_time += time.time() - self.sim._pause_start
        self.sim._pause_start = None
        self.pauseButton.setText("PAUSE")
        self.consoleLog.append("~~~~ Resuming Simulation ~~~~")

    def reactorMeltdown(self):
        """
        Handle reactor meltdown event.

        Activates siren output if enabled and manages meltdown alert logic.
        """
        if GPIO.input(pinouts.SIREN_ENABLED):
            GPIO.output(pinouts.SIREN_OUTPUT, GPIO.HIGH)
        else:
            GPIO.output(pinouts.SIREN_OUTPUT, GPIO.LOW)


    def sds1_triggered(self, channel=None):
        """
        Trigger shutdown system 1 if not already active.

        Parameters:
            channel : int, optional
                GPIO callback channel.
        """
        # only trip if safety has not yet been enabled
        if not self.sim.ctrl.trip_sds1:
            self.sim.ctrl.trip_sds1 = True
            self.consoleLog.append("SDS1 Triggered")

    def sds2_triggered(self, channel=None):
        """
        Trigger shutdown system 2 if not already active.

        Parameters:
            channel : int, optional
                GPIO callback channel.
        """
        if not self.sim.ctrl.trip_sds2:
            self.sim.ctrl.trip_sds2 = True
            self.consoleLog.append("SDS2 Triggered")

    def setup_Hardware_Events(self):
        """
        Register GPIO interrupt callbacks for all hardware control inputs.
        """
        GPIO.add_event_detect(pinouts.RESET_SIM_INPUT, GPIO.FALLING, callback=self.reset_steady, bouncetime=100)
        GPIO.add_event_detect(pinouts.SIM_PAUSE_INPUT, GPIO.FALLING, callback=self.pause_sim, bouncetime=100)
        GPIO.add_event_detect(pinouts.SDS1_INPUT, GPIO.FALLING, callback=self.sds1_triggered, bouncetime=100)
        GPIO.add_event_detect(pinouts.SDS2_INPUT, GPIO.FALLING, callback=self.sds2_triggered, bouncetime=100)
        GPIO.add_event_detect(pinouts.SIM_ON_INPUT, GPIO.FALLING, callback=self.resume_sim, bouncetime=100)


    def closeEvent(self, event):
        """
        Safely terminate simulation thread when application closes.

        Parameters:
            event : QCloseEvent
                Qt close event object.
        """
        self.sim._running = False
        event.accept()

    def moving_average(self, new_val, buffer, N=5):
        """
        Apply moving-average filter to ADC input samples.

        Parameters:
            new_val : float
                New ADC voltage reading.
            buffer : list
                Rolling buffer of previous samples.
            N : int
                Moving average window size.

        Returns:
            float
                Filtered averaged value.
        """
        buffer.append(new_val)
        if len(buffer) > N:
            buffer.pop(0)
        return sum(buffer)/len(buffer)


class SimHardware():
    """
    Hardware abstraction layer for simulator ADC, DAC, and GPIO devices.

    Manages:
        - ADC initialization
        - DAC initialization
        - GPIO pin configuration
    """
    def __init__(self):
        """
        Initialize ADC/DAC hardware interfaces and hardware constants.
        """
        self.ADC_REF_VOLTAGE = 5.0 # Volts
        self.ADC = ADS1256.ADS1256()
        self.DAC = DAC8532.DAC8532()
        self.ADC.ADS1256_init()
        self.MAX_ADC_VOLTAGE = 3.0 # Volts

    def GPIO_pin_init(self):
        """
        Configure all Raspberry Pi GPIO pins for simulator hardware I/O.
        """
        GPIO.setup(pinouts.SDS1_INPUT, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
        GPIO.setup(pinouts.SDS2_INPUT, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
        GPIO.setup(pinouts.SAFETY_TOGGLE_INPUT, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
        GPIO.setup(pinouts.SAFETY_ON_OUTPUT, GPIO.OUT)
        GPIO.setup(pinouts.SIREN_OUTPUT, GPIO.OUT)
        GPIO.setup(pinouts.SIM_ON_INPUT, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
        GPIO.setup(pinouts.SIM_ON_LIGHT_OUTPUT, GPIO.OUT)
        GPIO.setup(pinouts.USER_ACTION_LIGHT_OUTPUT, GPIO.OUT)
        GPIO.setup(pinouts.SIM_PAUSE_INPUT, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
        GPIO.setup(pinouts.SIM_PAUSE_LIGHT_OUTPUT, GPIO.OUT)
        GPIO.setup(pinouts.RESET_SIM_INPUT, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
        GPIO.setup(pinouts.SIREN_ENABLED, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
        GPIO.setup(pinouts.SDS1_STATUS, GPIO.OUT)
        GPIO.setup(pinouts.SDS2_STATUS, GPIO.OUT)





# ============================================================
# Application Entry Point
# ============================================================
if __name__ == "__main__":
    app = QApplication([])

    globals()["PlotWidget"] = pg.PlotWidget

    window = MainGUIWindow()
    window.show()

    app.exec()

