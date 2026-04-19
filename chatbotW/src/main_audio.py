import os
from dotenv import load_dotenv

from src.rag_langchain_con_audio import RAGLangchain
from src.audio_handler import AudioHandler
from src.chat_logger import ChatLogger # 1. Importar la clase

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")

# --- INICIALIZACIÓN ---
rag = RAGLangchain(api_key)
audio_handler = AudioHandler("audios")
logger = ChatLogger() # 2. CREAR EL OBJETO (Aquí se crea la carpeta /logs)

while True:
    print("\n--- MENU GEMINI MULTIMODAL ---")
    print("1. Escribir pregunta (Texto)")
    print("2. Procesar audios (Multimodal)")
    print("0. Salir")

    opcion = input("Elegí una opción: ")

    if opcion == "1":
        query = input("\nPregunta: ")
        
        # 3. Usar el logger
        logger.guardar_usuario(query)
        
        _, respuesta = rag.preguntar(query_text=query) 
        
        logger.guardar_bot(respuesta)
        
        print(f"\nRespuesta: {respuesta}")

    elif opcion == "2":
        audios = audio_handler.listar_audios()

        if not audios:
            print("\nNo hay audios en la carpeta.")
            continue

        print("\nProcesando audios...\n")

        for audio in audios:
            try:
                ruta_audio = str(audio.resolve())
                print(f" Procesando: {audio.name}")

                texto_leido, respuesta = rag.preguntar(audio_path=ruta_audio)
                
                # 4. Guardar datos del audio en el log
                logger.guardar_usuario(f"(AUDIO: {audio.name}) {texto_leido}")
                logger.guardar_bot(respuesta)

                print(f" Audio dice: {texto_leido}")
                print(f" Respuesta: {respuesta}\n")

            except Exception as e:
                print(f" Error en {audio.name}: {e}")

        limpiar = input("¿Eliminar audios procesados? (s/n): ")
        if limpiar.lower() == "s":
            audio_handler.limpiar_todos()
            print("Carpeta limpia.")

    elif opcion == "0":
        print("Cerrando sesión de chat...")
        break
    else:
        print("Opción inválida.")