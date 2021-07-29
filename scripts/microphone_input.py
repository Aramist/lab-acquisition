from collections import deque
import datetime
from functools import partial
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


# Local constants
SAMPLE_RATE = 125000  # Hz
READ_CYCLE_PERIOD = 0.5  # Amount of time (sec) between each read from the buffer
SAMPLE_INTERVAL = int(SAMPLE_RATE * READ_CYCLE_PERIOD)


class mic_data_writer():
    def __init__(self, length, num_microphones, filename_format_func, directory, identity_list, infinite=False, sample_rate=SAMPLE_RATE):
        """Parameters:
            length: the length of each file, in minutes
            filename_format: a string used to determine the filename, with {} in
                place of the file's index (for long recordings)
            directory: the directory in which the files should be created
        """
        # TODO: Change filename format, re-add filename format function
        self.target_num_samples = int(length * 60 * sample_rate)
        self.num_microphones = num_microphones
        self.filename_generator = filename_format_func
        self.directory = directory
        self.identity_list = identity_list
        self.infinite = infinite
        self.file_counter = 0
        self.present_num_samples = 0
        self.ephys_trigger_sample = 0
        self.saved_trigger = False
        self.current_file = None
        self.generate_new_file()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def increment_ephys_trigger(self, n):
        self.ephys_trigger_sample += n

    def save_ephys_trigger_sample(self):
        if self.saved_trigger:
            return
        self.saved_trigger = True
        self.tables_array.attrs.ephys_trigger_sample_no = self.ephys_trigger_sample

    def close(self):
        if self.current_file is not None:
            self.current_file.close()

    def write(self, data):
        self.tables_array.append(data)

        # Allaw for the option to grow the hdf file until the program halts
        if not self.infinite:
            self.present_num_samples += data.shape[1]
        if self.present_num_samples > self.target_num_samples:
            self.generate_new_file()

    def generate_new_file(self):
        # None check to prevent errors on creation of the very first file
        if self.current_file is not None:
            self.current_file.close()

        if not path.exists(self.directory):
        	os.mkdir(self.directory)

        filepath = path.join(self.directory, self.filename_generator().format(self.file_counter))
        self.current_file = tables.open_file(filepath, 'w')
        # Create a small array logging the microphones used in this reading:
        """
        string_atom = tables.StringAtom(itemsize=32)
        identifiers = self.current_file.create_array(
            self.current_file.root,
            'microphones_used',
            string_atom,
            (2,))
        identifiers[:] = self.identity_list
        """

        # Create an expandable array for analog input
        float_atom = tables.Float32Atom()
        self.tables_array = self.current_file.create_earray(
            self.current_file.root,
            'analog_input',
            float_atom,
            (self.num_microphones, 0),
            expectedrows=SAMPLE_INTERVAL)

        # Update necessary values
        self.file_counter += 1
        self.present_num_samples = 0


def read_callback(task_obj,
        data_writer,
        fft_queue,
        task_handle,
        every_n_samples_event_type,
        number_of_samples,
        callback_data):
    data = np.array(task_obj.read(
        number_of_samples_per_channel=READ_ALL_AVAILABLE,
        timeout=0)).reshape((data_writer.num_microphones + 1, -1))  # + 1 to account for the ttl input channel
    if np.max(data, axis=1)[-1] > 3:
        # The ttl trigger was hit
        trigger_location = np.argmax(data, axis=1)[-1]
        data_writer.increment_ephys_trigger(trigger_location)
        data_writer.save_ephys_trigger_sample()
    else:
        data_writer.increment_ephys_trigger(data.shape[1])
    data_writer.write(data[:-1,:])  # Exclude the channel used for trigger detection
    if fft_queue is not None:
        try:
            fft_queue.put(data, False)
        except Exception:
            pass
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


def record(directory, acq_started, port_list, name_list, duration, fft_queue, hsw_ttl_port):  # TODO: Add parameters to this function (microphone channels, sample rate and other constants, file length)
    task = nidaq.Task()
    # The following line allows each file in the sequence to have its own start time in its name
    fname_generator = lambda : 'mic_{}.h5'.format(datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S_%f'))
    
    # Create a voltage/microphone channel for every microphone
    for port, name in zip(port_list, name_list):
        task.ai_channels.add_ai_voltage_chan(port,
            name_to_assign_to_channel=name)
    # One for the ttl port as well
    task.ai_channels.add_ai_voltage_chan(hsw_ttl_port, 'hsw_ttl_input')
    
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
    data_writer = mic_data_writer(30, len(port_list), fname_generator, directory, name_list)
    task.register_every_n_samples_acquired_into_buffer_event(
        sample_interval=SAMPLE_INTERVAL,
        callback_method=partial(read_callback, task, data_writer, non_mp_queue))

    while not acq_started.value:
        pass  # Wait for everything else to be ready
    task.start()

    start_time = time.time()
    try:
        while acq_started.value:
            try:
                if non_mp_queue is not None and fft_queue is not None:
                    data = non_mp_queue.get(True, 0.2)
                    fft_queue.put(data)
            except queue.Empty:
                continue
            except KeyboardInterrupt:
                break
    except KeyboardInterrupt:
        print('Microphone_input: attempting to close task')


    task.stop()
    data_writer.close()
    task.close()


if __name__ == '__main__':
    record('mic_data', [u'Dev1/ai0'], [u'mic0'], (60000 // 200) + 30, None, u'Dev1/ai2')
