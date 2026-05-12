import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, BackgroundTasks

from rag_langchain_con_audio import RAGLangchain
from whatsapp_client import WhatsAppClient

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")
rag = RAGLangchain(api_key)

# Instanciamos el cliente de WhatsApp aislado
wa_client = WhatsAppClient(
    api_url="http://evolution_api:8080",
    api_key="franquitoGoat",
    instance_name="rag_bot"
)

app = FastAPI(title="Gemini WhatsApp Bot")

def procesar_y_responder(texto: str, remitente: str):
    print(f"--> [1] Iniciando consulta a Gemini para el número: {remitente}")
    try:
        # Obtenemos la respuesta del modelo
        transcripcion, respuesta_texto = rag.preguntar(texto)
        print(f"--> [2] Gemini respondió exitosamente: {respuesta_texto}")
        
        # Enviamos el mensaje
        print("--> [3] Enviando petición a Evolution API...")
        resultado = wa_client.enviar_mensaje(remitente, respuesta_texto)
        print(f"--> [4] Resultado final de Evolution API: {resultado}")
        
    except Exception as e:
        print(f"--> [ERROR CRÍTICO] Falló el proceso de fondo: {e}")

@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    
    print(f"PAYLOAD RECIBIDO: {payload}", flush=True)
    # Verificamos que sea el evento de recepción de mensajes
    if payload.get("event") == "messages.upsert":
        mensaje_data = payload.get("data", {}).get("message", {})
        remitente = payload.get("data", {}).get("key", {}).get("remoteJid")
        from_me = payload.get("data", {}).get("key", {}).get("fromMe")

        # Ignoramos los mensajes enviados por el propio bot para evitar bucles
        if from_me:
            return {"status": "ignorado"}

        # Evolution API manda el texto en distintos campos dependiendo si es un mensaje simple o con formato
        texto = mensaje_data.get("conversation") or mensaje_data.get("extendedTextMessage", {}).get("text")

        if texto:
            print(f"Mensaje entrante de {remitente}: {texto}")
            
            # Delegamos el procesamiento pesado a una tarea en segundo plano
            background_tasks.add_task(procesar_y_responder, texto, remitente)

    # FastAPI responde 200 OK inmediatamente
    return {"status": "recibido"}