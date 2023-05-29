import base64
import io
import operator
import os
from functools import reduce
from typing import Optional

import librosa
import librosa.display
import magic
import numpy as np
import pydub
import requests
import streamlit as st
from matplotlib import pyplot as plt
from scipy.io import wavfile


def transform_and_mul_int(value: str) -> int:
    return reduce(operator.mul, map(int, value.split("*")))


MAX_FILE_SIZE = transform_and_mul_int(os.getenv("MAX_FILE_SIZE"))

plt.rcParams["figure.figsize"] = (12, 10)

endpoint_enhancement = os.getenv("API_ENHANCEMENT_URI")
endpoint_recognition = os.getenv("API_RECOGNITION_URI")
endpoint_separation = os.getenv("API_SEPARATION_URI")


class AbstractOption:
    file_bytes: bytes
    file_mime_type: str
    file_name: str
    mime_type_audio_command_map = {
        "audio/mpeg": "from_mp3",
        "audio/wav": "from_wav",
        "audio/x-wav": "from_wav",
    }

    def __init__(self, file_uploader):
        if file_uploader is None:
            raise ValueError
        self.parse_file_uploader(file_uploader)
        self.validate_file_data()

    @property
    def name(self):
        raise NotImplementedError

    def handle(self, *args, **kwargs):
        raise NotImplementedError

    def parse_file_uploader(self, file_uploader):
        file_bytes = file_uploader.read()
        self.file_bytes = file_bytes
        # determine mime-type
        mime_type = magic.Magic(mime=True).from_buffer(file_bytes)
        mime_type = mime_type.lower()
        print(mime_type)
        self.file_mime_type = mime_type
        self.file_name = file_uploader.name

    def validate_file_data(self):
        # TODO show error for user instead raise ValueError
        if self.file_mime_type not in self.mime_type_audio_command_map:
            raise ValueError
        if len(self.file_bytes) > MAX_FILE_SIZE:
            raise ValueError

    def call_api(self, url):
        response = requests.post(
            url,
            files={"file": (self.file_name, self.file_bytes, self.file_mime_type)},
            timeout=8000,
        )
        if response.status_code != 200:
            st.error(f"error {response.status_code} {response.content}")
        return response.json()

    def convert_audio_bytes(self, file_bytes: Optional[bytes] = None, file_mime_type: Optional[str] = None):
        if file_bytes is None:
            file_bytes = self.file_bytes
        if file_mime_type is None:
            file_mime_type = self.file_mime_type

        buffer = io.BytesIO()
        buffer.write(file_bytes)
        buffer.seek(0)

        audio = getattr(pydub.AudioSegment, self.mime_type_audio_command_map[file_mime_type])(file=buffer)
        # handle audio data
        channel_sounds = audio.split_to_mono()
        samples = [s.get_array_of_samples() for s in channel_sounds]
        fp_arr = np.array(samples).T.astype(np.float32)
        fp_arr /= np.iinfo(samples[0].typecode).max
        source, sample_rate = fp_arr[:, 0], audio.frame_rate
        return source, sample_rate

    @staticmethod
    def draw_audio_player(source, sample_rate):
        in_memory_file = io.BytesIO()
        wavfile.write(in_memory_file, rate=sample_rate, data=source)
        # draw player
        st.audio(in_memory_file)

    @staticmethod
    def plot_wave(source, sample_rate):
        fig, ax = plt.subplots()
        librosa.display.waveshow(source, sr=sample_rate, x_axis="time", ax=ax)
        return plt.gcf()

    @staticmethod
    def add_h_space():
        st.markdown("<br></br>", unsafe_allow_html=True)


class SpeechRecognition(AbstractOption):
    name = "Speech Recognition"

    def handle(self, *args, **kwargs):

        api_result = self.call_api(endpoint_recognition)

        st.markdown(
            "<h4 style='text-align: center; color: black;'>Audio</h5>",
            unsafe_allow_html=True,
        )
        # draw audio player
        source, sample_rate = self.convert_audio_bytes()
        self.draw_audio_player(source, sample_rate)
        st.markdown("---")
        # show recognition result
        st.write(api_result["text"])


class SpeechSeparation(AbstractOption):
    name = "Speech Separation"

    def handle(self, *args, **kwargs):
        # start recognition via api
        api_result = self.call_api(endpoint_separation)
        separated_file = api_result.get("output_files")
        separated_file.sort(key=lambda x: x.get("order"))
        for i, source in enumerate(separated_file):
            result = source["file"]
            rate = source["rate"]
            result = result.encode(encoding="UTF-8")
            buff = base64.decodebytes(result)
            sound = np.frombuffer(buff, dtype=np.float32)
            in_memory_file = io.BytesIO()
            wavfile.write(in_memory_file, rate=rate, data=sound)
            st.write(f"part: {i + 1}")
            st.audio(in_memory_file)
            st.markdown("---")


class SpeechEnhancement(AbstractOption):
    name = "Speech Enhancement"

    def handle(self, *args, **kwargs):
        col1, col2, col3 = st.columns([1, 1, 1])

        with col1:
            st.markdown(
                f"<h4 style='text-align: center; color: black;'>Original Waveform</h5>",
                unsafe_allow_html=True,
            )
            source, sample_rate = self.convert_audio_bytes()
            self.draw_audio_player(source, sample_rate)

        with col2:
            st.markdown(
                f"<h4 style='text-align: center; color: black;'>Original Spectrogram</h5>",
                unsafe_allow_html=True,
            )
            fig, ax = plt.subplots()
            spectrogram = librosa.amplitude_to_db(np.abs(librosa.stft(source)), ref=np.max)
            plt.imshow(
                spectrogram,
                origin="lower",
                aspect="auto",
                cmap="viridis",
                extent=[0, len(source) / sample_rate, 0, sample_rate / 2],
            )
            plt.colorbar(format="%+2.0f dB")
            plt.xlabel("Time (s)")
            plt.ylabel("Frequency (Hz)")
            plt.tight_layout()
            st.pyplot(fig)

        with col3:
            st.markdown(
                f"<h4 style='text-align: center; color: black;'>Original Wave Plot</h5>",
                unsafe_allow_html=True,
            )
            st.pyplot(self.plot_wave(source, sample_rate))
            self.add_h_space()

        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            st.markdown(
                f"<h4 style='text-align: center; color: black;'>Enhanced Waveform</h5>",
                unsafe_allow_html=True,
            )
            # Speech Enhancement via api
            api_result = self.call_api(endpoint_enhancement)
            result = api_result["payload"]
            result = result.encode(encoding="UTF-8")
            buff = base64.decodebytes(result)
            enhanced_sound = np.frombuffer(buff, dtype=np.float32)
            self.draw_audio_player(enhanced_sound, sample_rate)

        with col2:
            st.markdown(
                f"<h4 style='text-align: center; color: black;'>Enhanced Spectrogram</h5>",
                unsafe_allow_html=True,
            )
            fig, ax = plt.subplots()
            enhanced_spectrogram = librosa.amplitude_to_db(np.abs(librosa.stft(enhanced_sound)), ref=np.max)
            plt.imshow(
                enhanced_spectrogram,
                origin="lower",
                aspect="auto",
                cmap="viridis",
                extent=[0, len(source) / sample_rate, 0, sample_rate / 2],
            )
            plt.colorbar(format="%+2.0f dB")
            plt.xlabel("Time (s)")
            plt.ylabel("Frequency (Hz)")
            plt.tight_layout()
            st.pyplot(fig)

        with col3:
            st.markdown(
                f"<h4 style='text-align: center; color: black;'>Enhanced Wave Plot</h5>",
                unsafe_allow_html=True,
            )
            st.pyplot(self.plot_wave(source, sample_rate))
            self.add_h_space()


def main():
    placeholder = st.empty()
    placeholder2 = st.empty()
    placeholder.markdown(
        "# Processing of sound and speech by SpeechBrain framework\n"
        "### Select the processing procedure in the sidebar.\n"
        "Once you have chosen processing procedure, select or upload an audio file\n. "
        "Then click 'Apply' to start! \n\n"
    )
    placeholder2.markdown("After clicking start,the result of the selected procedure are visualized.")
    options_map = {
        SpeechRecognition.name: SpeechRecognition,
        SpeechEnhancement.name: SpeechEnhancement,
        SpeechSeparation.name: SpeechSeparation,
    }
    option = st.sidebar.selectbox("Audio Processing Task", options=options_map)
    st.sidebar.markdown("---")
    st.sidebar.markdown("(Optional) Upload an audio file here:")
    file_uploader = st.sidebar.file_uploader(label="", type=[".wav", ".mp3"])
    st.sidebar.markdown("---")
    if st.sidebar.button("Apply"):
        if file_uploader is None:
            st.markdown(
                "<h4 style='text-align: center; color: black;'>Audio file required</h5>",
                unsafe_allow_html=True,
            )
        else:
            placeholder.empty()
            placeholder2.empty()
            handler = options_map[option](file_uploader)
            handler.handle()


if __name__ == "__main__":
    st.set_page_config(layout="wide", page_title="Speech brain audio file processing")
    main()
