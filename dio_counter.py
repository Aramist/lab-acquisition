import time

import nidaqmx as ni
from nidaqmx import types


def run():
    with ni.Task() as task:
        counter_port_loc = 'dev1/p2.4'
        counter_port_name = u'counter_0'
        task.do_channels.add_do_chan(counter_port_loc, counter_port_name)

        # pulse = types.CtrTime(high_time=1e-4, low_time=(1/10 - 1e-4))
        pulse = types.CtrFreq(freq=10, duty_cycle=0.5)
        task.write(pulse)
        time.sleep(10)
        task.stop()


if __name__ == '__main__':
    run()

