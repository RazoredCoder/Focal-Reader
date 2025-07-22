import azure.cognitiveservices.speech as speechsdk
from PySide6.QtCore import QObject, QThread, Signal, QBuffer, QByteArray, QIODevice
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

# The Worker class is now located here, unchanged.
class Worker(QObject):
    finished = Signal(QByteArray)
    error = Signal(str)
    def __init__(self, key, region, text_to_speak):
        super().__init__()
        self.key, self.region, self.text = key, region, text_to_speak
    def run(self):
        try:
            if not self.key or not self.region: raise ValueError("Azure credentials are not set.")
            speech_config = speechsdk.SpeechConfig(subscription=self.key, region=self.region)
            synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
            result = synthesizer.speak_text_async(self.text).get()
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                self.finished.emit(QByteArray(result.audio_data))
            else:
                self.error.emit(f"Speech synthesis failed: {result.reason}")
        except Exception as e: self.error.emit(str(e))

class TTSHandler(QObject):
    # Signals to communicate back to the MainWindow
    playback_started = Signal()
    playback_finished = Signal() # Emitted when a sentence finishes playing
    playback_stopped = Signal() # Emitted when stop() is called manually
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.azure_key = None
        self.azure_region = None
        self.thread = None
        self.worker = None

        # The player and its components now live here
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.buffer = QBuffer()
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
    
    def set_credentials(self, key, region):
        self.azure_key = key
        self.azure_region = region

    def play(self, text):
        """Public method to start playing a piece of text."""
        if not self.azure_key or not self.azure_region:
            self.error_occurred.emit("Azure credentials are not set.")
            return

        # Clean up any previous thread
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()

        self.thread = QThread()
        self.worker = Worker(self.azure_key, self.azure_region, text)
        self.worker.moveToThread(self.thread)

        self.worker.error.connect(self._on_tts_error)
        self.worker.finished.connect(self._play_audio_data)

        self.thread.started.connect(self.worker.run)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()
        self.playback_started.emit()

    def stop(self):
        """Public method to stop playback immediately."""
        self.player.stop()
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()
        self.playback_stopped.emit()

    def _play_audio_data(self, audio_data):
        if not audio_data:
            self.playback_finished.emit()
            return
        
        self.player.stop()
        self.buffer.close()
        self.buffer.setData(audio_data)
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.player.setSourceDevice(self.buffer)
        self.player.play()

    def _on_media_status_changed(self, status):
        # When the audio finishes, emit a signal. The MainWindow will decide what to do next.
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.playback_finished.emit()

    def _on_tts_error(self, error_message):
        self.error_occurred.emit(error_message)
        self.stop()