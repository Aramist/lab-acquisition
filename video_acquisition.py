import datetime
import os
from os import path
from threading import Thread
import time

import cv2
import numpy as np
import PySpin as spin

import camera_ttl


FILENAME_DATE_FORMAT = '%Y_%m_%d_%H_%M_%S_%f'


def image_acquisition_loop(camera_obj, timestamp_arr, dimensions, video_writer, still_active):
    while still_active:
        image = camera_obj.GetNextImage()
        timestamp_arr.append(image.GetTimeStamp())
        image_bgr = image.Convert(spin.PixelFormat_BGR8)
        video_writer.write(image_bgr.GetData().reshape((dimensions[1], dimensions[0], 3)))
        image.Release()



# Dimensions are given as (height, width)
def setup_camera(base_directory, framerate=30, dimensions=(1280,1024)):
    print('Beginning FLIR camera configuration')
    # For documentation/debugging purposes:
    flir_system = spin.System.GetInstance()
    flir_version = flir_system.GetLibraryVersion()
    print('Flir PySpin library version: {}.{}.{}.{}'.format(
        flir_version.major,
        flir_version.minor,
        flir_version.type,
        flir_version.build))

    camera_list = flir_system.GetCameras()
    if camera_list.GetSize() < 1:
        raise Exception('No cameras detected')
        return
    camera = camera_list[0]
    camera.Init()

    # Disable automatic exposure, gain, etc... Copied from previous script
    camera.ExposureAuto.SetValue(spin.ExposureAuto_Off)
    camera.GainAuto.SetValue(spin.GainAuto_Off)
    camera.BalanceWhiteAuto.SetValue(spin.BalanceWhiteAuto_Off)
    camera.AutoExposureTargetGreyValueAuto.SetValue(spin.AutoExposureTargetGreyValueAuto_Off)
    
    start_time = datetime.datetime.now()
    start_time_str = start_time.strftime(FILENAME_DATE_FORMAT)
    if not path.exists(base_directory):
        os.mkdir(base_directory)
    video_directory = path.join(base_directory, start_time_str)
    if not path.exists(video_directory):
        os.mkdir(video_directory)
    video_path = path.join(video_directory, '{}.avi'.format(start_time_str))
    cv_out = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'DIVX'), framerate, dimensions)

    # For analysis:
    flir_timestamps = list()

    with camera_ttl.CameraTTLTask(framerate) as camera_task:
        camera.BeginAcquisition()
        camera_task.start()
        is_enabled = True
        enabled = lambda: is_enabled
        # Begin separate thread for continued image acquisition:
        acq_thread = Thread(target=image_acquisition_loop, args=(camera, flir_timestamps, dimensions, cv_out, enabled))
        acq_thread.start()
        time.sleep(15)
        is_enabled = False
        camera.EndAcquisition()
        camera_task.stop()
        cv_out.release()

    timestamp_arr = np.array(flir_timestamps)
    np.save('camera_timestamps', timestamp_arr)


setup_camera('captured_frames')
