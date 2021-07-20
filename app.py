import multiprocessing
import queue

from flask import Flask, render_template
app = Flask(__name__)


# Paths for different requests
RECENT_UPDATE_TS = '/data/spectrogarm-update-ts'
SPECTROGRAM_DATA = '/data/spectrogram-raw'
SPECTROGRAM_TIMES = '/data/spectrogram-ts'
SPECTROGRAM_FREQS = '/data/spectrogram-frequencies'


@app.route('/', methods=['GET', 'POST'])
def home():
    return render_template('index.html')

@app.route(RECENT_UPDATE_TS, methods=['GET'])
def request_recent_ts():
    pass


@app.route(SPECTROGRAM_DATA, methods=['GET'])
def request_spectrogram_data():
    pass


@app.route(SPECTROGRAM_TIMES, methods=['GET'])
def request_spectrogram_times():
    pass


@app.route(SPECTROGRAM_FREQS, methods=['GET']):
    pass


if __name__ == '__main__':
    # Attempt to start acquisition processes here. Save own queues
    with multiprocessing.Manager() as manager:
        mic_spec_queue = manager.Queue()
        image_queue = manager.Queue()
        acq_proc = Process(target=multiprocess_run.begin_acquisition,
                args=(60, 60, None, mic_spec_queue, False))
        acq_proc.start()
        app.run(debug=True)

