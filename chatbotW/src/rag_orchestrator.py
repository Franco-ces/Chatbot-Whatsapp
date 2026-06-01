from pathlib import Path

from document_manager import DocumentManager
from query_processor import QueryProcessor
from ConfigManager import ConfigManager
from faq_matcher import FAQMatcher
from logging_config import get_logger

logger = get_logger("rag_orchestrator")


# Raíz del proyecto (un nivel arriba de /src) — donde vive faqs.json.
# Se calcula una sola vez al importar el módulo.
_ROOT_DIR = Path(__file__).resolve().parent.parent


class RAGOrchestrator:
    """
    Coordinador delgado que delega a DocumentManager y QueryProcessor.
    Preserva la interfaz pública de RAGLangchain para compatibilidad
    con main.py y bot_service.py.
    """

    def __init__(self, api_key, folder_path="PDFs"):
        # Creamos los componentes especializados
        self.doc_manager = DocumentManager(api_key, folder_path)

        # Construimos el FAQMatcher. Si algo falla (faqs.json corrupto,
        # API de embeddings caída, etc.) el bot DEBE seguir arrancando
        # — caemos a faq_matcher=None y el pipeline opera sólo con RAG.
        try:
            config_manager = ConfigManager()
            faq_matcher = FAQMatcher(
                faqs_path=_ROOT_DIR / "faqs.json",
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

    def actualizar_memoria(self):
        """
        Verifica cambios en archivos y refresca el retriever si es necesario.
        """
        actualizado = self.doc_manager.actualizar_memoria()
        if actualizado:
            self.retriever = self.doc_manager.setup_retriever()
        return actualizado
