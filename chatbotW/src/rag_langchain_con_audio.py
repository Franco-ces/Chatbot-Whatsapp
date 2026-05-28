from pathlib import Path
import numpy as np
import json
import time

from langchain_community.document_loaders import PyMuPDFLoader, CSVLoader
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import ChatGoogleGenerativeAI

# Recursos locales
from vectorstore_manager import VectorStoreManager
from embedding_cache import EmbeddingCache
from ConfigManager import ConfigManager
from audio_handler import AudioProcessor
from exceptions import RAGError
from error_codes import ErrorCode
# SDK GEMINI
from google import genai
from google.genai import types
from prompts import PROMPT_ASISTENTE_VIRTUAL
from logging_config import get_logger
from guardrails import evaluar_guardrail_entrada, evaluar_guardrail_salida
from context_builder import construir_contexto

logger = get_logger("rag")

class RAGLangchain:
    def __init__(self, api_key, folder_path="PDFs"):
        self.api_key = api_key
        # Ajustamos la ruta para que siempre encuentre la carpeta PDFs
        self.folder_path = Path(__file__).resolve().parent.parent / folder_path
        self.cache = EmbeddingCache()

        # gestion de donde se guarda el Mail y Telefono del cliente
        self.config_manager = ConfigManager()
        
        # Inicializamos el cliente aquí para usarlo en el método preguntar
        self.client = genai.Client(api_key=self.api_key)

        # Inicializamos el modelo de embeddings de Google
        self.embeddings_model = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-2-preview", 
            google_api_key=self.api_key
        )

        # Inicializar el procesador de audio
        self.audio_processor = AudioProcessor(self.client)
        
        # 1. Configuramos el retriever (Buscador de PDFs)
        self.retriever = self._setup_retriever()

        # LLM auxiliar para Guardrails con Langchain
        self.llm_guardrail = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", google_api_key=self.api_key)
        
        # 2. Definimos el prompt base
        self.prompt_template = PROMPT_ASISTENTE_VIRTUAL

    def _setup_retriever(self):
        # Intentamos cargar el vectorstore existente con el nuevo modelo
        vectorstore = VectorStoreManager.cargar(self.embeddings_model, self.folder_path)

        if vectorstore is None:
            logger.info("Creating vectorstore from documents...")
            pdf_files = list(self.folder_path.glob("*.pdf"))
            csv_folder = self.folder_path.parent / "CSVs"
            csv_files = list(csv_folder.glob("*.csv")) if csv_folder.exists() else []

            if not pdf_files and not csv_files:
                raise RAGError(ErrorCode.RAG_NO_PDFS, detail="No hay PDFs ni CSVs en las carpetas")

            docs = []
            
            # Cargar PDFs
            for pdf in pdf_files:
                loader = PyMuPDFLoader(str(pdf))
                docs.extend(loader.load())
            
            # Cargar CSVs
            for csv_file in csv_files:
                try:
                    loader = CSVLoader(str(csv_file))
                    docs.extend(loader.load())
                except Exception as e:
                    logger.warning("Error loading CSV", file=str(csv_file), detail=str(e))

            # Subimos a 1000 el chunk de los manuales para mejor contexto narrativo
            splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
            splits = splitter.split_documents(docs)
            
            texts = [doc.page_content for doc in splits]
            vectors = []
            logger.info("Processing text fragments", count=len(texts))
            for i, text in enumerate(texts):
                cached = self.cache.get(text)
                if cached is not None:
                    vectors.append(np.array(cached))
                else:
                    emb = self.embeddings_model.embed_query(text)
                    self.cache.set(text, emb)
                    vectors.append(emb)
                    time.sleep(0.5)
            
            self.cache.save()
            vectorstore = FAISS.from_embeddings(list(zip(texts, vectors)), self.embeddings_model)
            VectorStoreManager.guardar(vectorstore, self.folder_path)

        return vectorstore.as_retriever(search_kwargs={"k": 10})

    def actualizar_memoria(self):
        """
        Verifica rápidamente si hubo cambios en la carpeta de PDFs o Precios.
        """
        hash_actual = VectorStoreManager.calcular_hash_archivos(self.folder_path)
        metadata_path = VectorStoreManager._get_metadata_path()
        hash_guardado = None
        
        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
                hash_guardado = metadata.get("hash")
        
        if hash_actual != hash_guardado:
            logger.info("Change detected in files, updating RAG memory")
            self.retriever = self._setup_retriever()
            logger.info("RAG memory updated successfully")
            return True
        
        return False

    async def preguntar(self, query_text=None, audio_bytes=None, remitente=None, session_manager=None):
        """
        Maneja entradas de texto, de audio en memoria o ambas de forma híbrida (RAG + JSON).
        Si se provee session_manager, inyecta el historial de conversación en el prompt.
        """
        texto_para_buscar = query_text if query_text else ""
        transcripcion_detectada = query_text
        audio_part = None
        
        # Procesamiento desacoplado enteramente en memoria
        if audio_bytes:
            texto_extraido, audio_part = await self.audio_processor.extraer_transcripcion_memoria(audio_bytes)
            if not texto_para_buscar and texto_extraido:
                texto_para_buscar = texto_extraido
                transcripcion_detectada = texto_extraido

        # --- GUARDRAIL DE ENTRADA ---
        es_seguro, mensaje_rechazo = await evaluar_guardrail_entrada(
            texto_para_buscar if texto_para_buscar else "audio",
            self.llm_guardrail
        )
        if not es_seguro:
            return transcripcion_detectada, mensaje_rechazo

        # --- CONTEXTO (RAG + PRECIOS) ---
        contexto_total = await construir_contexto(
            self.retriever, texto_para_buscar, self.folder_path
        )

        # --- HISTORIAL DE CONVERSACIÓN (últimos 10 mensajes) ---
        historial_texto = ""
        if session_manager and remitente:
            historial = session_manager.leer_ultimos_mensajes(remitente, cantidad=10)
            if historial:
                lineas = []
                for msg in historial:
                    rol = "Usuario" if msg["role"] == "USER" else "Asistente"
                    lineas.append(f"[{msg['time']}] {rol}: {msg['message']}")
                historial_texto = "\n".join(lineas)

        # lee el disco por si la interfaz cambió algo
        self.config_manager.cargar()

        # Preparamos las instrucciones de sistema pasándole el contexto unificado
        instrucciones_sistema = self.prompt_template.format(
            history=historial_texto if historial_texto else "Sin historial previo.",
            context=contexto_total,
            input=texto_para_buscar if texto_para_buscar else "Responde a la duda del audio.",
            email=self.config_manager.config["email"],     
            telefono=self.config_manager.config["telefono"]
        )

        mensaje_usuario = texto_para_buscar if texto_para_buscar else "Audio adjunto. Por favor responder."

        contenidos_gemini = []
        if audio_part:
            contenidos_gemini.append(audio_part)
        contenidos_gemini.append(mensaje_usuario)

        response = await self.client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=contenidos_gemini,
            config=types.GenerateContentConfig(
                system_instruction=instrucciones_sistema
            )
        )
        respuesta_texto = response.text

        # --- GUARDRAIL DE SALIDA ---
        es_aceptado, mensaje_rechazo_salida = await evaluar_guardrail_salida(
            respuesta_texto, contexto_total, self.llm_guardrail
        )
        if not es_aceptado:
            return transcripcion_detectada, mensaje_rechazo_salida

        return transcripcion_detectada, respuesta_texto
