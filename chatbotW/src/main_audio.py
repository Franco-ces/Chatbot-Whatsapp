import os
from dotenv import load_dotenv

from src.rag_langchain_con_audio import RAGLangchain
from src.audio_handler import AudioHandler
from src.chat_logger import ChatLogger

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")

rag = RAGLangchain(api_key)
audio_handler = AudioHandler("audios")
logger = ChatLogger()

while True:
    print("\n--- MENU ---")
    print("1. Escribir pregunta ")
    print("2. Procesar audios ")
    print("0. Salir")

    opcion = input("Elegí una opción: ")

    if opcion == "1":
        query = input("\nPregunta: ")
        logger.guardar_usuario(query)
        
        try:
            _, respuesta = rag.preguntar(query_text=query) 
            logger.guardar_bot(respuesta)
            print(f"\nRespuesta: {respuesta}")
        except Exception as e:
            error_msg = "Servidor saturado o error de conexión. Reintentá en unos segundos."
            if "503" in str(e):
                print(f" {error_msg}")
            else:
                print(f" Error: {e}")
            logger.guardar_bot(f"ERROR: {e}")

    elif opcion == "2":
        audios = audio_handler.listar_audios()

        if not audios:
            print("\nNo hay audios en la carpeta.")
            continue

        print("\nProcesando audios...\n")

        for audio in audios:
            try:
                ruta_audio = str(audio.resolve())
                print(f"Procesando: {audio.name}")

                texto_leido, respuesta = rag.preguntar(audio_path=ruta_audio)
                
                logger.guardar_usuario(f"(AUDIO: {audio.name}) {texto_leido}")
                logger.guardar_bot(respuesta)

                print(f" Audio dice: {texto_leido}")
                print(f" Respuesta: {respuesta}\n")

            except Exception as e:
                if "503" in str(e):
                    print(f" Servidor saturado al procesar {audio.name}. Saltando...")
                else:
                    print(f" Error en {audio.name}: {e}")
                logger.guardar_bot(f"ERROR en {audio.name}: {e}")
                continue

      #  limpiar = input("¿Eliminar audios procesados? (s/n): ")
       # if limpiar.lower() == "s":
        #    audio_handler.limpiar_todos()
         #   print("Carpeta limpia.")

    elif opcion == "0":
        print("Cerrando sesión de chat...")
        break
    else:
        print("Opción inválida.")