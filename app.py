from collections import deque
from ctypes import c_bool
import multiprocessing
import queue
import threading

from flask import Flask, jsonify, make_response, render_template, request
app = Flask(__name__)

import fake_data_pusher
# import multiprocess_run


# Paths for different requests
SPEC_DATA_REQUEST = '/data/spectrogram/data'
SPEC_META_REQUEST = '/data/spectrogram/meta'

VIDEO_DATA_REQUEST = '/data/video/data'
VIDEO_META_REQUEST = '/data/video/meta'

# Globals for caching the most recent data
SPEC_DATA_DEQUE = deque(maxlen=12)
SPEC_META_DEQUE = deque(maxlen=12)
FRAME_DEQUE = deque(maxlen=40)

# Globals for keeping track of the frame ids
SPEC_COUNTER = 0
FRAME_COUNTER = 0


@app.route('/', methods=['GET', 'POST'])
def home():
    return render_template('index.html')


@app.route(SPEC_META_REQUEST, methods=['GET'])
def request_spectrogram_meta():
    global SPEC_META_DEQUE
    response = {
        'id': -1,
        'len_seconds': 0,
        'min_frequency': 0,
        'max_frequency': 0,
        'dim_time': 0,
        'dim_freq': 0
    }
    if len(SPEC_META_DEQUE) > 0:
        f, t, frame_id = SPEC_META_DEQUE[3]
        response['id'] = frame_id
        response['len_seconds'] = float(t[-1] - t[0])
        response['min_frequency'] = float(f[0])
        response['max_frequency'] = float(f[-1])
        response['dim_time'] = len(t)
        response['dim_freq'] = len(f)
    return jsonify(response)


@app.route(SPEC_DATA_REQUEST, methods=['GET'])
def request_spectrogram_data():
    global SPEC_DATA_DEQUE
    global SPEC_META_DEQUE
    try:
        req_id = int(request.args.get('id'))
    except Exception:
        return make_response('Bad id', 400)
    if len(SPEC_DATA_DEQUE) == 0:
        return make_response('No data to send', 400)
    else:
        low, high = SPEC_META_DEQUE[0][2], SPEC_META_DEQUE[-1][2]
        if req_id < low:
            return make_response('Id too low', 400)
        elif req_id > high:
            return make_response('Id too high', 400)
        else:
            response = make_response(SPEC_DATA_DEQUE[req_id - low].tobytes(), 200)
    response.headers['Content-Type'] = 'application/octet-stream'
    return response


@app.route(VIDEO_META_REQUEST, methods=['GET'])
def request_video_meta():
    global FRAME_DEQUE
    response = dict()
    if len(FRAME_DEQUE) < 10:
        return make_response('No data to give.', 400)
    shape = FRAME_DEQUE[9][0].shape
    response['width'] = shape[1]
    response['height'] = shape[0]
    response['channels'] = shape[-1] if len(shape) > 2 else 1
    response['id'] = FRAME_DEQUE[9][1]
    return jsonify(response)


def read(filse):
    cap = cv2.VideoCapture('filename')
    ret, frame = cap.read()
    while ret:
        # do stuff
        ret, frame = cap.read()

@app.route(VIDEO_DATA_REQUEST, methods=['GET'])
def request_video_data():
    try:
        req_id = int(request.args.get('id'))
    except Exception:
        return make_response('Bad id', 400)
    if len(FRAME_DEQUE) == 0:
        return make_response('No data to send', 400)
    
    low, high = FRAME_DEQUE[0][1], FRAME_DEQUE[-1][1]
    if req_id < low:
        return make_response('Id too low', 400)
    elif req_id > high:
        return make_response('Id too high', 400)
    else:
        response = make_response(FRAME_DEQUE[req_id - low][0].tobytes(), 200)
        response.headers['Content-Type'] = 'application/octet-stream'
        return response


def audio_thread(q):
    counter = 0
    while True:
        try:
            data = q.get(block=True, timeout=1)
            global SPEC_COUNTER
            global SPEC_META_DEQUE
            global SPEC_DATA_DEQUE
            SPEC_META_DEQUE.append((data[0], data[1], SPEC_COUNTER))
            SPEC_DATA_DEQUE.append(data[2])
            SPEC_COUNTER += 1
        except queue.Empty:
            pass
            """
            counter += 1
            if counter > 10:
                app.logger.info('Halting audio thread')
                break
            else:
                continue
            """


def video_thread(q):
    counter = 0
    while True:
        try:
            data = q.get(block=True, timeout=0.5)
            global FRAME_DEQUE
            global FRAME_COUNTER
            FRAME_DEQUE.append((data, FRAME_COUNTER))
            FRAME_COUNTER += 1
        except queue.Empty:
            pass
            """
            counter += 1
            if counter > 10:
                app.logger.info('Halting video thread')
                break
            else:
                continue
            """


if __name__ == '__main__':
    # Attempt to start acquisition processes here. Save own queues
    with multiprocessing.Manager() as manager:
        acq_enabled = manager.Value(c_bool, False)
        script_running = manager.Value(c_bool, True)
        spec_queue = manager.Queue()
        video_queue = manager.Queue()

        acq_proc = multiprocessing.Process(
                target=fake_data_pusher.fake_video_audio,
                args=(script_running, acq_enabled, video_queue, spec_queue,))
        acq_proc.start()
        '''
        acq_proc = multiprocessing.Process(target=multiprocess_run.begin_acquisition,
                args=(60, 60, None, mic_spec_queue, False))
        acq_proc.start()
        '''
        a_thread = threading.Thread(target=audio_thread, args=(spec_queue,))
        v_thread = threading.Thread(target=video_thread, args=(video_queue,))
        a_thread.start()
        v_thread.start()

        """
        def exit_handler(killswitch):
            killswitch.value = False
        atexit.register(exit_handler, script_running)
        """

        app.run(debug=True, use_reloader=False)
