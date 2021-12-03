import datetime
import os
from os import path
from queue import Queue
from threading import Thread
import time

import cv2
import numpy as np
import PySpin as spin

from scripts import camera_ttl
from scripts.config import constants as config
    

def image_acquisition_loop(camera_obj, timestamp_arr, dimensions, write_frame, still_active, maps, image_queue, counter):
    while still_active():
        try:
            # Remove timeout to prevent thread from hanging after acquisition is stopped.
            image = camera_obj.GetNextImage(34)
        except Exception:  # PySpin raises an exception when the timeout is reached, so stay silent here
            continue  # Likely hung on GetNextImage. Close thread.
        if not still_active():
            return
        timestamp_arr.append((image.GetFrameID(), image.GetTimeStamp()))
        #print((image.GetFrameID(), image.GetTimeStamp()))
        image_bgr = image.Convert(spin.PixelFormat_BGR8)
        cv_img_big = image_bgr.GetData().reshape((2 * dimensions[1], 2 * dimensions[0], 3))
        cv_img = cv2.resize(cv_img_big, dimensions)
        counter()
        if maps is not None:
            cv_img = cv2.remap(cv_img, *maps, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            # Here 0.5 is the alpha parameter, which determines how many of the original pixels should be kept in the image
        if image_queue is not None:
            image_queue.put(cv_img)
        write_frame(cv_img)
        # del cv_img
        del cv_img_big
        try:
            image.Release()
            image_bgr.Release()
        except Exception:
            # If this thread is in the middle of a loop when still_active changes, the call to image.release will fail
            pass


class FLIRCamera:
    def __init__(self, root_directory, acq_enabled, camera_serial, counter_port, port_name, frame_target, epoch_target, framerate=config['camera_framerate'], period_extension=0, dimensions=(640,512), calibration_param_path=None, use_queue=None, enforce_filename=None):
        self.framerate = framerate
        self.serial = camera_serial
        self.dimensions = dimensions
        self.base_dir = root_directory
        self.acq_enabled = acq_enabled
        self.is_capturing = False

        self.port = counter_port
        self.name = port_name
        self.period_extension = period_extension

        self.transformation_maps = None

        self.frame_target = frame_target
        self.frames_acquired = 0

        self.epoch_target = epoch_target
        self.epochs_acquired = 0

        self.queue = use_queue
        self.enforced_filename = enforce_filename

        if calibration_param_path:
            # Load calibration parameters
            print('Loading calibration parameters for {} from {}'.format(self.name, calibration_param_path))
            try:
                K_path = path.join(calibration_param_path, 'K.npy')
                D_path = path.join(calibration_param_path, 'D.npy')
                # Normalize the K matrix since it was designed for 1280x1024 images but we are using 640x512
                K = np.load(K_path) / 2
                K[2, 2] = 1
                D = np.load(D_path)
                new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(K, D, dimensions, np.eye(3), balance=0)
                self.transformation_maps = cv2.fisheye.initUndistortRectifyMap(K, D, np.eye(3), new_K, dimensions, cv2.CV_16SC2)
            except Exception as e:
                print(e)
                print('Failed to load calibration parameters for {}'.format(self.name))


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
        try:
            self.camera = camera_list.GetBySerial(self.serial)
        except Exception:
            raise Error('Failed to find camera {} with serial {}'.format(self.name, self.serial))
            return
        self.camera.Init()

        # Disable automatic exposure, gain, etc... Copied from previous script
        self.camera.ExposureAuto.SetValue(spin.ExposureAuto_Off)
        self.camera.GainAuto.SetValue(spin.GainAuto_Off)
        self.camera.BalanceWhiteAuto.SetValue(spin.BalanceWhiteAuto_Off)
        self.camera.AutoExposureTargetGreyValueAuto.SetValue(spin.AutoExposureTargetGreyValueAuto_Off)

        if self.port is not None:
            self.camera_task = camera_ttl.CameraTTLTask(self.framerate,
                period_extension=self.period_extension,
                counter_port=self.port,
                port_name=self.name)
        else:
            self.camera_task = None
        

    def inc_frame_count(self):
        self.frames_acquired += 1
        if self.frames_acquired >= self.frame_target:
            self.end_epoch()
            self.start_epoch()

    def create_video_file(self):
        start_time = datetime.datetime.now()
        if self.enforced_filename is None:
            start_time_str = start_time.strftime('%Y_%m_%d_%H_%M_%S_%f')
        else:
            start_time_str = self.enforced_filename
        if not path.exists(self.base_dir):
            os.mkdir(self.base_dir)
        self.timestamp_path = path.join(self.base_dir, '{}_{}.npy'.format(start_time_str, self.name))
        # video_directory = path.join(base_directory, start_time_str)
        # if not path.exists(video_directory):
            # os.mkdir(video_directory)
        video_path = path.join(self.base_dir, '{}_{}.avi'.format(start_time_str, self.name))
        writer = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'DIVX'), self.framerate, self.dimensions, isColor=True)

        # Reset the enforced filename field so future epochs calculate their own time
        self.enforced_filename = None
        return writer

    def save_ts_array(self):
        # The length here is arbitrary. Just to make sure we don't overwrite an existing npy file
        # with nearly empty data
        if len(self.timestamps) < 30 * 50:
            return
        np.save(self.timestamp_path, np.array(self.timestamps))
        self.timestamps.clear()

    def start_epoch(self):
        if self.epochs_acquired >= self.epoch_target:
            return

        self.video_writer = self.create_video_file()

        if self.is_capturing:
            # Testing out the effect of leaving everything active for the entire runtime
            # and only changing the file being written to upon entering new epochs
            return
        
        self.camera.BeginAcquisition()
        self.is_capturing = True
        if (self.camera_task is not None) and not (self.camera_task.is_active):
            self.camera_task.start()

        # Create a function to access is_capturing, creates the effect of passing the bool by reference
        enabled = lambda: self.is_capturing and safe_access_mp_bool(self.acq_enabled)

        # Begin separate thread for continued image acquisition:
        # 2021-12-03: replacing video writer object in args with function to write frame
        # this allows us to keep one thread alive for the whole 
        self.timestamps = list()
        self.acq_thread = Thread(
            target=image_acquisition_loop,
            args=(
                self.camera,
                self.timestamps,
                self.dimensions,
                self.write_frame,
                enabled,
                self.transformation_maps,
                self.queue,
                self.inc_frame_count))
        self.acq_thread.start()

    def write_frame(self, frame):
        self.video_writer.write(frame)

    def end_epoch(self):
        try:
            self.save_ts_array()
            self.epochs_acquired += 1
            self.frames_acquired = 0
            self.video_writer.release()
        except Exception as e:
            print('something wrong in end epoch')
            # Things most likely released out of order
            print(e)
            pass

    def release(self):
        self.end_epoch()
        if self.is_capturing:
            self.camera.EndAcquisition()
            self.is_capturing = False
        if self.camera_task is not None:
                self.camera_task.stop()
        del self.camera
        self.spin_system.ReleaseInstance()
        if self.camera_task is not None:
            self.camera_task.close()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        try:
            if hasattr(self, 'camera'):
                self.end_capture()
                self.release()
        except Exception as e:
            print(e)


def safe_access_mp_bool(mp_bool):
    """ Safely accesses a shared variable by catching the exception that
    occurs when the variable ceases to exist
    """
    try:
        return mp_bool.value
    except Exception:
        return False