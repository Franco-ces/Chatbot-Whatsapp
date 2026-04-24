import os
from dotenv import load_dotenv

from rag_langchain import RAGLangchain
from speech_to_text import SpeechToText
from audio_handler import AudioHandler

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")

rag = RAGLangchain(api_key)
stt = SpeechToText()
audio_handler = AudioHandler("audios")


while True:
    print("\n--- MENU ---")
    print("1. Escribir pregunta")
    print("2. Procesar audios")
    print("0. Salir")

    opcion = input("Elegí una opción: ")

    # 🔹 MODO TEXTO
    if opcion == "1":
        query = input("\nPregunta: ")
        respuesta = rag.preguntar(query)
        print("\nRespuesta:", respuesta)

    # 🔹 MODO AUDIO (LISTA + PROCESAMIENTO)
    elif opcion == "2":
        audios = audio_handler.listar_audios()

        if not audios:
            print("\nNo hay audios en la carpeta.")
            continue

        print("\nAudios encontrados:")
        for i, audio in enumerate(audios):
            print(f"{i+1}. {audio.name}")

        print("\nProcesando audios...\n")

        for audio in audios:
            try:
                # RUTA ABSOLUTA (FIX REAL)
                ruta_audio = str(audio.resolve())
                print(f" Audio: {audio.name}")
                print(f" Ruta: {ruta_audio}")

                texto = stt.transcribir(ruta_audio)
                print(f" Texto: {texto}")

                respuesta = rag.preguntar(texto)
                print(f" Respuesta: {respuesta}\n")

            except Exception as e:
                print(f" Error procesando {audio.name}: {e}")

        limpiar = input("¿Eliminar audios procesados? (s/n): ")

        if limpiar.lower() == "s":
            audio_handler.limpiar_todos()
            print("Audios eliminados.")

    elif opcion == "0":
        break

    else:
        print("Opción inválida.")