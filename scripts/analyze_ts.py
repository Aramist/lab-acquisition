import argparse

import matplotlib.pyplot as plt
import numpy as np


parser = argparse.ArgumentParser(description='Extracts information from .npy dumps of timestamps')
parser.add_argument('filepath', type=str, help='Location of the numpy file containing the timestamps')
parser.add_argument('framerate', type=int, default=30, help='Framerate of the video the data are collected from.')

args = parser.parse_args()

ts = np.load(args.filepath) * 1e-6  # Multiply by 10e-6 to convert from nanoseconds to milliseconds
framerate = args.framerate
expected = np.linspace(ts[0], ts[0] + 1000/framerate * (ts.shape[0] - 1), ts.shape[0])
diffs = np.diff(ts)  # Returns the time difference between each consecutive timestamp
mean = np.mean(diffs)
std = np.std(diffs)

print('Num timestamps collected: {} frames'.format(ts.shape[0]))
print('For reference: 1/{} sec = {} ms'.format(framerate, 1000/framerate))
print('Mean error between frames: {} ms'.format(1000/framerate - mean))
print('Standard deviation: {} ms'.format(std))


# Both plots use 1000/30 - diffs in order to display the error in the time differences.
"""
plt.subplot(1, 2, 1)
plt.title('Inter-frame Time Error vs. Frame #')
plt.scatter(np.arange(diffs.shape[0]), 1000/30 - diffs, s=1, color='b', label='Time between frames')
plt.axhline(1000/30 - mean, color='k', linestyle='dashed', linewidth=1, label='Mean')
plt.xlabel('Frame')
plt.ylabel('Error in Inter-frame Time Relative to 1/30sec (ms)')
plt.legend()
"""

# plt.subplot(1, 2, 2)
plt.title('Distribution of Inter-frame Time Error')
plt.hist(1000/framerate - diffs, bins=40, label='Time between frames')
plt.axvline(1000/framerate - mean, color='k', linestyle='dashed', linewidth=1, label='Mean')
plt.xlabel('Error in Inter-frame Time Relative to 1/{}sec (ms)'.format(framerate))
plt.ylabel('Frames')
plt.legend()
plt.show()

#plt.subplot(2, 2, 3)
plt.title('Testing for Cumulative Effects of Camera Trigger Mistiming Events')
relative_ts = ts - ts[0]
relative_expected = expected - ts[0]
plt.plot([0, relative_expected.shape[0] - 1], [0, relative_expected[-1]], 'b-', label='Expected Timestamps')
plt.scatter(np.arange(relative_ts.shape[0]), relative_ts, s=2, c='r', label='Observed Timestamps')
plt.xlabel('Frame #')
plt.ylabel('Timestamp (ms)')
plt.legend()
plt.show()

plt.title('Error in Observed Timestamps Relative to Perfect {}fps Timing'.format(framerate))
plt.scatter(np.arange(ts.shape[0]) / framerate / 3600, ts - expected, s=2, c='r', label='Residuals')
# Find the weird spot
plt.legend()
plt.xlabel('Time Since Start (hrs)')
plt.ylabel('Timestamp Error (ms)')
plt.show()

print((ts-expected)[-1])

