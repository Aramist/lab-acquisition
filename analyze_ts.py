import matplotlib.pyplot as plt
import numpy as np

ts = np.load('camera_timestamps.npy') * 1e-6  # Multiply by 10e-6 to convert from nanoseconds to milliseconds
diffs = np.diff(ts)  # Returns the time difference between each consecutive time stamp
mean = np.mean(diffs)
std = np.std(diffs)

print('Num timestamps collected: {} frames'.format(ts.shape[0]))
print('For reference: 1/30 sec = {} ms'.format(1000/30))
print('Mean time difference between frames: {} ms'.format(mean))
print('Standard deviation: {} ms'.format(std))


# Both plots use 1000/30 - diffs in order to display the error in the time differences.
plt.subplot(1, 2, 1)
plt.plot(np.arange(diffs.shape[0]), 1000/30 - diffs, 'bo')
plt.subplot(1, 2, 2)
plt.hist(1000/30 - diffs, bins=40)
plt.show()

