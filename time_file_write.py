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
        time_array[i][:] = np.array(trial(i+1)) * 1000
    means = np.mean(time_array, axis=1)
    devs = np.std(time_array, axis=1)
    print(means)
    print(devs)
    quartiles = np.quantile(time_array, [0.25, 0.50, 0.75], axis=1)
    median_q1_dist = quartiles[1] - quartiles[0]
    q3_median_dist = quartiles[2] - quartiles[1]
    x_axis = np.arange(1, 17, 1)
    plt.errorbar(x_axis, means.flatten(), yerr=[median_q1_dist, q3_median_dist], fmt='bo')
    plt.title('Write Time for 0.5s Acquisition vs # Channels Recorded.')
    plt.xlabel('# Channels Recorded')
    plt.ylabel('Time per write (65k samples, ms)')
    plt.show()


if __name__ == '__main__':
    run()

