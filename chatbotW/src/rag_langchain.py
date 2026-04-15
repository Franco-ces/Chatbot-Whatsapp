from pathlib import Path
import numpy as np
import os

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

from langchain_text_splitters import RecursiveCharacterTextSplitter

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from vectorstore_manager import VectorStoreManager
from embedding_cache import EmbeddingCache

#  OpenRouter via OpenAI SDK
from openai import OpenAI


class RAGLangchain:
    def __init__(self, api_key, folder_path="PDFs"):
        self.api_key = api_key
        self.folder_path = Path(__file__).resolve().parent.parent / folder_path
        
        #CREA LA CARPETA SI NO EXISTE
        self.folder_path.mkdir(parents=True, exist_ok=True)

        print("Ruta actual:", self.folder_path.resolve())
        print("PDFs encontrados:", list(self.folder_path.glob("*.pdf")))

        self.cache = EmbeddingCache()
        self.chain = self._build_chain()

    def _build_chain(self):

        #  Cliente OpenRouter
        client = OpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1"
        )

        #  Embeddings locales (gratis)
        embeddings_model = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

        vectorstore = VectorStoreManager.cargar(
            embeddings_model,
            self.folder_path
        )

        if vectorstore is None:
            print("Creando vectorstore...")

            pdf_files = list(self.folder_path.glob("*.pdf"))

            if not pdf_files:
                raise Exception("No hay PDFs en la carpeta")

            docs = []
            for pdf in pdf_files:
                loader = PyMuPDFLoader(str(pdf))
                docs.extend(loader.load())

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=500,
                chunk_overlap=50
            )

            splits = splitter.split_documents(docs)

            texts = [doc.page_content for doc in splits]

            vectors = []

            for text in texts:
                cached = self.cache.get(text)

                if cached is not None:
                    embedding = np.array(cached)
                else:
                    embedding = embeddings_model.embed_query(text)
                    self.cache.set(text, embedding)

                vectors.append(embedding)

            self.cache.save()

            vectorstore = FAISS.from_embeddings(
                list(zip(texts, vectors)),
                embeddings_model
            )

            VectorStoreManager.guardar(vectorstore, self.folder_path)

        retriever = vectorstore.as_retriever()

        prompt = ChatPromptTemplate.from_template("""
Sos un asistente experto en productos.

Respondé usando SOLO la información del contexto.
Si no encontrás la respuesta, decí: "No se encuentra en los documentos".

Priorizá:
- especificaciones técnicas
- precios
- características
- comparaciones entre productos

Contexto:
{context}

Pregunta:
{input}
""")

        def format_docs(docs):
            return "\n\n".join(doc.page_content for doc in docs)

        #  LLM OPENROUTER
        def llamar_llm(prompt_value):
            try:
                response = client.chat.completions.create(
                    model="google/gemma-4-26b-a4b-it:free",
                    messages=[
                        {"role": "user", "content": prompt_value.to_string()}
                    ]
                )
                return response.choices[0].message.content

            except Exception as e:
                return f"Error llamando al modelo: {e}"

        #  CHAIN FINAL
        chain = (
            {
                "context": RunnableLambda(lambda x: x["input"])
                           | retriever
                           | RunnableLambda(format_docs),
                "input": RunnableLambda(lambda x: x["input"])
            }
            | prompt
            | RunnableLambda(llamar_llm)
        )

        return chain

    def preguntar(self, query):
        return self.chain.invoke({"input": query})