from collections import deque
from itertools import cycle
import time
import queue

import h5py
import numpy as np
from scipy import signal


def fake_mic_data():
    file = h5py.File('mic.h5', 'r')
    arr = file['analog_input'][0]
    cyc = cycle(arr)
    while True:
        ret = np.array(
            [next(cyc) for _ in range(65200)],
            dtype=np.float32
        )
        yield(ret)

    return np.random.rand(1, 62500)


def fake_spec_task(duration, spec_queue):
    if spec_queue is None:
        return
    data_gen = fake_mic_data()
    mic_deque = deque(maxlen=20)
    start_time = time.time()
    while duration < 0 or time.time() - start_time < duration:
        mic_deque.append(next(data_gen))
        data_arr = np.concatenate(list(mic_deque), axis=0)
        spec_data = signal.spectrogram( \
            data_arr, 
            fs=125000,
            nfft=1024,
            noverlap=256,
            nperseg=1024,
            scaling='density')
        spec_data = (
            spec_data[0].astype(np.float16),
            spec_data[1].astype(np.float16),
            spec_data[2].astype(np.float32)
        )
        spec_queue.put(spec_data)
        time.sleep(0.5)


if __name__ == '__main__':
    fake_spec_task(3, queue.Queue())