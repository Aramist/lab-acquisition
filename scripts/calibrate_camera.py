import os
from os import path

import cv2
import numpy as np


image_dir = 'calibration'
image_paths = sorted([path.join(image_dir, filename) for filename in os.listdir(image_dir)])

output_dir = 'camera_params/cam1'

# This might need to change if a different checkerboard image is used
board_size = (7, 9)
criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

# Lists to hold the locations of checkerboard corners in the world and in the image
world_points = list()
image_points = list()

# The origin and orientation of the world coordinates is arbitrary for our purposes
world_frame = np.zeros((1, board_size[0] * board_size[1], 3), np.float32)
world_frame[0, :, :2] = np.mgrid[0:board_size[0], 0:board_size[1]].T.reshape(-1, 2)
prev_image_shape = None

for image_path in image_paths:
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Finds the locations of chessboard corners in image space
    ret, corners = cv2.findChessboardCorners(gray,
            board_size,
            cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_FAST_CHECK +
            cv2.CALIB_CB_NORMALIZE_IMAGE)
    if ret:
        world_points.append(world_frame)
        corners_refined = cv2.cornerSubPix(gray,
                corners,
                (11, 11),
                (-1, -1),
                criteria)
        image_points.append(corners_refined)


ret, mtx, dist, r_mat, t_mat = cv2.calibrateCamera(world_points,
        image_points,
        gray.shape[::-1],
        None,
        None)

np.save('rotations.npy', r_mat)
np.save('translations.npy', t_mat)
np.save('camera_matrix.npy', mtx)
np.save('distortions.npy', dist)

