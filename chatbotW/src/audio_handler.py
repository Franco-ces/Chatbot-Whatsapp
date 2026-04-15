from pathlib import Path


class AudioHandler:
    def __init__(self, folder="audios"):
        #  ruta absoluta SIEMPRE
        base_path = Path(__file__).resolve().parent.parent
        self.folder = base_path / folder
        

        if not self.folder.exists():
            print(f" La carpeta {self.folder} no existe")

    def listar_audios(self):
        #  formatos compatibles 
        extensiones = ["*.ogg", "*.opus", "*.mp3", "*.wav", "*.m4a"]

        audios = []
        for ext in extensiones:
            audios.extend(self.folder.glob(ext))

        return audios

    def limpiar_todos(self):
        for audio in self.folder.glob("*.*"):
            audio.unlink()