import asyncio
from typing import Optional

from document_manager import DocumentManager
from query_processor import QueryProcessor
from ConfigManager import ConfigManager
from faq_matcher import FAQMatcher
from faq_paths import FAQS_PATH
from logging_config import get_logger

logger = get_logger("rag_orchestrator")


class RAGOrchestrator:
    """
    Orquestador de RAG (Retrieval Augmented Generation).
    
    Implementa el 'Patrón Facade' (Fachada) para proporcionar una interfaz única y 
    simplificada al sistema de recuperación de información. Su objetivo es 
    encapsular la complejidad de la interacción entre:
    
    - DocumentManager: Gestión de archivos, fragmentación y creación del índice FAISS.
    - QueryProcessor: Procesamiento de la consulta, aplicación de guardrails y generación.
    - FAQMatcher: Sistema de atajos semánticos para respuestas predefinidas.
    
    De esta manera, el resto de la aplicación (como bot_service.py) puede interactuar 
    con el sistema de conocimiento sin conocer los detalles internos de la implementación 
    de LangChain o los modelos de embeddings.
    """
    def __init__(self, api_key, folder_path="PDFs"):
        # Lock para serializar reconstrucciones concurrentes del vectorstore
        self._reload_lock = asyncio.Lock()

        # Creamos los componentes especializados
        self.doc_manager = DocumentManager(api_key, folder_path)

        # Construimos el FAQMatcher. Si algo falla (faqs.json corrupto,
        # API de embeddings caída, etc.) el bot DEBE seguir arrancando
        # — caemos a faq_matcher=None y el pipeline opera sólo con RAG.
        try:
            config_manager = ConfigManager()
            faq_matcher = FAQMatcher(
                faqs_path=FAQS_PATH,
                embeddings_model=self.doc_manager.embeddings_model,
                config_manager=config_manager,
                logger=logger,
            )
        except Exception as e:
            logger.warning(
                "FAQMatcher no se pudo inicializar, se continúa sin atajo de FAQ",
                detail=str(e),
            )
            faq_matcher = None

        self.query_processor = QueryProcessor(api_key, faq_matcher=faq_matcher)

        # La carpeta la resuelve DocumentManager
        self.folder_path = self.doc_manager.folder_path

        # Inicializamos el retriever
        self.retriever = self.doc_manager.setup_retriever()

    async def preguntar(self, query_text=None, audio_bytes=None, remitente=None, session_manager=None):
        """
        Delega la consulta al QueryProcessor con el retriever actual.
        """
        return await self.query_processor.procesar(
            query_text=query_text,
            audio_bytes=audio_bytes,
            retriever=self.retriever,
            folder_path=self.folder_path,
            remitente=remitente,
            session_manager=session_manager
        )

    def check_faq(self, texto: str) -> Optional[str]:
        """Devuelve la `respuesta` del FAQ si hay match arriba del threshold, si no None.

        Pensado para que `bot_service` consulte el FAQ ANTES del cache LRU
        de respuestas: el FAQ es la fuente de verdad que el operador edita
        en vivo, y un cache stale de respuestas pisaría al atajo (el caso
        clásico: el operador edita la respuesta en la UI, el usuario
        repregunta, el bot devuelve la respuesta vieja cacheada y el
        hot-reload del matcher nunca se ejecuta porque match() ni se
        llama). Si el FAQ matchea, el caller DEBE usar esa respuesta y
        NO cachearla (o usar una clave de cache que incluya la
        identidad del FAQ, no solo el texto).
        """
        if not texto or not texto.strip():
            return None
        if self.query_processor.faq_matcher is None:
            return None
        try:
            hit = self.query_processor.faq_matcher.match(texto)
        except Exception as e:
            logger.warning("FAQMatcher.match() lanzó excepción en check_faq", detail=str(e))
            return None
        return hit.respuesta if hit is not None else None

    async def actualizar_memoria(self):
        """
        Verifica cambios en archivos y refresca el retriever si es necesario.
        Serializado con _reload_lock para evitar reconstrucciones concurrentes.
        """
        async with self._reload_lock:
            actualizado = self.doc_manager.actualizar_memoria()
            if actualizado:
                logger.info("CSV/PDF change detected, rebuilding vectorstore")
                self.retriever = self.doc_manager.setup_retriever()
            return actualizado
