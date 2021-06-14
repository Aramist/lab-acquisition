import random
import time

import matplotlib.pyplot as plt
import numpy as np

import test_recording


class Timer:
    def __init__(self, func):
        self.func = func

    def __call__(self, *args, **kwargs):
        start_time = time.time()
        self.func(*args, **kwargs)
        end_time = time.time()
        return end_time - start_time


def random_data(num_streams, mean_size, stdev_size):
    length = int(random.gauss(mean_size, stdev_size))
    return (np.random.rand(num_streams, length) - 0.5) * 10


@Timer
def write_data(writer, data):
    writer.write(data)


def trial(num_streams):
    # Create a writer for this trial:
    times = list()
    with test_recording.mic_data_writer(100, f'{num_streams}_streams_{{}}.hdf5', 'timing_experiment', ['mic_{}'.format(a) for a in range(num_streams)], infinite=True, num_microphones=num_streams) as writer:
        for _ in range(1000):
            sample_data = random_data(num_streams, 125000//2, 100)
            time = write_data(writer, sample_data)
            times.append(time)
    return(times)


def run():
    time_array = np.zeros((16, 1000), dtype=float)
    for i in range(16):
        time_array[i][:] = np.array(trial(i+1))
    means = np.mean(time_array, axis=1) * 1000
    devs = np.std(time_array, axis=1) * 1000
    print(means)
    print(devs)
    x_axis = np.arange(1, 17, 1)
    plt.scatter(x_axis, means.flatten(), 2)
    plt.xlabel('# Channels Recorded')
    plt.ylabel('Time per write (65k samples, ms)')
    plt.show()


if __name__ == '__main__':
    run()

