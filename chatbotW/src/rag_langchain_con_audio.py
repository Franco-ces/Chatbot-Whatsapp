from pathlib import Path
import numpy as np
import json

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate

# Recursos locales
from vectorstore_manager import VectorStoreManager
from embedding_cache import EmbeddingCache
from ConfigManager import ConfigManager
# SDK GEMINI
from google import genai
from google.genai import types

class RAGLangchain:
    def __init__(self, api_key, folder_path="PDFs"):
        self.api_key = api_key
        # Ajustamos la ruta para que siempre encuentre la carpeta PDFs
        self.folder_path = Path(__file__).resolve().parent.parent / folder_path
        self.cache = EmbeddingCache()

        #gestion de donde se guarda el Mail y Telefono del cliente
        self.config_manager = ConfigManager()
        
        # Inicializamos el cliente aquí para usarlo en el método preguntar
        self.client = genai.Client(api_key=self.api_key)
        
        # 1. Configuramos el retriever (Buscador de PDFs)
        self.retriever = self._setup_retriever()
        
        # 2. Definimos el prompt base
        self.prompt_template = ChatPromptTemplate.from_template("""
Eres un Asistente Virtual de Atención al Cliente profesional y preciso. 
Tu objetivo es ayudar a los usuarios basándote EXCLUSIVAMENTE en el contexto proporcionado.

### REGLAS CRÍTICAS DE COMPORTAMIENTO:
1. NO INVENTES INFORMACIÓN: Si la respuesta no está presente de forma explícita en el contexto, indica amablemente: "Lo siento, no cuento con esa información específica. Puedes ponerte en contacto a través del correo electrónico {email} o llamando al teléfono {telefono}."
2. LÍMITE DE CONTEXTO: Utiliza únicamente los fragmentos de texto entregados abajo. No utilices conocimientos externos ni supongas detalles que no estén escritos.
3. PRECISIÓN TÉCNICA: Si el contexto menciona precios, códigos o especificaciones, cítalos con exactitud.
4. TONO: Mantén un tono servicial, profesional y directo.
5. CASO DE RESPUESTA ERRONEA : si habla sobre el producto, respondele de manera profecional que no cuentas con esa informacion, no incluyas cosas como que no se encuentra en tu "memoria o contexto" intenta responder como una persona que no cuentas con esa informacion.

### CONTEXTO DE DOCUMENTOS:
{context}

### INSTRUCCIÓN DE CONSULTA:
Analiza el contexto anterior y responde la siguiente pregunta del cliente. Si la pregunta es un saludo, responde cordialmente y pregunta en qué puedes ayudar.

Pregunta del Cliente: {input}

Respuesta del Asistente:""")

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

    def actualizar_memoria(self):
        """
        Verifica rápidamente si hubo cambios en la carpeta de PDFs.
        """
        # 1. Calculamos el hash de los archivos actuales
        hash_actual = VectorStoreManager.calcular_hash_archivos(self.folder_path)
        
        # 2. Leemos el hash guardado
        metadata_path = VectorStoreManager._get_metadata_path()
        hash_guardado = None
        
        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
                hash_guardado = metadata.get("hash")
        
        # 3. Si hay cambios, recargamos el retriever
        if hash_actual != hash_guardado:
            print("🔄 Cambio detectado en los PDFs. Actualizando memoria del RAG...")
            self.retriever = self._setup_retriever()
            print("✅ Memoria RAG actualizada con éxito.")
            return True
        
        return False

    def preguntar(self, query_text=None, audio_path=None):
        """
        Maneja entradas de texto, de audio o ambas.
        """
        texto_para_buscar = query_text
        transcripcion_detectada = query_text
        
        audio_part = None
        if audio_path:
            p = Path(audio_path)
            if p.exists():
                audio_part = types.Part.from_bytes(
                    data=p.read_bytes(),
                    mime_type="audio/ogg"
                )
                
                if not texto_para_buscar:
                    res_t = self.client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[audio_part, "Transcribe textualmente la consulta de este audio de forma clara y directa."]
                    )
                    texto_para_buscar = res_t.text
                    transcripcion_detectada = res_t.text

        # Búsqueda en RAG
        busqueda_final = texto_para_buscar if texto_para_buscar else "productos"
        docs = self.retriever.invoke(busqueda_final)
        contexto_docs = "\n\n".join(doc.page_content for doc in docs)

        #lee el disco por si la interfaz cambió algo
        self.config_manager.cargar()

        # Prompt para Gemini
        prompt_final = self.prompt_template.format(
            context=contexto_docs,
            input=texto_para_buscar if texto_para_buscar else "Responde a la duda del audio.",
            email=self.config_manager.config["email"],     
            telefono=self.config_manager.config["telefono"]
        )

        contenidos_gemini = []
        if audio_part:
            contenidos_gemini.append(audio_part)
        contenidos_gemini.append(prompt_final)

        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contenidos_gemini
        )

        return transcripcion_detectada, response.text