from pathlib import Path
import numpy as np
import json
import time

from langchain_community.document_loaders import PyMuPDFLoader, CSVLoader
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Recursos locales
from vectorstore_manager import VectorStoreManager
from embedding_cache import EmbeddingCache
from ConfigManager import ConfigManager
from exceptions import RAGError
from error_codes import ErrorCode
from logging_config import get_logger

logger = get_logger("document_manager")


class DocumentManager:
    """
    Gestiona la ingesta de documentos (PDF/CSV), generación de embeddings,
    creación del vectorstore FAISS y detección de cambios por hash.
    """

    def __init__(self, api_key, folder_path="PDFs"):
        self.api_key = api_key
        # Resolvemos la ruta relativa a chatbotW/ (centralizada en paths.py)
        from paths import BASE_PATH
        self.folder_path = BASE_PATH / folder_path

        # Cache de embeddings para evitar llamadas redundantes
        self.cache = EmbeddingCache()

        # Modelo de embeddings de Google — configurable desde config_bot.json
        # NOTA: La API de Google necesita el prefijo "models/" internamente,
        # pero en config se guarda sin él para consistencia con el modelo de
        # generación. Lo agregamos acá al construir el cliente.
        config_manager = ConfigManager()
        raw_name = config_manager.config.get(
            "gemini_embeddings_model", "gemini-embedding-2-preview"
        )
        api_name = raw_name if raw_name.startswith("models/") else f"models/{raw_name}"
        self.embeddings_model = GoogleGenerativeAIEmbeddings(
            model=api_name,
            google_api_key=self.api_key
        )

    def setup_retriever(self):
        """
        Intenta cargar el vectorstore existente. Si no existe, procesa todos
        los PDFs y CSVs, genera embeddings y construye el índice FAISS.
        Retorna un retriever con k=10.
        """
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
        Retorna True si se detectaron cambios y se reconstruyó el retriever.
        Si setup_retriever() falla, captura la excepción y retorna False
        (el retriever anterior sigue activo).
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
            try:
                self.retriever = self.setup_retriever()
                logger.info("RAG memory updated successfully")
                return True
            except Exception as e:
                logger.warning(
                    "Failed to rebuild vectorstore, keeping stale retriever",
                    error_code=ErrorCode.RAG_QUERY_FAILED.value,
                    detail=str(e),
                )
                return False

        return False
