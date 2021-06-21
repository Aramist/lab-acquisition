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
CALCULATED_FRAMERATE = 29.9998066833


def image_acquisition_loop(camera_obj, timestamp_arr, dimensions, video_writer, still_active):
    while still_active():
        try:
            image = camera_obj.GetNextImage()
        except Exception:
            print('Ending acquisition thread')  # Avoid completely silent errors
            return  # Likely hung on GetNextImage. Close thread.
        timestamp_arr.append(image.GetTimeStamp())
        image_bgr = image.Convert(spin.PixelFormat_BGR8)
        video_writer.write(image_bgr.GetData().reshape((dimensions[1], dimensions[0], 3)))
        image.Release()


class FLIRCamera:
    def __init__(self, root_directory, framerate=CALCULATED_FRAMERATE, camera_index=0, dimensions=(1280,1024)):
        self.framerate = framerate
        self.camera_index = camera_index
        self.dimensions = dimensions
        self.base_dir = root_directory

        # For documentation/debugging purposes:
        flir_system = spin.System.GetInstance()
        flir_version = flir_system.GetLibraryVersion()
        print('Flir PySpin library version: {}.{}.{}.{}'.format(
            flir_version.major,
            flir_version.minor,
            flir_version.type,
            flir_version.build))

        # IMPORTANT: Keep a useles reference of spin.System around to prevent PySpin from silently crashing your program
        self.spin_system = flir_system  # Do not delete this line

        camera_list = flir_system.GetCameras()
        if camera_list.GetSize() <= camera_index:
            raise Exception('Camera index {} out of bounds'.format(camera_index))
            return
        self.camera = camera_list[camera_index]
        self.camera.Init()

        # Disable automatic exposure, gain, etc... Copied from previous script
        self.camera.ExposureAuto.SetValue(spin.ExposureAuto_Off)
        self.camera.GainAuto.SetValue(spin.GainAuto_Off)
        self.camera.BalanceWhiteAuto.SetValue(spin.BalanceWhiteAuto_Off)
        self.camera.AutoExposureTargetGreyValueAuto.SetValue(spin.AutoExposureTargetGreyValueAuto_Off)

    def create_video_file(self):
        start_time = datetime.datetime.now()
        start_time_str = start_time.strftime(FILENAME_DATE_FORMAT)
        if not path.exists(self.base_dir):
            os.mkdir(self.base_dir)
        self.timestamp_path = path.join(self.base_dir, '{}_cam{}.npy'.format(start_time_str, self.camera_index))
        # video_directory = path.join(base_directory, start_time_str)
        # if not path.exists(video_directory):
            # os.mkdir(video_directory)
        video_path = path.join(self.base_dir, '{}_cam{}.avi'.format(start_time_str, self.camera_index))
        return cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'DIVX'), self.framerate, self.dimensions)

    def start_capture(self):
        self.video_writer = self.create_video_file()
        self.camera_task = camera_ttl.CameraTTLTask(self.framerate)

        self.camera.BeginAcquisition()
        self.camera_task.start()

        # Create a function to access is_capturing, creates the effect of passing the bool by reference
        self.is_capturing = True
        enabled = lambda: self.is_capturing

        # Begin separate thread for continued image acquisition:
        self.timestamps = list()
        self.acq_thread = Thread(target=image_acquisition_loop, args=(self.camera, self.timestamps, self.dimensions, self.video_writer, enabled))
        self.acq_thread.start()

    def end_capture(self):
        self.is_capturing = False
        self.camera.EndAcquisition()
        self.camera_task.stop()
        self.video_writer.release()
        np.save(self.timestamp_path, np.array(self.timestamps))

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        try:
            self.end_capture()
        except Exception as e:
            print(e)


def demo(capture_dir):
    print('Running video_acquisition.py demo')
    with FLIRCamera(capture_dir) as cam:
        cam.start_capture()
        time.sleep(10)
        cam.end_capture()
    print('Done')


if __name__ == '__main__':
    demo('captured_frames')

