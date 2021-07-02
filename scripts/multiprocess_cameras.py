from functools import partial
from multiprocessing import Pool
import time

import video_acquisition


CAPTURE_DIRECTORY = 'captured_frames'
CALCULATED_FRAMERATE = 29.9998066833


def run_camera(directory, duration, index, name, port, framerate=CALCULATED_FRAMERATE):
	cam = video_acquisition.FLIRCamera(directory,
			camera_index=index,
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
	camera_params = zip(camera_indices, camera_names, camera_ports)

	with Pool(processes=2) as pool:
		print('Starting capture processes for {}'.format(str(camera_names)))
		pool.starmap(partial(run_camera, directory, duration), camera_params)
		# time.sleep(duration)  # The starmap function doesn't return until the functions return so this is unnecessary
		print('Closing processes')
	print('Done')


if __name__ == '__main__':
	run(CAPTURE_DIRECTORY, 60 * 60 * 22) # 22 Hours, started just before 2PM, 2021-07-01
