import datetime
from functools import partial
from multiprocessing import Pool
import time

import video_acquisition


CAPTURE_DIRECTORY = 'captured_frames'
# CALCULATED_FRAMERATE = 29.9998066833


def run_camera(directory, duration, index, name, port, period_extension, framerate=30):
	cam = video_acquisition.FLIRCamera(directory,
			camera_index=index,
			period_extension=period_extension,
			port_name=name,
			counter_port=port,
			framerate=framerate)
	cam.start_capture()
	time.sleep(duration)
	cam.end_capture()


def run(directory, duration):
	camera_indices = (0, 1)
	camera_names = ('cam0', 'cam1')
	camera_ports = ('Dev1/ctr0', 'Dev1/ctr1')
	# The next term is camera specific and based on the mean error between each of the camera's frames' timestamps
	camera_period_extension = (1.41661592e-7, 3.05238578e-7)
	camera_params = zip(camera_indices, camera_names, camera_ports, camera_period_extension)

	with Pool(processes=2) as pool:
		print('Starting capture processes for {}'.format(str(camera_names)))
		pool.starmap(partial(run_camera, directory, duration), camera_params)
		# time.sleep(duration)  # The starmap function doesn't return until the functions return so this is unnecessary
		print('Closing processes')


def multi_epoch_demo(directory, duration, epoch_len):
	"""All times are expected in seconds"""
	num_epochs = duration // epoch_len
	for iteration in range(num_epochs):
		print(f'Starting epoch {iteration + 1}/{num_epochs}')
		run(directory, epoch_len)


if __name__ == '__main__':
	# run(CAPTURE_DIRECTORY, 60)
	multi_epoch_demo(CAPTURE_DIRECTORY, 3600 * 48, 60 * 30)  # 30 minute segments over 48 hours
	print('Done, {}'.format(str(datetime.datetime.now())))
