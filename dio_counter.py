import time

import nidaqmx as ni
from nidaqmx import types
from nidaqmx import constants


def run():
    with ni.Task() as task:
        counter_port_loc = u'Dev1/ctr0'
        counter_port_name = u'counter_0'
        co_channel = task.co_channels.add_co_pulse_chan_freq(counter_port_loc, counter_port_name, freq=10, duty_cycle=0.5)

        # Set some parameters:
        # First, tell the device that the frequency and duty cycle won't change. This makes it use fewer resources
        # co_channel.co_constrained_gen_mode = constants.ConstrainedGenMode.FIXED_HIGH_FREQ
        # Second, specify that the channel should have continuous output. Without this only one pulse is generated
        task.timing.cfg_implicit_timing(sample_mode=constants.AcquisitionType.CONTINUOUS)
        # pulse = types.CtrTime(high_time=1e-4, low_time=(1/10 - 1e-4))
        # pulse = types.CtrFreq(freq=1, duty_cycle=0.5)
        #task.write(pulse)
        task.start()
        time.sleep(10)
        task.stop()


if __name__ == '__main__':
    run()

