import argparse
from collections import deque
import datetime
from functools import partial
import multiprocessing
from multiprocessing import Pool, Process, Manager
from pprint import pprint
from queue import Empty
import time

import cv2
import nidaqmx as ni
from nidaqmx import constants
import numpy as np
from scipy import signal

from scripts import microphone_input, scheduled_feeding, video_acquisition


CAPTURE_DIRECTORY = 'captured_frames'
NUM_MICROPHONES = 2
MIC_DIRECTORY = 'mic_data'


def run_camera(directory, duration, serial, port, name, period_extension, framerate=30):
	cam = video_acquisition.FLIRCamera(directory,
			camera_serial=serial,
			period_extension=period_extension,
			port_name=name,
			counter_port=port,
			framerate=framerate)
	cam.start_capture()
	time.sleep(duration)
	cam.end_capture()


def run_cameras(directory, duration):
	camera_serials = (video_acquisition.FLIRCamera.CAMERA_A_SERIAL, video_acquisition.FLIRCamera.CAMERA_B_SERIAL)
	camera_names = ('cam_a', 'cam_b')
	camera_ports = ('Dev1/ctr1', None)
	# The next term is camera specific and based on the mean error between each of the camera's frames' timestamps
	#camera_period_extension = (1.41661592e-7, 3.05238578e-7)
	camera_period_extension = (0, 0)
	camera_params = zip(camera_serials, camera_ports, camera_names, camera_period_extension)

	with Pool(processes=2) as pool:
		print('Starting capture processes for {}'.format(str(camera_names)))
		pool.starmap(partial(run_camera, directory, duration), camera_params)
		print('Closing processes')


def multi_epoch_demo(directory, duration, epoch_len):
	"""All times are expected in seconds"""
	num_epochs = duration // epoch_len
	for iteration in range(num_epochs):
		print(f'Starting epoch {iteration + 1}/{num_epochs}')
		run_cameras(directory, epoch_len)


def spec_demo():
	manager = multiprocessing.Manager()
	DURATION = 15
	mic_data_queue = manager.Queue()
	ai_ports = [u'Dev1/ai0']
	ai_names = [u'microphone_0']
	mic_proc = Process(target=microphone_input.record, args=('mic_data', ai_ports, ai_names, DURATION, mic_data_queue, u'Dev1/ai2'))
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
		f, t, spec = signal.spectrogram( \
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


def command_line_demo():
	parser = argparse.ArgumentParser()
	parser.add_argument('duration', help='How long the script should run (in hours)', type=float)
	parser.add_argument('epoch_len', help='How long each epoch of data acquisition should be (in minutes)', type=int)
	parser.add_argument('--dispenserinterval', help='How often the dispensers should be activated (in minutes)', type=int)
	args = parser.parse_args()
	
	DURATION = int(60 * args.duration)
	EPOCH_LEN = int(60 * args.epoch_len)
	if args.dispenserinterval:
		DISP_INTERVAL = args.dispenserinterval * 60
	else:
		DISP_INTERVAL = None  # Don't run the dispenser

	if DISP_INTERVAL is not None:
		dio_ports = ('Dev1/port0/line7',)
		stop_dt = datetime.datetime.now() + datetime.timedelta(seconds=DURATION)
		feeder_proc = Process(target=scheduled_feeding.feed_regularly, args=(dio_ports, DISP_INTERVAL, False, stop_dt))
		feeder_proc.start()

	mic_data_queue = Q()
	ai_ports = [u'Dev1/ai{}'.format(i) for i in range(NUM_MICROPHONES)]
	ai_names = [u'microphone_{}'.format(a) for a in range(NUM_MICROPHONES)]
	mic_proc = Process(target=microphone_input.record, args=(MIC_DIRECTORY, ai_ports, ai_names, DURATION, None, u'Dev1/ai2'))
	mic_proc.start()

	# Begin sending sync signal
	co_task = ni.Task()
	co_task.co_channels.add_co_pulse_chan_freq('Dev1/ctr0', 'counter0', freq=12206.5)
	co_task.timing.cfg_implicit_timing(sample_mode=constants.AcquisitionType.CONTINUOUS)
	co_task.start()

	multi_epoch_demo(CAPTURE_DIRECTORY, DURATION, EPOCH_LEN)

	mic_proc.join()
	if DISP_INTERVAL is not None:
		feeder_proc.join()
	print('Done, {}'.format(str(datetime.datetime.now())))
	print('Closing remaining processes...')
	mic_proc.close()
	if DISP_INTERVAL is not None:
		feeder_proc.close()


if __name__ == '__main__':
    command_line_demo()
