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


def image_acquisition_loop(camera_obj, timestamp_arr, dimensions, video_writer, still_active, camera_matrix, camera_distortions):
    while still_active():
        try:
            # Remove timeout to prevent thread from hanging after acquisition is stopped.
            image = camera_obj.GetNextImage(0)
        except Exception:  # PySpin raises an exception when the timeout is reached, so stay silent here
            continue  # Likely hung on GetNextImage. Close thread.
        timestamp_arr.append(image.GetTimeStamp())

        image_bgr = image.Convert(spin.PixelFormat_BGR8)
        cv_img = image_bgr.GetData().reshape((dimensions[1], dimensions[0], 3))
        video_writer[0].write(cv_img)
        if camera_matrix is not None and camera_distortions is not None:
            h, w = cv_img.shape[:2]
            # Here 0.5 is the alpha parameter, which determines how many of the original pixels should be kept in the image
            new_mtx, roi = cv2.getOptimalNewCameraMatrix(camera_matrix, camera_distortions, (w,h), 1, (w,h))
            cv_img = cv2.undistort(cv_img, camera_matrix, camera_distortions, None, new_mtx)
            # x, y, roi_w, roi_h = roi
            # roi_image = cv_img[y:y+roi_h, x:x+roi_h, :]
            # cv_img = np.resize(roi_image, (w, h, 3))
        video_writer[1].write(cv_img)
        try:
            image.Release()
        except Exception:
            # If this thread is in the middle of a loop when still_active changes, the call to image.release will fail
            pass


class FLIRCamera:
    def __init__(self, root_directory, framerate=CALCULATED_FRAMERATE, period_extension=0, camera_index=0, dimensions=(640,512), counter_port=u'Dev1/ctr0', port_name=u'camera_0', calibration_param_path=None):
        self.framerate = framerate
        self.camera_index = camera_index
        self.dimensions = dimensions
        self.base_dir = root_directory

        self.port = counter_port
        self.name = port_name
        self.period_extension = period_extension

        self.cam_mat = None
        self.dist_vecs = None

        if calibration_param_path:
            # Load calibration parameters
            print('Loading calibration parameters for {} from {}'.format(self.name, calibration_param_path))
            try:
                cam_mat_path = path.join(calibration_param_path, 'camera_matrix.npy')
                dist_vec_path = path.join(calibration_param_path, 'distortions.npy')
                self.cam_mat = np.load(cam_mat_path)
                self.dist_vecs = np.load(dist_vec_path)
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
        orig_path = path.join(self.base_dir, '{}_orig_cam{}.avi'.format(start_time_str, self.camera_index))
        writer_orig = cv2.VideoWriter(orig_path, cv2.VideoWriter_fourcc(*'DIVX'), self.framerate, self.dimensions)
        writer_transformed = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'DIVX'), self.framerate, self.dimensions)
        return writer_orig, writer_transformed

    def start_capture(self):
        self.camera_task = camera_ttl.CameraTTLTask(self.framerate,
            period_extension=self.period_extension,
            counter_port=self.port,
            port_name=self.name)

        self.camera.BeginAcquisition()
        self.camera_task.start()

        # Create a function to access is_capturing, creates the effect of passing the bool by reference
        self.is_capturing = True
        enabled = lambda: self.is_capturing

        # Begin separate thread for continued image acquisition:
        self.video_writer = self.create_video_file()
        self.timestamps = list()
        self.acq_thread = Thread(
            target=image_acquisition_loop,
            args=(self.camera, self.timestamps, self.dimensions, self.video_writer, enabled, self.cam_mat, self.dist_vecs))
        self.acq_thread.start()

    def end_capture(self):
        try:
            self.is_capturing = False
            self.camera.EndAcquisition()
            self.camera_task.stop()
            self.camera_task.close()
            self.video_writer[0].release()
            self.video_writer[1].release()
            del self.camera
            self.spin_system.ReleaseInstance()
        except Exception:
            # Things most likely released out of order
            pass
        np.save(self.timestamp_path, np.array(self.timestamps))

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        try:
            if hasattr(self, 'camera'):
                self.end_capture()
        except Exception as e:
            print(e)


def demo(capture_dir):
    print('Running video_acquisition.py demo')
    with FLIRCamera(capture_dir,
            camera_index=1,
            counter_port=u'Dev1/ctr1',
            port_name=u'camera1',
            calibration_param_path='camera_params/cam1') as cam:
        cam.start_capture()
        time.sleep(30)
        cam.end_capture()
    print('Done')


def demo_2cam(capture_dir):
    cam0 = FLIRCamera(capture_dir,
            camera_index=0,
            counter_port=u'Dev1/ctr0',
            port_name='camera0')
    cam1 = FLIRCamera(capture_dir,
            camera_index=1,
            counter_port=u'Dev1/ctr1',
            port_name='camera1')
    cam0.start_capture()
    cam1.start_capture()
    time.sleep(10)
    cam0.end_capture()
    cam1.end_capture()

 
if __name__ == '__main__':
    demo('captured_frames')

