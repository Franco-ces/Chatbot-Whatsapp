from google.genai import types

class AudioProcessor:
    def __init__(self, client):
        self.client = client

    def extraer_transcripcion_memoria(self, audio_bytes: bytes, mime_type: str = "audio/ogg"):
        """
        Recibe los bytes del audio directamente desde la RAM, 
        solicita la transcripción y devuelve el texto.
        """
        if not audio_bytes:
            return None, None
        
        # Instanciamos el objeto Part de Gemini inyectando la memoria directamente
        audio_part = types.Part.from_bytes(
            data=audio_bytes,
            mime_type=mime_type
        )
        
        # Enviamos los bytes a la API de Google sin haber tocado el disco local
        respuesta = self.client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[audio_part, "Transcribe textualmente la consulta de este audio de forma clara y directa."]
        )
        
        return respuesta.text, audio_part