import cv2
import matplotlib.pyplot as plt
import numpy as np


vid_path = 'video.avi'
reader = cv2.VideoCapture(vid_path)

means = list()
frame_count = 0
while reader.isOpened():
    ret, frame = reader.read()
    
    if not ret:
        break
    hsv_image = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mean_value = np.mean(hsv_image, axis=(0, 1))[2]
    means.append(mean_value)
    frame_count += 1
    if frame_count % 30 * 5 == 0:
        print('Progress: {}s'.format(frame_count // 30))

plt.scatter(np.arange(len(means))/30, means, s=1, c='b', label='Average brightness of pixels across entire frame')
plt.xlabel('Time (sec)')
plt.ylabel('Value (in HSV)')
plt.title('Fluctuations of Average Frame Brightness under Red Light')
plt.legend()
plt.savefig('fluctuation_graph.png')
plt.show()