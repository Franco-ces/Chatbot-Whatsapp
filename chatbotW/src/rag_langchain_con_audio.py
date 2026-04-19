from pathlib import Path
import numpy as np

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate

# Recursos locales
from vectorstore_manager import VectorStoreManager
from embedding_cache import EmbeddingCache

# SDK GEMINI
from google import genai
from google.genai import types

class RAGLangchain:
    def __init__(self, api_key, folder_path="PDFs"):
        self.api_key = api_key
        self.folder_path = Path(__file__).resolve().parent.parent / folder_path
        self.cache = EmbeddingCache()
        
        # Inicializamos el cliente aquí para usarlo en el método preguntar
        self.client = genai.Client(api_key=self.api_key)
        
        # 1. Configuramos el retriever (Buscador de PDFs)
        self.retriever = self._setup_retriever()
        
        # 2. Definimos el prompt base
        self.prompt_template = ChatPromptTemplate.from_template("""
Sos un asistente experto en productos.
Respondé usando SOLO la información del contexto.
Si no encontrás la respuesta, decí: "No se encuentra en los documentos".

Contexto:
{context}

Pregunta:
{input}
""")

    def _setup_retriever(self):
        embeddings_model = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

        vectorstore = VectorStoreManager.cargar(embeddings_model, self.folder_path)

        if vectorstore is None:
            print("Creando vectorstore desde PDFs...")
            pdf_files = list(self.folder_path.glob("*.pdf"))
            if not pdf_files:
                raise Exception("No hay PDFs en la carpeta")

            docs = []
            for pdf in pdf_files:
                loader = PyMuPDFLoader(str(pdf))
                docs.extend(loader.load())

            splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
            splits = splitter.split_documents(docs)
            
            texts = [doc.page_content for doc in splits]
            vectors = []
            for text in texts:
                cached = self.cache.get(text)
                if cached is not None:
                    vectors.append(np.array(cached))
                else:
                    emb = embeddings_model.embed_query(text)
                    self.cache.set(text, emb)
                    vectors.append(emb)
            
            self.cache.save()
            vectorstore = FAISS.from_embeddings(list(zip(texts, vectors)), embeddings_model)
            VectorStoreManager.guardar(vectorstore, self.folder_path)

        return vectorstore.as_retriever()

    def preguntar(self, query_text=None, audio_path=None):
        """
        Maneja entradas de texto, de audio o ambas.
        Retorna: (transcripcion_o_query, respuesta_final)
        """
        # 1. DETERMINAR EL TEXTO DE BÚSQUEDA PARA EL RAG
        texto_para_buscar = query_text
        transcripcion_detectada = query_text # Para mostrar qué se leyó
        
        audio_part = None
        if audio_path:
            p = Path(audio_path)
            if p.exists():
                audio_part = types.Part.from_bytes(
                    data=p.read_bytes(),
                    mime_type="audio/ogg"
                )
                
                # Si el usuario NO escribió nada pero mandó audio
                if not texto_para_buscar:
                    res_t = self.client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[audio_part, "Transcribe la consulta de este audio de forma clara y directa."]
                    )
                    texto_para_buscar = res_t.text
                    transcripcion_detectada = res_t.text

        # 2. RAG: Buscar en los PDFs
        busqueda_final = texto_para_buscar if texto_para_buscar else "productos"
        docs = self.retriever.invoke(busqueda_final)
        contexto_docs = "\n\n".join(doc.page_content for doc in docs)

        # 3. PREPARAR EL PAQUETE PARA GEMINI
        prompt_final = self.prompt_template.format(
            context=contexto_docs,
            input=texto_para_buscar if texto_para_buscar else "Responde a la duda del audio."
        )

        contenidos_gemini = []
        if audio_part:
            contenidos_gemini.append(audio_part)
        
        contenidos_gemini.append(prompt_final)

        # 4. RESPUESTA FINAL
        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contenidos_gemini
        )

        # Devolvemos el texto detectado y la respuesta
        return transcripcion_detectada, response.text