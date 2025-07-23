import azure.cognitiveservices.speech as speechsdk
from PySide6.QtCore import QObject, QThread, Signal, QBuffer, QByteArray, QIODevice
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

class Worker(QObject):
    # We go back to the simple signal. No more duration calculation.
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
    playback_started = Signal()
    playback_finished = Signal()
    playback_stopped = Signal()
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.azure_key = None
        self.azure_region = None
        self.thread = QThread(self) 
        self.worker = None
        self.is_playing = False # This flag is now crucial

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.buffer = QBuffer()
        
        # We return to the most reliable signal, but will use it more carefully.
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
    
    def set_credentials(self, key, region):
        self.azure_key = key
        self.azure_region = region

    def play(self, text):
        if not self.azure_key or not self.azure_region:
            self.error_occurred.emit("Azure credentials are not set.")
            return

        if self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()

        self.worker = Worker(self.azure_key, self.azure_region, text)
        self.worker.moveToThread(self.thread)
        self.worker.error.connect(self._on_tts_error)
        self.worker.finished.connect(self._play_audio_data)
        self.thread.started.connect(self.worker.run)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()
        self.playback_started.emit()

    def stop(self):
        # Set the flag to False BEFORE stopping the player.
        self.is_playing = False
        self.player.stop()
        if self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()
        self.playback_stopped.emit()

    def _play_audio_data(self, audio_data):
        if not audio_data:
            self.playback_finished.emit()
            return
        
        # --- THE FIX: Carefully manage state to prevent the race condition ---
        # 1. Ensure the flag is false before we do anything.
        self.is_playing = False
        # 2. Stop the player. This might prematurely emit EndOfMedia, but it will be ignored.
        self.player.stop() 
        
        self.buffer.close()
        self.buffer.setData(audio_data)
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.player.setSourceDevice(self.buffer)
        
        # 3. Only now is it safe to set the flag to True and play.
        self.is_playing = True
        self.player.play()

    def _on_media_status_changed(self, status):
        """
        This slot now correctly handles the end-of-media signal by checking our state flag.
        """
        # This condition is now robust. It only fires if the media truly finishes
        # while we are in an active playing state.
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self.is_playing:
            self.is_playing = False # Reset the flag for the next sentence
            self.playback_finished.emit()

    def _on_tts_error(self, error_message):
        self.error_occurred.emit(error_message)
        self.stop()