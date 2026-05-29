from document_manager import DocumentManager
from query_processor import QueryProcessor
from logging_config import get_logger

logger = get_logger("rag_orchestrator")


class RAGOrchestrator:
    """
    Coordinador delgado que delega a DocumentManager y QueryProcessor.
    Preserva la interfaz pública de RAGLangchain para compatibilidad
    con main.py y bot_service.py.
    """

    def __init__(self, api_key, folder_path="PDFs"):
        # Creamos los componentes especializados
        self.doc_manager = DocumentManager(api_key, folder_path)
        self.query_processor = QueryProcessor(api_key)

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
