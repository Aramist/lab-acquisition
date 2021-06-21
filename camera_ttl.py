import time

import nidaqmx as ni
from nidaqmx import types
from nidaqmx import constants


class CameraTTLTask:
    def __init__(self, framerate, counter_port=u'Dev1/ctr0', port_name='camera_0', duty_cycle=0.1):
        self.frequency = framerate
        self.port = counter_port
        self.name = port_name
        self.duty_cycle = duty_cycle
        self.configure_task()

    def configure_task(self):
        self.counter_task = ni.Task()
        # Don't think there are any strict requirements on the duty cycle here, as the camera listens for the rising edge
        self.counter_task.co_channels.add_co_pulse_chan_freq(
                self.port,
                self.name,
                freq=self.frequency,
                duty_cycle=self.duty_cycle)
        # If this is not set to Continuous, only one pulse is generated.
        self.counter_task.timing.cfg_implicit_timing(sample_mode=constants.AcquisitionType.CONTINUOUS)

    def start(self):
        self.counter_task.start()

    def stop(self):
        self.counter_task.stop()

    def close(self):
        self.counter_task.close()

    def __enter__(self):
        return self.counter_task

    def __exit__(self, type, value, traceback):
        self.counter_task.close()


def example():
    with CameraTTLTask(framerate=30, counter_port=u'Dev1/ctr0', port_name='camera_0') as task:
        task.start()
        time.sleep(300)  # Or any other function that blocks the interpreter
        task.stop()


if __name__ == '__main__':
    example()

