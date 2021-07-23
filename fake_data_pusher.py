from collections import deque
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
            [next(cyc) for _ in range(65200)],
            dtype=np.float32
        )
        yield(ret)

    return np.random.rand(1, 62500)

def frame_generator(file):
    while True:
        cap = cv2.VideoCapture(file)
        ret, frame = cap.read()
        while ret:
            yield frame
            time.sleep(1/30)
            ret, frame = cap.read()


def fake_camera_task(duration, image_queue, filepath):
    generator = frame_generator(filepath)
    for frame in generator:
        if len(frame.shape) > 2:
            image_queue.put(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        else:
            image_queue.put(frame)


def fake_spec_task(duration, spec_queue):
    if spec_queue is None:
        return
    data_gen = fake_mic_data()
    mic_deque = deque(maxlen=20)
    start_time = time.time()
    while duration < 0 or time.time() - start_time < duration:
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
        time.sleep(0.5)


def fake_video_audio(duration, audio_queue, video_queue):
    if video_queue is None or audio_queue is None:
        return
    audio_thread = threading.Thread(target=fake_spec_task, args=(duration, audio_queue))
    video_thread = threading.Thread(target=fake_camera_task, args=(duration, video_queue, 'video.avi'))

    audio_thread.start()
    video_thread.start()

if __name__ == '__main__':
    fake_spec_task(3, queue.Queue())