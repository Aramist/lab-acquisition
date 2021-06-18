import datetime
import os
from os import path
import time

import PySpin as spin

# import camera_ttl


FILENAME_DATE_FORMAT = '%Y_%m_%d_%H_%M_%S_%f'


def setup_camera(base_directory, framerate=30):
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
    #camera.ExposureAuto.SetValue(spin.ExposureAuto_Off)
    #camera.GainAuto.SetValue(spin.GainAuto_Off)
    #camera.BalanceWhiteAuto.SetValue(spin.BalanceWhiteAuto_Off)
    #camera.AutoExposureTargetGreyValueAuto.SetValue(spin.AutoExposureTargetGreyValueAuto_Off)
    
    start_time = datetime.datetime.now()
    start_time_str = start_time.strftime(FILENAME_DATE_FORMAT)
    if not path.exists(base_directory):
        os.mkdir(base_directory)
    image_directory = path.join(base_directory, start_time_str)
    if not path.exists(image_directory):
        os.mkdir(image_directory)

    with camera_ttl.CameraTTLTask(framerate) as camera_task:
        camera.BeginAcquisition()
        camera_task.start()
        start = time.time()
        while time.time() - start < 5:
            print(type(camera.GetNextImage()))
        camera.EndAcquisition()


setup_camera('captured_frames')
