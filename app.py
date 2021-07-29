import multiprocessing
import queue
import threading
import time

from flask import Flask, jsonify, make_response, render_template
app = Flask(__name__)

import fake_data_pusher
# import multiprocess_run


# Paths for different requests
RECENT_UPDATE_TS = '/data/spectrogram-update-ts'
SPECTROGRAM_DATA = '/data/spectrogram-raw'
SPECTROGRAM_META = '/data/spectrogram-meta'

VIDEO_DATA = '/data/recent-frame'
VIDEO_DIMS = '/data/video-meta'

# Globals for storing the most recent data
RECENT_SPEC_TUPLE = None
RECENT_FRAME = None


@app.route('/', methods=['GET', 'POST'])
def home():
    return render_template('index.html')


@app.route(RECENT_UPDATE_TS, methods=['GET'])
def request_recent_ts():
    global RECENT_SPEC_TUPLE
    response = {
        'valid': False,
        'timestamp': -1
    }
    if RECENT_SPEC_TUPLE is not None:
        response['valid'] = True
        response['timestamp'] = RECENT_SPEC_TUPLE[3]
    return jsonify(response)


@app.route(SPECTROGRAM_DATA, methods=['GET'])
def request_spectrogram_data():
    global RECENT_SPEC_TUPLE
    if RECENT_SPEC_TUPLE is None:
        response = b''
    else:
        response = RECENT_SPEC_TUPLE[2].tobytes()
    response = make_response(response)
    response.headers['Content-Type'] = 'application/octet-stream'
    return response


@app.route(SPECTROGRAM_META, methods=['GET'])
def request_spectrogram_times():
    global RECENT_SPEC_TUPLE
    response = {
        'len_seconds': 0,
        'min_frequency': 0,
        'max_frequency': 0,
        'dim_time': 0,
        'dim_freq': 0
    }
    if RECENT_SPEC_TUPLE is not None:
        f, t, _, _ = RECENT_SPEC_TUPLE
        response['len_seconds'] = float(t[-1] - t[0])
        response['min_frequency'] = float(f[0])
        response['max_frequency'] = float(f[-1])
        response['dim_time'] = len(t)
        response['dim_freq'] = len(f)
    return jsonify(response)


@app.route(VIDEO_DIMS, methods=['GET'])
def request_video_dimensions():
    global RECENT_FRAME
    response = {
        'width': 0,
        'height': 0,
        'channels': 0,
        'valid': False
    }
    if RECENT_FRAME is not None:
        shape = RECENT_FRAME.shape
        response['width'] = shape[1]
        response['height'] = shape[0]
        response['channels'] = shape[-1] if len(shape) > 2 else 1
        response['valid'] = True
    return jsonify(response)


@app.route(VIDEO_DATA, methods=['GET'])
def request_video_data():
    global RECENT_FRAME
    if RECENT_FRAME is None:
        response = b''
    else:
        response = RECENT_FRAME.tobytes()
    response = make_response(response)
    response.headers['Content-Type'] = 'application/octet-stream'
    return response


def audio_thread(q):
    counter = 0
    while True:
        try:
            data = q.get(block=True, timeout=1)
            global RECENT_SPEC_TUPLE
            RECENT_SPEC_TUPLE = (*data, time.time())
        except queue.Empty:
            counter += 1
            if counter > 10:
                app.logger.info('Halting audio thread')
                break
            else:
                continue


def video_thread(q):
    counter = 0
    while True:
        try:
            data = q.get(block=True, timeout=0.5)
            global RECENT_FRAME
            RECENT_FRAME = data
        except queue.Empty:
            counter += 1
            if counter > 10:
                app.logger.info('Halting video thread')
                break
            else:
                continue


if __name__ == '__main__':
    # Attempt to start acquisition processes here. Save own queues
    with multiprocessing.Manager() as manager:
        mic_spec_queue = manager.Queue()
        image_queue = manager.Queue()
        acq_proc = multiprocessing.Process(target=fake_data_pusher.fake_video_audio,
                args=(-1, mic_spec_queue, image_queue))
        acq_proc.start()
        '''
        acq_proc = multiprocessing.Process(target=multiprocess_run.begin_acquisition,
                args=(60, 60, None, mic_spec_queue, False))
        acq_proc.start()
        '''
        a_thread = threading.Thread(target=audio_thread, args=(mic_spec_queue,))
        v_thread = threading.Thread(target=video_thread, args=(image_queue,))
        a_thread.start()
        v_thread.start()

        app.run(debug=True, use_reloader=False)

