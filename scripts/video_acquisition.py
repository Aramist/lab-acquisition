import datetime
import os
from os import path
from queue import Queue
from threading import Thread
import time

import cv2
import numpy as np
import PySpin as spin

if 'scripts' in __name__:
    from scripts import camera_ttl
else:
    import camera_ttl
    

FILENAME_DATE_FORMAT = '%Y_%m_%d_%H_%M_%S_%f'
CALCULATED_FRAMERATE = 29.9998066833

def image_acquisition_loop(camera_obj, timestamp_arr, dimensions, video_writer, still_active, K, D, image_queue, save_ts_fn, counter):
    while still_active():
        try:
            # Remove timeout to prevent thread from hanging after acquisition is stopped.
            image = camera_obj.GetNextImage(0)
        except Exception:  # PySpin raises an exception when the timeout is reached, so stay silent here
            continue  # Likely hung on GetNextImage. Close thread.
        if not still_active():
            return
        timestamp_arr.append((image.GetFrameID(), image.GetTimeStamp()))
        image_bgr = image.Convert(spin.PixelFormat_BGR8)
        cv_img_big = image_bgr.GetData().reshape((2 * dimensions[1], 2 * dimensions[0], 3))
        cv_img = cv2.resize(cv_img_big, dimensions)
        counter()
        if K is not None and D is not None:
            new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(K, D, dimensions, np.eye(3), balance=0.5)
            maps = cv2.initUndistortRectifyMap(K, D, np.eye(3), K, dimensions, cv2.CV_16SC2)
            cv_img = cv2.remap(cv_img, *maps, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            # Here 0.5 is the alpha parameter, which determines how many of the original pixels should be kept in the image
        if image_queue is not None:
            image_queue.put(cv_img)
        video_writer.write(cv_img)
        # del cv_img
        del cv_img_big
        try:
            image.Release()
            image_bgr.Release()
        except Exception:
            # If this thread is in the middle of a loop when still_active changes, the call to image.release will fail
            pass
        # Reset timestamp array every 5 minutes to reduce memory consumption. Honestly, is this even major? 30 min = 30 * 60 * 30 * 8 bytes < 0.5MB
        if len(timestamp_arr) > 30 * 60 * 5:
            save_ts_fn()


class FLIRCamera:
    # Static variables for our cameras' serial numbers:
    CAMERA_A_SERIAL = '19390113'
    CAMERA_B_SERIAL = '19413860'

    def __init__(self, root_directory, acq_enabled, camera_serial, counter_port, port_name, frame_target, framerate=CALCULATED_FRAMERATE, period_extension=0, dimensions=(640,512), calibration_param_path=None, use_queue=None, enforce_filename=None):
        self.framerate = framerate
        self.serial = camera_serial
        self.dimensions = dimensions
        self.base_dir = root_directory
        self.acq_enabled = acq_enabled

        self.port = counter_port
        self.name = port_name
        self.period_extension = period_extension

        self.K_matrix = None
        self.D_matrix = None

        self.frame_target = frame_target
        self.frames_acquired = 0

        self.queue = use_queue
        self.enforced_filename = enforce_filename

        if calibration_param_path:
            # Load calibration parameters
            print('Loading calibration parameters for {} from {}'.format(self.name, calibration_param_path))
            try:
                K_path = path.join(calibration_param_path, 'K.npy')
                D_path = path.join(calibration_param_path, 'D.npy')
                self.K_matrix = np.load(K_path)
                self.D_matrix = np.load(D_path)
            except:
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
            self.end_capture()

    def create_video_file(self):
        start_time = datetime.datetime.now()
        if self.enforced_filename is None:
            start_time_str = start_time.strftime(FILENAME_DATE_FORMAT)
        else:
            start_time_str = self.enforced_filename
        if not path.exists(self.base_dir):
            os.mkdir(self.base_dir)
        self.timestamp_path = path.join(self.base_dir, '{}_{}.npy'.format(start_time_str, self.name))
        # video_directory = path.join(base_directory, start_time_str)
        # if not path.exists(video_directory):
            # os.mkdir(video_directory)
        video_path = path.join(self.base_dir, '{}_{}.avi'.format(start_time_str, self.name))
        writer= cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'DIVX'), self.framerate, self.dimensions, isColor=True)

        # Reset the enforced filename field so future epochs calculate their own time
        self.enforced_filename = None
        return writer

    def save_ts_array(self):
        np.save(self.timestamp_path, np.array(self.timestamps))
        self.timestamps.clear()

    def start_capture(self):
        self.camera.BeginAcquisition()
        if self.camera_task is not None:
            self.camera_task.start()

        # Create a function to access is_capturing, creates the effect of passing the bool by reference
        self.is_capturing = True
        enabled = lambda: self.is_capturing and self.acq_enabled.value

        # Begin separate thread for continued image acquisition:
        self.video_writer = self.create_video_file()
        self.timestamps = list()
        self.acq_thread = Thread(
            target=image_acquisition_loop,
            args=(self.camera,
                self.timestamps,
                self.dimensions,
                self.video_writer,
                enabled,
                self.K_matrix,
                self.D_matrix,
                self.queue,
                self.save_ts_array,
                self.inc_frame_count))
        self.acq_thread.start()

    def end_capture(self):
        try:
            self.save_ts_array()
            self.frames_acquired = 0
            self.is_capturing = False
            if self.camera_task is not None:
                self.camera_task.stop()
            self.camera.EndAcquisition()
            self.video_writer.release()
        except Exception:
            # Things most likely released out of order
            pass

    def release(self):
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


def demo(capture_dir):
    print('Running video_acquisition.py demo')
    with FLIRCamera(capture_dir,
            framerate=30,
            camera_serial=FLIRCamera.CAMERA_B_SERIAL,
            counter_port=u'Dev1/ctr1',
            port_name=u'camera_b') as cam:
        #    calibration_param_path='camera_params/cam_a') as cam:
        cam.start_capture()
        """
        start_time = time.time()
        while time.time() - start_time < 60:
            try:
                cv2.imshow('image', cam.queue.get(timeout=0.03))
                cv2.waitKey(1)
            except Exception:
                continue
        """
        time.sleep(120)
        cam.end_capture()
    print('Done')

 
if __name__ == '__main__':
    demo('captured_frames')
