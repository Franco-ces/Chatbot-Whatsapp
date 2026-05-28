import asyncio

from price_lookup import buscar_precios
from logging_config import get_logger

logger = get_logger("context_builder")


async def construir_contexto(retriever, texto_busqueda: str, folder_path) -> str:
    """Combine RAG docs and price data into unified context.

    Args:
        retriever: FAISS vector store retriever.
        texto_busqueda: User's search query text.
        folder_path: Path to PDFs/precios folder.

    Returns:
        Combined context string with manuals + prices sections.
    """
    # 1. RAG document retrieval (via asyncio.to_thread for thread safety)
    busqueda_final = texto_busqueda if texto_busqueda else "productos"
    docs = await asyncio.to_thread(retriever.invoke, busqueda_final)
    contexto_docs = "\n\n".join(doc.page_content for doc in docs)

    # 2. Price lookup
    contexto_precios = buscar_precios(texto_busqueda, folder_path)

    # 3. Combine both contexts
    contexto_total = f"--- MANUALES TÉCNICOS Y DETALLES ---\n{contexto_docs}\n\n--- INFORMACIÓN COMERCIAL (PRECIOS Y STOCK) ---\n{contexto_precios}"

    return contexto_total
