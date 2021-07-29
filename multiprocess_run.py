import argparse
from collections import deque
from ctypes import c_bool
import datetime
from functools import partial
import multiprocessing
from multiprocessing import Pool, Process, Manager
import os
from os import path
from pprint import pprint
from queue import Empty
import signal
import threading
import time

import cv2
import nidaqmx as ni
from nidaqmx import constants
import numpy as np
import scipy.signal
import tqdm

from scripts import microphone_input, scheduled_feeding, video_acquisition


NUM_MICROPHONES = 4
DATA_DIR = 'acquired_data'


def run_camera(directory, acq_enabled, duration, serial, port, name, period_extension, framerate=30):
    cam = video_acquisition.FLIRCamera(directory,
            acq_enabled=acq_enabled,
            camera_serial=serial,
            period_extension=period_extension,
            port_name=name,
            counter_port=port,
            framerate=framerate)
    while not acq_enabled.value:
        pass
    cam.start_capture()
    start_time = time.time()
    while acq_enabled.value:
        pass
    cam.end_capture()


def run_cameras(directory, acq_enabled, duration):
    camera_serials = (video_acquisition.FLIRCamera.CAMERA_A_SERIAL, video_acquisition.FLIRCamera.CAMERA_B_SERIAL)
    camera_names = ('cam_a', 'cam_b')
    camera_ports = ('Dev1/ctr1', None)
    # The next term is camera specific and based on the mean error between each of the camera's frames' timestamps
    #camera_period_extension = (1.41661592e-7, 3.05238578e-7)
    camera_period_extension = (0, 0)
    camera_params = zip(camera_serials, camera_ports, camera_names, camera_period_extension)

    with Pool(processes=2) as pool:
        print('initializing cameras: {}'.format(str(camera_names)))
        pool.starmap(partial(run_camera, directory, acq_enabled, duration), camera_params)
        print('Closing processes')


def multi_epoch_demo(directory, acq_enabled, duration, epoch_len):
    """All times are expected in seconds"""
    num_epochs = duration // epoch_len
    for iteration in range(num_epochs):
        print(f'Starting epoch {iteration + 1}/{num_epochs}')
        run_cameras(directory, acq_enabled, epoch_len)


def spec_demo():
    mic_proc = Process(target=microphone_input.record, args=('mic_data', ai_ports, ai_names, DURATION, mic_data_queue, u'Dev1/ai3'))
    mic_proc.start()

    cv2.namedWindow('spec', cv2.WINDOW_AUTOSIZE)

    TEMP_HIGH = 2e-9
    TEMP_LOW = 60e-11

    print('Started mic process')

    start_time = time.time()
    mic_deque = deque(maxlen=20)  # 10 seconds' worth
    while time.time() - start_time < DURATION:
        try:
            mic_data = mic_data_queue.get(block=True, timeout=0.15)
        except Empty:
            continue
        if len(mic_deque) == 20:
            mic_deque.popleft()
        mic_deque.append(mic_data[0])
        if len(mic_deque) < 20:
            print(20 - len(mic_deque))
            # continue
        data_arr = np.concatenate(list(mic_deque), axis=0)
        f, t, spec = scipy.signal.spectrogram( \
            data_arr,
            fs=microphone_input.SAMPLE_RATE,
            nfft=1024,
            noverlap=256,
            nperseg=1024,
            scaling='density')
        # Perform logarithmic scaling to accentuate the smaller signals

        spec[spec < TEMP_LOW] = TEMP_LOW
        spec[spec > TEMP_HIGH] = TEMP_HIGH

        spec = np.log(spec)
        maxspec, minspec = np.log(TEMP_HIGH), np.log(TEMP_LOW)
        # maxspec, minspec = np.max(spec), np.min(spec)
        # Perform the scaling and convert to int for image viewing
        # The reversal of the 0 axis is necessary here because opencv uses matrix style indexing
        # Although this might not need to be conserved after switching to d3
        spec = ((spec - minspec) * 255 / (maxspec - minspec)).astype(np.uint8)[::-1, :]
        print(spec.shape)
        cv2.imshow('spec', spec)
        cv2.waitKey(1)
    mic_proc.join()
    mic_proc.close()


def begin_acquisition(duration, epoch_len, dispenser_interval=None, spec_queue=None, send_sync=True):
    # First make the directory to hold all the data
    subdir = path.join(
        DATA_DIR,
        datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S_%f'))
    if not path.exists(subdir):
        os.mkdir(subdir)


    if dispenser_interval is not None:
        dio_ports = ('Dev1/port0/line7',)
        stop_dt = datetime.datetime.now() + datetime.timedelta(seconds=duration)
        feeder_proc = Process(target=scheduled_feeding.feed_regularly, args=(dio_ports, dispenser_interval, False, stop_dt))
        feeder_proc.start()

    with multiprocessing.Manager() as manager:
        acq_started = manager.Value(c_bool, False)

        mic_queue = None
        # mic_queue = manager.Queue()
        ai_ports = [u'Dev1/ai{}'.format(i) for i in range(NUM_MICROPHONES)]
        ai_names = [u'microphone_{}'.format(a) for a in range(NUM_MICROPHONES)]
        mic_proc = Process(
                target=microphone_input.record,
                args=(subdir, acq_started, ai_ports, ai_names, duration, mic_queue, u'Dev1/ai7'))
        mic_proc.start()

        if send_sync:
            # Begin sending sync signal
            co_task = ni.Task()
            #co_task.co_channels.add_co_pulse_chan_freq('Dev1/ctr0', 'counter0', freq=12500)
            co_task.co_channels.add_co_pulse_chan_freq('Dev1/ctr0', 'counter0', freq=12206.5)
            co_task.timing.cfg_implicit_timing(sample_mode=constants.AcquisitionType.CONTINUOUS)
            co_task.start()

        cam_thread = threading.Thread(target=multi_epoch_demo, args=(subdir, acq_started, duration, epoch_len))
        cam_thread.start()

        print()
        print('Waiting for everything to initialize')
        time.sleep(5)
        print('Starting acquisition')
        acq_started.value = True

        def sigint_handler(sig, frame):
            print('Attempting to stop acquisition')
            acq_started.value = False
            time.sleep(1)
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, sigint_handler)

        # if spec_queue is None:
        # start = time.time()
        try:
            bar_format = 'Timer|{bar}|{elapsed}/{remaining}'
            for i in tqdm.tqdm(range(duration), bar_format=bar_format):
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        """
        else:
            # Use the downtime to handle all the queue data handling
            start_time = time.time()
            mic_deque = deque(maxlen=20)  # 10 seconds' worth
            while time.time() - start_time < duration:
                try:
                    mic_data = mic_queue.get(block=True, timeout=0.15)
                except Empty:
                    continue
                if len(mic_deque) == 20:
                    mic_deque.popleft()
                mic_deque.append(mic_data[0])
                data_arr = np.concatenate(list(mic_deque), axis=0)
                f, t, spec = signal.spectrogram( \
                    data_arr,
                    fs=microphone_input.SAMPLE_RATE,
                    nfft=1024,
                    noverlap=256,
                    nperseg=1024,
                    scaling='density')
                spec_queue.put((f,t,spec))"""
        try:
            acq_started.value = False
        except Exception:
            pass
    mic_proc.join()
    if dispenser_interval is not None:
        feeder_proc.join()
    if send_sync:
        co_task.stop()
        co_task.close()
    print('Done, {}'.format(str(datetime.datetime.now())))
    print('Closing remaining processes...')
    mic_proc.close()
    if dispenser_interval is not None:
        feeder_proc.close()


def command_line_demo():
    parser = argparse.ArgumentParser()
    parser.add_argument('duration', help='How long the script should run (in minutes)', type=float)
    parser.add_argument('epoch_len', help='How long each epoch of data acquisition should be (in minutes)', type=int)
    parser.add_argument('--dispenserinterval', help='How often the dispensers should be activated (in minutes)', type=int)
    args = parser.parse_args()

    duration = int(60 * args.duration)
    epoch_len = int(60 * args.epoch_len)
    if args.dispenserinterval:
        dispenser_interval = args.dispenserinterval * 60
    else:
        dispenser_interval = None  # Don't run the dispenser

    begin_acquisition(duration, epoch_len, dispenser_interval)


if __name__ == '__main__':
    command_line_demo()
