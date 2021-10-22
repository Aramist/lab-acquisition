from collections import deque
import datetime
from functools import partial
import json
import os
from os import path
from multiprocessing import Process
import queue
import time

import nidaqmx as nidaq
from nidaqmx.constants import READ_ALL_AVAILABLE
from nidaqmx.constants import AcquisitionType
import numpy as np
import tables

from scripts.config import constants


# Local constants
SAMPLE_RATE = constants['microphone_sample_rate']  # Hz
READ_CYCLE_PERIOD = constants['microphone_data_retrieval_interval']  # Amount of time (sec) between each read from the buffer
SAMPLE_INTERVAL = int(SAMPLE_RATE * READ_CYCLE_PERIOD)


class mic_data_writer():
    def __init__(self, total_length, epoch_length, num_microphones, directory, identity_list, infinite=False, sample_rate=SAMPLE_RATE, enforced_filename=None):
        """Parameters:
            length: the length of each file, in minutes
            filename_format: a string used to determine the filename, with {} in
                place of the file's index (for long recordings)
            directory: the directory in which the files should be created
        """
        # TODO: Change filename format, re-add filename format function
        self.target_num_samples = int(epoch_length * 60 * sample_rate)
        self.total_num_samples = int(total_length * 60 * sample_rate)

        self.num_microphones = num_microphones
        
        self.directory = directory
        self.enforced_filename = enforced_filename
        self.array_labels = identity_list
        
        self.infinite = infinite
        self.file_counter = 0
        self.present_num_samples = 0
        self.no_epoch_num_samples = 0
        
        self.ephys_rising_edge = 0
        self.saved_rising = False
        self.ephys_falling_edge = 0
        self.saved_falling = False
        
        self.cam_accumulator = 0
        self.temp_rising = None
        
        self.current_file = None
        self.generate_new_file()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def increment_ephys_trigger(self, n, rising=True):
        if rising:
            self.ephys_rising_edge += n
        else:
            self.ephys_falling_edge += n

    def increment_cam_accumulator(self, n):
        self.cam_accumulator += n

    def save_ephys_trigger_sample(self, rising=True):
        if rising:
            if self.saved_rising:
                return
            self.saved_rising = True
            self.trig_array.append(np.array([self.ephys_rising_edge], dtype=int))
            # self.tables_array.attrs.ephys_trigger_rising_edge = self.ephys_rising_edge
        else:
            if self.saved_falling:
                return
            self.saved_falling = True
            # self.tables_array.attrs.ephys_trigger_falling_edge = self.ephys_falling_edge

    def close(self):
        if self.current_file is not None:
            self.current_file.close()

    def write(self, data):
        if self.arrays is None:
            return

        remainder = None
        if self.present_num_samples + data.shape[1] > self.target_num_samples:
            to_add = self.target_num_samples - self.present_num_samples
            for i in range(data.shape[0]):
                self.arrays[i].append(data[i, :to_add])
            remainder = data[:, to_add:]
            if not self.infinite:
                self.present_num_samples = self.target_num_samples
                self.no_epoch_num_samples += to_add
        else:
            for i in range(data.shape[0]):
                self.arrays[i].append(data[i])
            if not self.infinite:
                self.present_num_samples += data.shape[1]
                self.no_epoch_num_samples += data.shape[1]

        # Allaw for the option to grow the hdf file until the program halts
        if self.present_num_samples >= self.target_num_samples:
            self.generate_new_file()
        
        if remainder is not None:
            self.write(remainder)

    def write_pulses(self, data):
        if self.cam_array is not None:
            self.cam_array.append(data)

    def write_audio_pulses(self, data):
        if self.audio_array is not None:
            self.audio_array.append(data)
        print(data)

    def generate_new_file(self):
        # None check to prevent errors on creation of the very first file
        if self.current_file is not None:
            self.current_file.close()

        if self.no_epoch_num_samples >= self.total_num_samples:
            self.current_file = None
            self.arrays = None
            self.cam_array = None
            return

        if not path.exists(self.directory):
        	os.mkdir(self.directory)

        if self.enforced_filename is None:
            filepath = path.join(self.directory, 'mic_{}.h5'.format(datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S_%f')))
        else:
            filepath = path.join(self.directory, 'mic_{}.h5'.format(self.enforced_filename))
            self.enforced_filename = None

        self.current_file = tables.open_file(filepath, 'w')

        # Create the analog_channels group to keep everything organized
        ai_group = self.current_file.create_group(self.current_file.root, 'ai_channels')
        # NEW (2021-09-21): dump the config dictionary into an attribute of the table
        self.current_file.create_array(
            '/',
            'config',
            np.array(json.dumps({k: v for k, v in constants.items() if 'color' not in k})))

        # Create an expandable array for analog input
        float_atom = tables.Float32Atom()
        self.arrays = list()
        for channel_name in self.array_labels:
            # Arrays are added here in the order in which they appear in port_list, which is also the order in which they are created,
            # Which means the data received will also be in this order
            self.arrays.append(
                self.current_file.create_earray(
                    ai_group,
                    channel_name,
                    float_atom,
                    (0,),
                    expectedrows=self.target_num_samples))


        int_atom = tables.Int32Atom()
        self.cam_array = self.current_file.create_earray(
            self.current_file.root,
            'camera_frames',
            int_atom,
            (0,),
            expectedrows=self.target_num_samples // 125000 * 30)

        self.trig_array = self.current_file.create_earray(
            self.current_file.root,
            'ephys_trigger',
            int_atom,
            (0,),
            expectedrows=2
        )

        self.audio_array = self.current_file.create_earray(
            self.current_file.root,
            'audio_onset',
            int_atom,
            (0, 2),  # Saves the falling edge and the length of the pulse in ms
            expectedrows=30
        )

        # Update necessary values
        self.file_counter += 1
        self.present_num_samples = 0



def record_data(task_obj, data_writer, fft_queue):
    data = np.array(task_obj.read(
        number_of_samples_per_channel=READ_ALL_AVAILABLE,
        timeout=0)).reshape((data_writer.num_microphones + 3, -1))  # +3 for all of the ttl-reading channels
    trigger_location = 0
    if np.max(data[-1]) > 3 and not data_writer.saved_rising:
        # The ttl trigger was hit
        trigger_location = np.argmax(np.diff(data[-1]))
        # The falling edge must lie beyond the rising edge
        data_writer.increment_ephys_trigger(data_writer.ephys_rising_edge, rising=False)
        data_writer.increment_ephys_trigger(trigger_location, rising=True)
        data_writer.save_ephys_trigger_sample(rising=True)
        # See if the falling edge occured in the same block of data
        if np.min(data[-1, trigger_location:]) < 3:
            loc = np.argmin(np.diff(data[-1]))
            data_writer.increment_ephys_trigger(loc, rising=False)
            data_writer.save_ephys_trigger_sample(rising=False)
        else:
            data_writer.increment_ephys_trigger(data.shape[1], rising=False)
    else:
        data_writer.increment_ephys_trigger(data.shape[1], rising=True)
    # See if the falling edge occured in a different block
    if data_writer.saved_rising and not data_writer.saved_falling:
        if np.min(data[-1]) < 3:
            loc =  np.argmin(np.diff(data[-1]))
            data_writer.increment_ephys_trigger(loc, rising=False)
            data_writer.save_ephys_trigger_sample(rising=False)
        else:
            data_writer.increment_ephys_trigger(data.shape[1], rising=False)

    # Camera rising edge stuff
    cam_rising = np.flatnonzero((data[-2,1:] > 1) & (data[-2,:-1] < 1)) + 1 + data_writer.cam_accumulator
    if len(cam_rising) > 0:
        data_writer.write_pulses(cam_rising)

    
    # Audio rising and falling edge stuff
    audio_rising = np.flatnonzero((data[-3, :-1] < 2) & (data[-3, 1:] > 2)) + data_writer.cam_accumulator
    audio_falling = np.flatnonzero((data[-3, :-1] > 2) & (data[-3, 1:] < 2)) + data_writer.cam_accumulator

    if data_writer.temp_rising is not None:
        audio_rising = np.insert(audio_rising, 0, data_writer.temp_rising)
        data_writer.temp_rising = None

    # Check for edge cases
    # Case 1: the rising edge is cut off and there is no temp rising, so n_falling > n_rising
    if len(audio_falling) > len(audio_rising):
        audio_falling = audio_falling[1:]
    # Case 2: the falling edge is cut off, so it appears in the next frame and  n_rising > n_falling
    elif len(audio_rising) > len(audio_falling):
        data_writer.temp_rising = audio_rising[-1]
        audio_rising = audio_rising[:-1]
    else:
    # Case 3: the wave is fully contained in this block, wipe the rising edge
        data_writer.temp_rising = None
    
    if len(audio_rising) == len(audio_falling) and len(audio_rising) > 0:
        np_pulses = np.array([[falling, (falling - rising) * 1000 // SAMPLE_RATE] for rising, falling in zip(audio_rising, audio_falling)], dtype=int)
        data_writer.write_audio_pulses(np_pulses)
    
    data_writer.increment_cam_accumulator(data.shape[1])
    data_writer.write(data[:data_writer.num_microphones])
    if fft_queue is not None:
        try:
            # Ensure the input has more than one dimension so the output doesn't end up scalar
            fft_queue.put(np.reshape(data[:data_writer.num_microphones], (data_writer.num_microphones, -1)), False)
        except Exception:
            pass


def read_callback(task_obj,
        data_writer,
        fft_queue,
        task_handle,
        every_n_samples_event_type,
        number_of_samples,
        callback_data):
    record_data(task_obj, data_writer, fft_queue)
    return 0


class MicrophoneRecorder:
    def __init__(self, channels_in_use, microphone_labels, sampling_rate, data_write_frequency, file_length_minutes):
        self.sampling_rate = sampling_rate
        self.read_cycle_period = data_write_frequency
        self.sample_interval = data_write_frequency * sampling_rate
        self.names = microphone_labels
        self.ports = [u'Dev1/ai{}'.format(channel) for channel in channels_in_use]
        self.init_task()

    def init_task(self):
        self.microphone_task = nidaq.Task()

    def __enter__(self):
        return self.microphone_task

    def __exit__(self, type, value, traceback):
        self.microphone_task.close()


def record(directory, filename, acq_started, acq_start_time, port_list, name_list, duration, epoch_len, fft_queue, audio_ttl_port, cam_ttl_port, hsw_ttl_port):
    task = nidaq.Task()
    # The following line allows each file in the sequence to have its own start time in its name
    # fname_generator = lambda : 'mic_{}.h5'.format(datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S_%f'))
    # fname_generator = lambda : 'mic_{}.h5'.format(filename)

    # Create a voltage/microphone channel for every microphone
    for port, name in zip(port_list, name_list):
        task.ai_channels.add_ai_voltage_chan(port,
            name_to_assign_to_channel=name)

    # Hold the -3 index for audio ttl signals
    task.ai_channels.add_ai_voltage_chan(audio_ttl_port, 'audio_ttl_port')
    # One for the cameras, will hold the -2 index
    task.ai_channels.add_ai_voltage_chan(cam_ttl_port, 'cam_ttl_port')
    # One for the ttl port as well
    task.ai_channels.add_ai_voltage_chan(hsw_ttl_port, 'hsw_ttl_port')
    
    
    # Configure the timing for this task
    # Samples per channel is set to only 5 second's worth of samples to prevent
    # NI-DAQ from creating a really large buffer for the input
    task.timing.cfg_samp_clk_timing(
        rate=SAMPLE_RATE,
        sample_mode=AcquisitionType.CONTINUOUS,
        samps_per_chan=SAMPLE_RATE*5)

    """So there is this really strange bug in nidaqmx where if you have a callback function bound to a task (like read_callback) and you attempt
    to use this callback function to append to a multiprocessing queue (standand thread-safe queues are exempt), the process will never join 
    and there will not be any sort of error message to indicate that the process is unresponsive."""
    # Getting around this by maintaining a separate queue within the process that is copied into the mp queue as it receives data
    non_mp_queue = None
    if fft_queue is not None:
        non_mp_queue = queue.Queue()


    # The *5 grants some extra space to the buffer to avoid a crash if the timing of the retrieval from the buffer is a bit off
    channel_labels = [a.split('/')[1] for a in port_list]  # Should return something like ['ai0', 'ai1', 'ai2', ...]
    data_writer = mic_data_writer(duration // 60, epoch_len // 60, len(port_list), directory, channel_labels, enforced_filename=filename)
    task.register_every_n_samples_acquired_into_buffer_event(
        sample_interval=SAMPLE_INTERVAL,
        callback_method=partial(read_callback, task, data_writer, non_mp_queue))

    try:
        while time.time() < acq_start_time.value or not acq_started.value:
            pass  # Wait for everything else to be ready
    except Exception:
        return  # The program was closed before the value changed
    task.start()

    start_time = time.time()
    try:
        while acq_started.value and time.time() - start_time < duration:
            try:
                if non_mp_queue is not None and fft_queue is not None:
                    data = non_mp_queue.get(timeout=0)
                    fft_queue.put(data)
            except queue.Empty:
                continue


    except KeyboardInterrupt:
        print('Microphone_input: attempting to close task')
    
    time.sleep(1)

    task.stop()
    data_writer.close()
    task.close()