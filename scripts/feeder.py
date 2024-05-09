import threading
import time

import nidaqmx as ni


FEEDER_PULSE_LEN = 20e-6  # 20us


class Feeder:
	def __init__(self, port, name):
		self.port = port
		self.name = name
		self.task = ni.Task()
		self.task.do_channels.add_do_chan(port, name)
		self.task.start()

	def __del__(self):
		self.task.stop()
		self.task.close()

	def __exit__(self, type, value, traceback):
		self.task.stop()
		self.task.close()

	def __enter__(self):
		return self

	def dispense_once(self):
		# Wasn't sure if there would be any problems with referencing self directly from the other thread
		def thread_func(feeder):
			feeder.task.write(True)
			time.sleep(FEEDER_PULSE_LEN)
			feeder.task.write(False)
		threading.Thread(target=thread_func, args=(self,)).start()


def demo():
	"""Demos the feeder using the DIO port 0.7. Dispenses 10 times over 5 seconds"""
	demo_feeder = Feeder(u'Dev1/port0/line7', u'Feeder0')
	for _ in range(10):
		demo_feeder.dispense_once()
		time.sleep(0.5)


if __name__ == '__main__':
	demo()
