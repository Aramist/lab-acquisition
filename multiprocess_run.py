import argparse
from collections import deque
from ctypes import c_bool, c_double
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


NUM_MICROPHONES = 2
DATA_DIR = 'acquired_data'


def camera_process(acq_enabled, acq_start_time, epoch_len, num_epochs, param_dict):
    cam = video_acquisition.FLIRCamera(**param_dict)

    while time.time() < acq_start_time.value or not acq_enabled.value:
        pass
    time.sleep(0.05)  # Allow the analog input enough time to start (40-50ms)
    for _ in range(num_epochs):
        start_time = time.time()
        cam.start_capture()
        try:
            while acq_enabled.value and cam.is_capturing and time.time() - start_time < epoch_len + 2:
                pass  # Give a 2 second grace period to avoid hanging the process at the end when the ctr stops
        except Exception as e:
            print(e)
            cam.end_capture()
            return 0
        cam.end_capture()
    cam.release()
    return 0


def create_cv_windows(window_names):
    for name in window_names:
        cv2.namedWindow(name, cv2.WINDOW_NORMAL)


def multi_epoch_demo(directory, filename, acq_enabled, acq_start_time, duration, epoch_len, cam_queues, framerate=30):
    camera_params = (
        {
            'root_directory': directory,
            'acq_enabled': acq_enabled,
            'camera_serial':  video_acquisition.FLIRCamera.CAMERA_A_SERIAL,
            'counter_port': u'Dev1/ctr1',
            'port_name': 'cam_a',
            'frame_target': epoch_len * framerate,
            'framerate': framerate,
            'period_extension': 0,
            'use_queue': cam_queues[0],
            'enforce_filename': filename
        },
        {
            'root_directory': directory,
            'acq_enabled': acq_enabled,
            'camera_serial':  video_acquisition.FLIRCamera.CAMERA_B_SERIAL,
            'counter_port': None,
            'port_name': 'cam_b',
            'frame_target': epoch_len * framerate,
            'framerate': framerate,
            'period_extension': 0,
            'use_queue': cam_queues[1],
            'enforce_filename': filename
        },
    )
    # Since objects can't be transported across processes, the camera objects have to be created independently in its own process
    camera_names = [p['port_name'] for p in camera_params]
    num_epochs = duration // epoch_len
    with Pool(processes=2) as pool:
        print('initializing cameras: {}'.format(str(camera_names)))
        pool.map(partial(camera_process, acq_enabled, acq_start_time, epoch_len, num_epochs), camera_params)
        print('Closing processes')
        pool.terminate()

    """All times are expected in seconds"""
    """
    num_epochs = duration // epoch_len
    for iteration in range(num_epochs):
        print(f'Starting epoch {iteration + 1}/{num_epochs}')
        run_cameras(directory, acq_enabled, epoch_len)
    """

"""
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
"""




def begin_acquisition(duration, epoch_len, dispenser_interval=None, suffix=None, spec_queue=None, send_sync=True):
    # First make the directory to hold all the data
    start_time_dt = datetime.datetime.now() + datetime.timedelta(seconds=10)
    script_start_time = start_time_dt.strftime('%Y_%m_%d_%H_%M_%S_%f')
    if suffix is not None:
        folder_name = '{}_{}'.format(script_start_time, suffix)
    else:
        folder_name = script_start_time
    subdir = path.join(DATA_DIR, folder_name)
    if not path.exists(subdir):
        os.mkdir(subdir)


    if dispenser_interval is not None:
        dio_ports = ('Dev1/port0/line7',)
        stop_dt = datetime.datetime.now() + datetime.timedelta(seconds=duration)
        feeder_proc = Process(target=scheduled_feeding.feed_regularly, args=(dio_ports, dispenser_interval, False, stop_dt))
        feeder_proc.start()

    with multiprocessing.Manager() as manager:
        acq_started = manager.Value(c_bool, False)
        acq_start_time = manager.Value(c_double, start_time_dt.timestamp())

        # mic_queue = None
        mic_queue = manager.Queue()
        mic_deque = deque(maxlen=40)
        # cam_queue = None
        cam_a_queue, cam_b_queue = None, manager.Queue()
        window_names = {
            # 'a': 'Camera A',
            'b': 'Camera B',
            'mic': 'Spectrogram (All mics averaged)'
        }

        create_cv_windows(window_names.values())

        ai_ports = [u'Dev1/ai{}'.format(i) for i in range(NUM_MICROPHONES)]
        ai_names = [u'microphone_{}'.format(a) for a in range(NUM_MICROPHONES)]
        mic_proc = Process(
                target=microphone_input.record,
                args=(subdir, script_start_time, acq_started, acq_start_time, ai_ports, ai_names, duration, epoch_len, mic_queue, u'Dev1/ai7', u'Dev1/ai6'))
        mic_proc.start()

        if send_sync:
            # Begin sending sync signal
            co_task = ni.Task()
            co_task.co_channels.add_co_pulse_chan_freq('Dev1/ctr0', 'counter0', freq=125000)
            #co_task.co_channels.add_co_pulse_chan_freq('Dev1/ctr0', 'counter0', freq=12206.5)
            co_task.timing.cfg_implicit_timing(sample_mode=constants.AcquisitionType.CONTINUOUS)
            co_task.start()


        # Commented out the camera thread here (Aramis, 2021-07-30, 14:12): 
        cam_thread = threading.Thread(target=multi_epoch_demo, args=(subdir, script_start_time, acq_started, acq_start_time, duration, epoch_len, (cam_a_queue, cam_b_queue)))
        cam_thread.start()

        print()
        print('Waiting for everything to initialize')
        acq_started.value = True

        while time.time() < start_time_dt.timestamp():
            pass

        def sigint_handler(sig, frame):
            print('Attempting to stop acquisition')
            acq_started.value = False
            time.sleep(1)
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, sigint_handler)


        # Constants for the spectrogram display
        TEMP_HIGH = 2e-9
        TEMP_LOW = 50e-11

        # if spec_queue is None:
        start = time.time()
        last_printed = 0
        try:
            # bar_format = 'Timer|{bar}|{elapsed}/{remaining}'
            bar_format = 'Timer|{elapsed}'
            #for i in tqdm.tqdm(range(duration*60), bar_format=bar_format):
            while time.time() - start < duration:
                # if time.time() - start > duration:
                #    break
                # Check for camera frame
                try:
                    image = cam_b_queue.get()
                    cv2.imshow(window_names['b'], image)
                    cv2.waitKey(1)
                except Empty:
                    pass
                except Exception as e:
                    print(e)

                # Check for microphone data and display it
                try:
                    mic_data = mic_queue.get(timeout=0)
                    #mic_deque.append(mic_data)
                    #data_arr = np.concatenate(list(mic_deque), axis=0)

                    # START CALCULATION TIME
                    # TODO: Delete
                    start_calc = time.time()
                    
                    f, t, spec = scipy.signal.spectrogram( \
                        mic_data,
                        fs=microphone_input.SAMPLE_RATE,
                        nfft=512,
                        noverlap=0,
                        nperseg=512,
                        scaling='density')

                    # crop to certain frequency
                    # idx = np.argmin(np.abs(f - 6000))
                    # spec = spec[:idx, :]
                    # Perform logarithmic scaling to accentuate the smaller signals
                    spec[spec < TEMP_LOW] = TEMP_LOW
                    spec[spec > TEMP_HIGH] = TEMP_HIGH
            
                    #spec = np.log(spec)
                    #maxspec, minspec = np.log(TEMP_HIGH), np.log(TEMP_LOW)
                    maxspec, minspec = TEMP_HIGH, TEMP_LOW
                    # maxspec, minspec = np.max(spec), np.min(spec)
                    # Perform the scaling and convert to int for image viewing
                    # The reversal of the 0 axis is necessary here because opencv uses matrix style indexing
                    # Although this might not need to be conserved after switching to d3
                    spec = ((spec - minspec) * 255 / (maxspec - minspec)).astype(np.uint8)[::-1, :]
                    mic_deque.append(spec)
                    complete_image = np.ascontiguousarray(np.concatenate(list(mic_deque), axis=1), dtype=np.uint8)

                    # TODO: delete
                    stop_calc = time.time()
                    duration_text = '{:.2f}ms'.format(1000 * (stop_calc - start_calc))
                    
                    cv2.putText(
                        complete_image,
                        duration_text,
                        (50, 50),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        255,
                        1
                    )
                    cv2.imshow(window_names['mic'], complete_image)
                    cv2.waitKey(1)
                except Empty:
                    pass
                except Exception as e:
                    print(e)

                # Doesn't really need to sleep because processing the frames for the display takes so much time
                # time.sleep(1/60)
                elapsed = int(time.time() - start)
                if elapsed >= last_printed + 5:
                    print('Timer: {}:{:>02}'.format(elapsed // 60, elapsed % 60))  # Minutes and seconds
                    last_printed = elapsed
        except KeyboardInterrupt:
            pass
        
        try:
            # Attempt to allow the last bits of data to be written
            time.sleep(0.5)
            acq_started.value = False
        except Exception:
            pass
    cv2.destroyAllWindows()
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
    parser.add_argument('epoch_len', help='How long each epoch of data acquisition should be (in minutes)', type=float)
    parser.add_argument('--dispenserinterval', help='How often the dispensers should be activated (in minutes)', type=int)
    parser.add_argument('--suffix', help='A suffix for the names of the files produced in this session', type=str)
    args = parser.parse_args()

    duration = int(60 * args.duration)
    epoch_len = int(60 * args.epoch_len)
    if args.dispenserinterval:
        dispenser_interval = args.dispenserinterval * 60
    else:
        dispenser_interval = None  # Don't run the dispenser

    if args.suffix:
        suffix = args.suffix
    else:
        suffix = None

    begin_acquisition(duration, epoch_len, dispenser_interval, suffix)


if __name__ == '__main__':
    command_line_demo()
