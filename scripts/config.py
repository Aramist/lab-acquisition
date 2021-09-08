import numpy as np


constants = {
    'num_microphones': 2,
    'data_directory': 'acquired_data',
    'camera_a_serial': '19390113',
    'camera_b_serial': '19413860',
    'camera_ctr_port': 'Dev1/ctr1',
    'camera_framerate': 30,  # Hz/fps
    'cam_a_enabled': False,
    'cam_b_enabled': True,
    'cam_a_display_enabled': False,
    'cam_b_display_enabled': True,
    'cam_a_window_name': 'Camera A',
    'cam_b_window_name': 'Camera B',
    'cam_a_calibration_path': None, # for de-fisheye-ing
    'cam_b_calibration_path': None, # for de-fisheye-ing
    'cam_output_signal_ai_port': 'Dev1/ai6',

    'microphone_sample_rate': 125000,  # Hz
    'microphone_data_retrieval_interval': 0.25,  # n seconds between each read from DAQ buffer; keep < 2 seconds and > .1 seconds
    'spectrogram_display_enabled': True,
    'spectrogram_rmic_correction_factor': 1 / 1.85,  # Normalize the input from the louder microphone
    'spectrogram_red_color': np.array([87, 66, 206]).reshape((1, 1, 3)),  # BGR order
    'spectrogram_blue_color': np.array([218, 214, 109]).reshape((1, 1, 3)),  # BGR order
    'spectrogram_white_color': np.array([255, 255, 255]).reshape((1, 1, 3)),  # BGR order
    'spectrogram_black_color': np.array([0, 0, 0]).reshape((1, 1, 3)),  # BGR order
    'spectrogram_nfft': 512,
    'spectrogram_noverlap': 0,
    'spectrogram_deque_size': 20,  # 5 seconds worth
    'spectrogram_upper_cutoff': 1000e-11,
    'spectrogram_lower_cutoff': 90e-11,
    'spectrogram_mic_difference_thresh': 450e-11,
    'spectrogram_window_name': 'Spectrogram (right side blue, left side red)',

    'wm_sync_signal_frequency': 125000,  # Hz
    'wm_sync_signal_port': 'Dev1/ctr0',
    'wm_trig_ai_port': 'Dev1/ai7',
    'audio_ttl_ai_port': 'Dev1/ai5',


}