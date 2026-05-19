import base64

def procesar_mensaje_bot(rag_instance, wa_client, remitente: str, texto: str, mensaje_data: dict, es_audio: bool):
    """
    Ejecuta el ciclo de vida del bot: obtiene audio (si aplica), consulta al RAG y envía la respuesta.
    """
    print(f"--> [1] Iniciando consulta para: {remitente}")
    try:
        audio_bytes = None
        
        # Procesamiento de audio bajo demanda
        if es_audio:
            print("--> [Audio detectado] Descargando desde Evolution API en memoria...")
            audio_b64 = wa_client.obtener_audio_base64(mensaje_data)
            if audio_b64:
                audio_bytes = base64.b64decode(audio_b64)

        # Invocamos al RAG
        transcripcion, respuesta_texto = rag_instance.preguntar(
            query_text=texto, 
            audio_bytes=audio_bytes, 
            remitente=remitente
        )
        
        print(f"--> [2] Gemini respondió exitosamente: {respuesta_texto}")
        
        # Enviamos la respuesta
        print("--> [3] Enviando petición a Evolution API...")
        resultado = wa_client.enviar_mensaje(remitente, respuesta_texto)
        print(f"--> [4] Resultado final: {resultado}")
        
    except Exception as e:
        print(f"--> [ERROR CRÍTICO] Falló el proceso de fondo: {e}")