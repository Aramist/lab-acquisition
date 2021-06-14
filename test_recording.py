from functools import partial
from os import path
import time

import nidaqmx as nidaq
from nidaqmx.constants import READ_ALL_AVAILABLE
from nidaqmx.constants import AcquisitionType
import numpy as np
import tables


# Local constants
NUM_MICROPHONES = 2
SAMPLE_RATE = 125000  # kHz
READ_CYCLE_PERIOD = 0.5  # Amount of time (sec) between each read from the buffer
SAMPLE_INTERVAL = int(SAMPLE_RATE * READ_CYCLE_PERIOD)


class mic_data_writer():
    def __init__(self, length, filename_format_func, directory, identity_list, infinite=False):
        """Parameters:
            length: the length of each file, in minutes
            filename_format: a string used to determine the filename, with {} in
                place of the file's index (for long recordings)
            directory: the directory in which the files should be created
        """
        self.target_num_samples = int(length * 60 * SAMPLE_RATE)
        self.filename_generator = filename_format_func
        self.directory = directory
        self.identity_list = identity_list
        self.infinite = infinite
        self.file_counter = 0
        self.present_num_samples = 0
        self.current_file = None
        self.generate_new_file()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

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

        filepath = path.join(self.directory, self.filename_generator.format(self.file_counter))
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
        float_atom = tables.Float64Atom()
        self.tables_array = self.current_file.create_earray(
            self.current_file.root,
            'analog_input',
            float_atom,
            (NUM_MICROPHONES, 0),
            expectedrows=SAMPLE_INTERVAL)

        # Update necessary values
        self.file_counter += 1
        self.present_num_samples = 0


def read_callback(task_obj,
        data_writer, 
        task_handle, 
        every_n_samples_event_type, 
        number_of_samples, 
        callback_data):
    data = np.array(task_obj.read(
        number_of_samples_per_channel=READ_ALL_AVAILABLE,
        timeout=0))
    data_writer.write(data)
    return 0


with nidaq.Task() as task:
    name_list = [u'microphone_{}'.format(a) for a in range(NUM_MICROPHONES)]
    # The following line allows each file in the sequence to have its own start time in its name
    #fname_generator = lambda : f'mic_{time.time()}_{{}}.h5'
    
    # Create a voltage/microphone channel for every microphone
    task.ai_channels.add_ai_voltage_chan("dev1/ai1",
        name_to_assign_to_channel=name_list[0])
    task.ai_channels.add_ai_voltage_chan("dev1/ai2",
        name_to_assign_to_channel=name_list[1])
    
    # Configure the timing for this task
    # Samples per channel is set to 1 second's worth of samples to prevent
    # NI-DAQ from creating a really large buffer for the input
    task.timing.cfg_samp_clk_timing(
        rate=SAMPLE_RATE,
        sample_mode=AcquisitionType.CONTINUOUS,
        samps_per_chan=SAMPLE_RATE*5)
    # The *5 grants some extra space to the buffer to avoid a crash if the timing of the retrieval from the buffer is a bit off
    with mic_data_writer(30, f'mic_{time.time()}_{{}}.h5', 'mic_data', name_list) as data_writer:
        task.register_every_n_samples_acquired_into_buffer_event(
            sample_interval=SAMPLE_INTERVAL,
            callback_method=partial(read_callback, task, data_writer))

        task.start()

        # Prevent python from interpreting EOF - allows the data acquisition to run
        time.sleep(60 * 120)
        task.stop()
