import os
from os import path

import cv2
import numpy as np


image_dir = 'calibration'
image_paths = sorted([path.join(image_dir, filename) for filename in os.listdir(image_dir) if filename.endswith('.png')])

use_vid = True
vid_path = path.join(image_dir, 'calibrate.avi')

output_dir = 'camera_params/cam_a'
if not path.exists(output_dir):
    os.mkdir(output_dir)

# This might need to change if a different checkerboard image is used
board_size = (7, 9)
criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
cal_flags = cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC \
            + cv2.fisheye.CALIB_FIX_SKEW
            # + cv2.fisheye.CALIB_CHECK_COND \


# Lists to hold the locations of checkerboard corners in the world and in the image
world_points = list()
image_points = list()

# The origin and orientation of the world coordinates is arbitrary for our purposes
world_frame = np.zeros((1, board_size[0] * board_size[1], 3), np.float32)
world_frame[0, :, :2] = np.mgrid[0:board_size[0], 0:board_size[1]].T.reshape(-1, 2)
# image_shape = None
num_samples = 0


def process(img):
    # img = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2))
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img

    global image_shape
    image_shape = gray.shape
    # Finds the locations of chessboard corners in image space
    ret, corners = cv2.findChessboardCorners(gray,
            board_size,
            cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_FAST_CHECK + cv2.CALIB_CB_NORMALIZE_IMAGE)
    if ret:
        world_points.append(world_frame)
        corners_refined = cv2.cornerSubPix(gray,
                corners,
                (5, 5),
                (-1, -1),
                criteria)
        image_points.append(corners_refined)



if not use_vid:
    num_samples = len(image_paths)
    for image_path in image_paths:
        img = cv2.imread(image_path)
        sh = img.shape
        img = cv2.resize(img, (img.shape[1], img.shape[0]))
        process(img)
else:
    cap = cv2.VideoCapture(vid_path)
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        num_samples += 1
        process(frame)


k_matrix = np.zeros((3, 3))
d_matrix = np.zeros((4, 1))
# Placeholders for rotation and translation vectors
r_vecs = [np.zeros((1, 1, 3), dtype=float) for _ in range(num_samples)]
t_vecs = [np.zeros((1, 1, 3), dtype=float) for _ in range(num_samples)]

print(criteria)
print(image_shape[::-1])
cv2.fisheye.calibrate(
    world_points,
    image_points,
    image_shape[::-1],
    k_matrix,
    d_matrix,
    r_vecs,
    t_vecs,
    cal_flags,
    criteria
)


np.save(path.join(output_dir, 'K.npy'), k_matrix)
np.save(path.join(output_dir, 'D.npy'), d_matrix)

print('K: {}'.format(str(k_matrix)))
print('D: {}'.format(str(d_matrix)))

