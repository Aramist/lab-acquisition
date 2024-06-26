import argparse
from collections import deque
from ctypes import c_bool, c_double
import datetime
from functools import partial
import json
from math import ceil
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
from scripts.config import constants as config


NUM_MICROPHONES = config['num_microphones']
DATA_DIR = config['data_directory']


def camera_process(acq_enabled, acq_start_time, duration, epoch_len, num_epochs, param_dict):
    cam = video_acquisition.FLIRCamera(**param_dict)

    while time.time() < acq_start_time.value or not acq_enabled.value:
        pass
    # time.sleep(0.05)  # Allow the analog input enough time to start (40-50ms)
    cam.start_epoch()
    try:
        while acq_enabled.value and cam.is_capturing:  # and time.time() - start_time < epoch_len + 1:
            pass  # Give a 2 second grace period to avoid hanging the process at the end when the ctr stops
    except Exception as e:
        print(e)
        cam.end_epoch()
        return 0
    time.sleep(0.5)
    cam.release()
    return 0


def create_cv_windows(window_names):
    for name in window_names:
        cv2.namedWindow(name, cv2.WINDOW_NORMAL)


def multi_epoch_demo(directory, filename, acq_enabled, acq_start_time, duration, epoch_len, cam_queues, framerate=30):
    a_enabled, b_enabled, c_enabled = config['cam_a_enabled'], config['cam_b_enabled'], config['cam_c_enabled']
    cam_port = config['camera_ctr_port']
    num_epochs = ceil(duration / epoch_len)
    camera_params = [
        {
            'root_directory': directory,
            'acq_enabled': acq_enabled,
            'camera_serial':  config['camera_a_serial'],
            'counter_port': cam_port,  # Ensure that the port only belongs to one camera object
            'port_name': 'cam_a',
            'frame_target': epoch_len * framerate,
            'epoch_target': num_epochs,
            'framerate': framerate,
            'period_extension': 0,
            'calibration_param_path': config['cam_a_calibration_path'],
            'use_queue': cam_queues[0],
            'enforce_filename': filename
        },
        {
            'root_directory': directory,
            'acq_enabled': acq_enabled,
            'camera_serial':  config['camera_b_serial'],
            'counter_port': None,
            'port_name': 'cam_b',
            'frame_target': epoch_len * framerate,
            'epoch_target': num_epochs,
            'framerate': framerate,
            'period_extension': 0,
            'calibration_param_path': config['cam_b_calibration_path'],
            'use_queue': cam_queues[1],
            'enforce_filename': filename
        },
        {
            'root_directory': directory,
            'acq_enabled': acq_enabled,
            'camera_serial':  config['camera_c_serial'],
            'counter_port': None,
            'port_name': 'cam_c',
            'frame_target': epoch_len * framerate,
            'epoch_target': num_epochs,
            'framerate': framerate,
            'period_extension': 0,
            'calibration_param_path': config['cam_c_calibration_path'],
            'use_queue': cam_queues[2],
            'enforce_filename': filename
        },
    ]

    # Filter out the disabled cameras
    camera_params = [bound[0] for bound in zip(camera_params, (a_enabled, b_enabled, c_enabled)) if bound[1]]
    if not camera_params:
        return  # In this case, both cameras are disabled

    # Since objects can't be transported across processes, the camera objects have to be created independently in its own process
    camera_names = [p['port_name'] for p in camera_params]
    
    print('initializing cameras: {}'.format(str(camera_names)))
    camera_processes = list()
    for camera_configuration in camera_params:
        camera_proc = Process(
            target=camera_process,
            args=(acq_enabled, acq_start_time, duration, epoch_len, num_epochs, camera_configuration))
        camera_proc.daemon = True
        camera_processes.append(camera_proc)
        camera_proc.start()
    return camera_processes


def calc_spec_frame_segment_mono(all_audio):
    avg_audio = np.mean(all_audio, axis=0)

    _, _, spec = scipy.signal.spectrogram(
        avg_audio,
        fs=config['microphone_sample_rate'],
        nfft=config['spectrogram_nfft'],
        noverlap=config['spectrogram_noverlap'],
        nperseg=config['spectrogram_nfft']
    )

    minavg, maxavg = config['spectrogram_lower_cutoff'], config['spectrogram_upper_cutoff']

    spec = np.clip(spec, minavg, maxavg)
    spec = (spec - minavg) * 255 / (maxavg - minavg)
    return spec[::-1].astype(np.uint8)



def calc_spec_frame_segment_color(left_audio, right_audio, diff_scaling_factor=1):
    _, _, lspec = scipy.signal.spectrogram(
        left_audio,
        fs=config['microphone_sample_rate'],
        nfft=config['spectrogram_nfft'],
        noverlap=config['spectrogram_noverlap'],
        nperseg=config['spectrogram_nfft']
    )

    _, _, rspec = scipy.signal.spectrogram(
        right_audio,
        fs=config['microphone_sample_rate'],
        nfft=config['spectrogram_nfft'],
        noverlap=config['spectrogram_noverlap'],
        nperseg=config['spectrogram_nfft']
    )

    # TEMPORARY: Account for the inflated readings from the right microphone
    rspec *= config['spectrogram_rmic_correction_factor']

    black_color = config['spectrogram_black_color']
    white_color = config['spectrogram_white_color']
    red_color = config['spectrogram_red_color']
    blue_color = config['spectrogram_blue_color']

    # Compute 2 separate images:
    # One containing the average (for maintaining the baseline in the case where the signals are equally powerful on both sides)
    # One containing the difference (for modifying the previous image to reflect the difference in recorded power)
    # Add a new axis to both to allow them to be broadcast with the color vectors effeciently
    # Here, subtracting left from right means positive value of diff -> more power on the right side -> more blue color
    avg = ((rspec + lspec) / 2)[:, :, np.newaxis]
    diff = ((rspec - lspec) * diff_scaling_factor)[:, :, np.newaxis]

    minavg, maxavg = config['spectrogram_lower_cutoff'], config['spectrogram_upper_cutoff']
    # This is more arbitrary: the minimum power difference between the two mics for the signals to be differentiated between the two
    diff_inner_thresh = config['spectrogram_mic_difference_thresh']
    
    # Truncate the average and diff arrays with these value to prevent the final image from underflowing or overflowing
    avg[avg > maxavg] = maxavg
    avg[avg < minavg] = minavg

    # minavg doesn't work in the same way for diff because it spans the negative numbers. avg is originally non-negative
    diff[diff < -maxavg] = -maxavg
    diff[diff > maxavg] = maxavg
    diff[(diff < diff_inner_thresh) & (diff > -diff_inner_thresh)] = 0
    diff[avg < minavg] = 0


    # Interpolate avg between black and white
    # Original range: minavg, maxavg
    # New range: black_color, white_color
    # While it is redundant to subtract and add black_color here, it's useful to keep it, just in case the color changes in the future
    avg_img = (avg - minavg) * (white_color - black_color) / (maxavg - minavg) + black_color
    del avg

    # Next in interpolating the locations with positive diff between their present color and blue_color
    # The strength of the diff at that point will be used as the point of evaluation for the linear transform

    # First scale diff to -1,1 for convenience
    diff /= (maxavg * diff_scaling_factor)

    # Remove the new axis on the mask so it can be applied to avg_img
    # I thought it would be fine to just not add the new axis to diff in the first place but doing that broke something
    positive_mask = (diff > 0).reshape(diff.shape[:2])

    # Blue first
    # Original range: scaled_inner_thresh, 1
    # New range: present color, blue_color
    # Note: while the true range of diff is -1, 1, this operation is only performed on the positive values of diff, so it is effectively ", 1
    avg_img[positive_mask] = diff[positive_mask] * (blue_color - avg_img[positive_mask]) + avg_img[positive_mask]

    # Now red
    # Original range: -1, -scaled_inner_thresh
    # New range: present color, red_color
    # Note: I'm not exactly sure why the negative is needed in on diff here, maybe the new range should be reversed? In any case, it makes it work properly
    avg_img[~positive_mask] = -diff[~positive_mask] * (red_color - avg_img[~positive_mask]) + avg_img[~positive_mask]

    # Finally, reverse the 0 axis because opencv uses a different system of indexing images than scipy
    # In opencv, image[0] corresponds to the top row of the image, just like a matrix in math
    # No need to typecast to uint8 here because it gets done at the ascontiguousarray step
    return avg_img[::-1]


def begin_acquisition(duration, epoch_len, dispenser_interval=None, suffix=None, spec_queue=None, send_sync=True):
    spectrogram_colored = False
    device_name = config['device_name']
    # First make the directory to hold all the data
    secs = config['cam_setup_time']
    start_time_dt = datetime.datetime.now() + datetime.timedelta(seconds=secs)
    # n seconds between running multiprocess_run and acquisition starting. Gives everything time to setup
    print('Acquisition beginning in {} seconds.'.format(secs))
    script_start_time = start_time_dt.strftime('%Y_%m_%d_%H_%M_%S_%f')
    if suffix is not None:
        folder_name = '{}_{}'.format(script_start_time, suffix)
    else:
        folder_name = script_start_time
    subdir = path.join(DATA_DIR, folder_name)
    if not path.exists(subdir):
        os.mkdir(subdir)

    if dispenser_interval is not None:
        dio_ports = ('{}/port0/line7'.format(device_name),)
        stop_dt = datetime.datetime.now() + datetime.timedelta(seconds=duration)
        feeder_proc = Process(target=scheduled_feeding.feed_regularly, args=(dio_ports, dispenser_interval, False, stop_dt))
        feeder_proc.start()

    with multiprocessing.Manager() as manager:
        
        acq_started = manager.Value(c_bool, False)
        acq_start_time = manager.Value(c_double, start_time_dt.timestamp())

        # mic_queue = None
        mic_queue = manager.Queue() if config['spectrogram_display_enabled'] else None
        mic_deque = deque(maxlen=config['spectrogram_deque_size'])
        # cam_queue = None
        cam_a_queue = manager.Queue() if config['cam_a_enabled'] and config['cam_a_display_enabled'] else None
        cam_b_queue = manager.Queue() if config['cam_b_enabled'] and config['cam_b_display_enabled'] else None
        cam_c_queue = manager.Queue() if config['cam_c_enabled'] and config['cam_c_display_enabled'] else None
        window_names = {
            'a': config['cam_a_window_name'],
            'b': config['cam_b_window_name'],
            'c': config['cam_c_window_name'],
            'mic': config['spectrogram_window_name']
        }

        # Don't show windows that are disabled in config:
        if not config['cam_a_display_enabled']:
            del window_names['a']
        if not config['cam_b_display_enabled']:
            del window_names['b']
        if not config['cam_c_display_enabled']:
            del window_names['c']
        if not config['spectrogram_display_enabled']:
            del window_names['mic']

        create_cv_windows(window_names.values())
        
        # Starts the camera child-processes
        camera_processes = multi_epoch_demo(
            subdir,
            script_start_time,
            acq_started,
            acq_start_time,
            duration,
            epoch_len,
            (cam_a_queue, cam_b_queue, cam_c_queue),
            config['camera_framerate'])
        

        ai_ports = [u'{}/ai{}'.format(device_name, i) for i in range(NUM_MICROPHONES)]
        ai_names = [u'microphone_{}'.format(a) for a in range(NUM_MICROPHONES)]
        mic_proc = Process(
                target=microphone_input.record,
                args=(subdir,
                    script_start_time,
                    acq_started,
                    acq_start_time,
                    ai_ports,
                    ai_names,
                    duration,
                    epoch_len,
                    mic_queue,
                    config['audio_ttl_ai_port'],
                    config['cam_output_signal_ai_port'],
                    config['wm_trig_ai_port']))
        mic_proc.daemon = True
        mic_proc.start()

        if send_sync:
            # Begin sending sync signal
            co_task = ni.Task()
            co_task.co_channels.add_co_pulse_chan_freq(config['wm_sync_signal_port'], 'wm_sync', freq=config['wm_sync_signal_frequency'])
            #co_task.co_channels.add_co_pulse_chan_freq('Dev1/ctr0', 'counter0', freq=12206.5)
            co_task.timing.cfg_implicit_timing(sample_mode=constants.AcquisitionType.CONTINUOUS)
            co_task.start()

        print()
        print('Waiting for everything to initialize')
        acq_started.value = True


        def sigint_handler(sig, frame):
            print('Attempting to stop acquisition')
            try:
                acq_started.value = False
            except Exception:
                pass
            time.sleep(1)
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, sigint_handler)

        while time.time() < start_time_dt.timestamp():
            pass
        print('Beginning acquisition.')
        start = time.time()
        last_printed = 0
        try:
            while time.time() - start < duration:
                # Update timer
                elapsed = int(time.time() - start)
                hours = elapsed // 3600
                minutes = elapsed // 60 - 60 * hours
                seconds = elapsed % 60
                if hours > 0:
                    timer_string = 'Timer: {}:{:>02}:{:>02}'.format(hours, minutes, seconds)
                else:
                    timer_string = 'Timer: {}:{:>02}'.format(minutes, seconds)
                if elapsed >= last_printed + 5:
                    print(timer_string)
                    last_printed = elapsed

                # Check for camera frame
                if cam_a_queue is not None:
                    try:
                        image = cam_a_queue.get(timeout=0)
                        cv2.imshow(window_names['a'], image)
                        cv2.waitKey(1)
                    except Empty:
                        pass
                    except Exception as e:
                        print(e)

                if cam_b_queue is not None:
                    try:
                        image = cam_b_queue.get(timeout=0)
                        cv2.imshow(window_names['b'], image)
                        cv2.waitKey(1)
                    except Empty:
                        pass
                    except Exception as e:
                        print(e)
                if cam_c_queue is not None:
                    try:
                        image = cam_c_queue.get(timeout=0)
                        cv2.imshow(window_names['c'], image)
                        cv2.waitKey(1)
                    except Empty:
                        pass
                    except Exception as e:
                        print(e)

                # Check for microphone data and display it
                if config['spectrogram_display_enabled']:
                    try:
                        start_calc = time.time()
                        
                        mic_data = mic_queue.get(timeout=0)
                        if spectrogram_colored:
                            color_frame = calc_spec_frame_segment_color(mic_data[0], mic_data[1], diff_scaling_factor=2)
                        else:
                            color_frame = calc_spec_frame_segment_mono(mic_data)

                        mic_deque.append(color_frame)
                        complete_image = np.ascontiguousarray(np.concatenate(mic_deque, axis=1), dtype=np.uint8)
                        
                        '''
                        calc_duration = time.time() - start_calc
                        duration_text = '{:.2f}ms'.format(1000 * calc_duration)
                        cv2.putText(
                            complete_image,
                            duration_text,
                            (50, 50),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            1,
                            (255, 255, 255),
                            2
                        )'''

                        # Display timer on spectrogram window
                        text_color = (255, 255, 255) if spectrogram_colored else 255
                        cv2.putText(
                            complete_image,
                            timer_string,
                            (50, 50),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            1,
                            text_color,
                            2
                        )
                        cv2.imshow(window_names['mic'], complete_image)
                        cv2.waitKey(1)
                    except Empty:
                        pass
                    except Exception as e:
                        print(e)
                
        except KeyboardInterrupt:
            pass
        
        try:
            # Attempt to allow the last bits of data to be written
            time.sleep(0.5)
            acq_started.value = False
        except Exception:
            pass
    # Shutdown procedure:
    # Get rid of any cv windows
    cv2.destroyAllWindows()
    cv2.waitKey(1)
    # Wait for all processes to complete
    mic_proc.join()
    for cam_proc in camera_processes:
        cam_proc.join()
    if dispenser_interval is not None:
        feeder_proc.join()
    # Stop the sync signal
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

    if args.epoch_len > 30:
        print('Keep the epoch len below 30 minutes.')
        return

    duration = int(60 * args.duration)
    epoch_len = int(60 * args.epoch_len)
    if args.dispenserinterval:
        dispenser_interval = args.dispenserinterval * 60
    else:
        dispenser_interval = None  # Don't run the dispenser

    if args.suffix:
        suffix = args.suffix.strip('_')
    else:
        suffix = None

    begin_acquisition(duration, epoch_len, dispenser_interval, suffix)


if __name__ == '__main__':
    command_line_demo()
