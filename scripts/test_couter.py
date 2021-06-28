from functools import partial
from os import path
import time

import nidaqmx as ni
from nidaqmx.constants import READ_ALL_AVAILABLE
from nidaqmx.constants import AcquisitionType
import numpy as np


SAMPLE_RATE = 10000


def callback(task,
        task_handle,
        event_type,
        num_samples,
        data):
    data = np.array(task.read(number_of_samples_per_channel=READ_ALL_AVAILABLE, timeout=0))
    print(data)
    print(np.sum(data > 1))


with ni.Task() as task:
    task.di_channels.add_di_chan('dev1/P0.0', 'counter_input')
    task.timing.cfg_samp_clk_timing(
        rate=SAMPLE_RATE,
        sample_mode=AcquisitionType.CONTINUOUS,
        samps_per_chan=SAMPLE_RATE*5)
    task.register_every_n_samples_acquired_into_buffer_event(
                sample_interval=SAMPLE_RATE//2,
                callback_method=partial(callback, task))
    task.start()

