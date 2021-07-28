from collections import deque
import datetime
from itertools import cycle
import queue
import threading
import time

import cv2
import h5py
import numpy as np
from scipy import signal


def fake_mic_data():
    file = h5py.File('mic.h5', 'r')
    arr = np.mean(file['analog_input'], axis=0)
    cyc = cycle(arr)
    while True:
        ret = np.array(
            [next(cyc) for _ in range(125000 // 8)],
            dtype=np.float32
        )
        yield(ret)

def frame_generator(file):
    while True:
        cap = cv2.VideoCapture(file)
        ret, frame = cap.read()
        while ret:
            yield frame
            time.sleep(1/30)
            ret, frame = cap.read()


def fake_camera_task(script_running, acq_enabled, video_queue, filepath):
    generator = frame_generator(filepath)
    for frame in generator:
        if not script_running.value:
            break
        if len(frame.shape) > 2:
            video_queue.put(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        else:
            video_queue.put(frame)


def fake_spec_task(script_running, acq_enabled, spec_queue):
    data_gen = fake_mic_data()
    mic_deque = deque(maxlen=80)
    start_time = time.time()
    with open('log.txt', 'w') as ctx:
        while script_running.value:
            mic_deque.append(next(data_gen))
            data_arr = np.concatenate(list(mic_deque), axis=0)
            spec_data = signal.spectrogram( \
                data_arr, 
                fs=125000,
                nfft=1024,
                noverlap=256,
                nperseg=1024,
                scaling='density')
            spec_data = (
                spec_data[0].astype(np.float16),
                spec_data[1].astype(np.float16),
                spec_data[2].astype(np.float32)
            )
            spec_queue.put(spec_data)
            if acq_enabled:
                ctx.write('acq enabled: {}'.format(datetime.datetime.now()))
            time.sleep(0.125)


def fake_video_audio(script_running, acq_enabled, video_queue, spec_queue):
    if video_queue is None or spec_queue is None:
        return

    audio_thread = threading.Thread(target=fake_spec_task, args=(script_running, acq_enabled, spec_queue))
    video_thread = threading.Thread(target=fake_camera_task, args=(script_running, acq_enabled, video_queue, 'video.avi'))

    audio_thread.start()
    video_thread.start()

if __name__ == '__main__':
    fake_spec_task(3, queue.Queue())