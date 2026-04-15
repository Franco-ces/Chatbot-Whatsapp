import os
import whisper

# FORZAR ruta de ffmpeg (NO necesitas PATH)
import os
import whisper

# agregar ffmpeg al PATH sin tocar Windows
os.environ["PATH"] += os.pathsep + r"D:\Users\Usuario\Desktop\ffmpeg-8.1-essentials_build\bin"


class SpeechToText:
    def __init__(self, model_size="base"):
        self.model = whisper.load_model(model_size)

    def transcribir(self, audio_path):
        try:
            result = self.model.transcribe(audio_path)
            return result["text"]
        except Exception as e:
            return f"Error al transcribir: {e}"