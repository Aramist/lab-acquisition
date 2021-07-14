import argparse
import datetime
from functools import partial
from multiprocessing import Pool, Process
import time

# Local imports
from scripts import microphone_input, scheduled_feeding, video_acquisition


CAPTURE_DIRECTORY = 'captured_frames'
NUM_MICROPHONES = 2
MIC_DIRECTORY = 'mic_data'


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


def run_cameras(directory, duration):
	camera_serials = (video_acquisition.FLIRCamera.CAMERA_A_SERIAL, video_acquisition.FLIRCamera.CAMERA_B_SERIAL)
	camera_names = ('cam_a', 'cam_b')
	camera_ports = ('Dev1/ctr0', 'Dev1/ctr1')
	# The next term is camera specific and based on the mean error between each of the camera's frames' timestamps
	#camera_period_extension = (1.41661592e-7, 3.05238578e-7)
	camera_period_extension = (0, 0)
	camera_params = zip(camera_serials, camera_names, camera_ports, camera_period_extension)

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


if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument('duration', help='How long the script should run (in hours)', type=float)
	parser.add_argument('epoch_len', help='How long each epoch of data acquisition should be (in minutes)', type=int)
	parser.add_argument('--dispenserinterval', help='How often the dispensers should be activated (in minutes)', type=int)
	args = parser.parse_args()
	
	DURATION = int(3600 * args.duration)
	EPOCH_LEN = int(60 * args.epoch_len)
	if args.dispenserinterval:
		DISP_INTERVAL = args.dispenserinterval * 60
	else:
		DISP_INTERVAL = None  # Don't run the dispenser

	if DISP_INTERVAL:
		dio_ports = ('Dev1/port0/line7',)
		stop_dt = datetime.datetime.now() + datetime.timedelta(seconds=DURATION)
		feeder_proc = Process(target=scheduled_feeding.feed_regularly, args=(dio_ports, DISP_INTERVAL, False, stop_dt))
		feeder_proc.start()

	
	ai_ports = [u'Dev1/ai{}'.format(i) for i in range(NUM_MICROPHONES)]
	ai_names = [u'microphone_{}'.format(a) for a in range(NUM_MICROPHONES)]
	mic_proc = Process(target=microphone_input.record, args=(MIC_DIRECTORY, ai_ports, ai_names, DURATION))
	mic_proc.start()

	multi_epoch_demo(CAPTURE_DIRECTORY, DURATION, EPOCH_LEN)

	mic_proc.join()
	feeder_proc.join()
	print('Done, {}'.format(str(datetime.datetime.now())))
	print('Closing remaining processes...')
	mic_proc.close()
	feeder_proc.close()
