# src/price_lookup.py
"""
Búsqueda de precios en archivos CSV con tolerancia a errores tipográficos.
"""
import csv
import os
from difflib import SequenceMatcher
from logging_config import get_logger

logger = get_logger("price_lookup")

# Umbral mínimo para considerar un match difuso (0.0 - 1.0)
FUZZY_THRESHOLD = 0.6


def _similarity(a: str, b: str) -> float:
    """Return similarity ratio between two strings."""
    return SequenceMatcher(None, a, b).ratio()


def _matches(query: str, producto: str, categoria: str) -> bool:
    """Check if query matches product or category (exact substring or fuzzy)."""
    # Exact substring match (fast path)
    if query in producto or query in categoria:
        return True

    # Fuzzy match: split query into words and check each
    query_words = query.split()
    for word in query_words:
        if len(word) < 3:
            # Skip short words for fuzzy (too many false positives)
            if word in producto or word in categoria:
                continue
            continue
        # Check similarity against product and category
        if _similarity(word, producto) >= FUZZY_THRESHOLD:
            return True
        if _similarity(word, categoria) >= FUZZY_THRESHOLD:
            return True

    return False


def buscar_precios(texto_busqueda: str, folder_path) -> str:
    """Search for products matching the query in CSV files.

    Args:
        texto_busqueda: User's search query.
        folder_path: Path to the CSVs folder.

    Returns:
        Formatted string with matching products, or a no-results message.
    """
    if not texto_busqueda:
        texto_busqueda = ""

    texto_lower = texto_busqueda.lower().strip()
    resultados = []

    # Read all CSV files in the folder
    if not os.path.isdir(folder_path):
        logger.warning("CSV folder not found: %s", folder_path)
        return "No se encontró la carpeta de precios."

    for filename in os.listdir(folder_path):
        if not filename.endswith(".csv"):
            continue

        filepath = os.path.join(folder_path, filename)
        try:
            with open(filepath, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    producto = row.get("producto", "").lower()
                    categoria = row.get("categoria", "").lower()

                    if _matches(texto_lower, producto, categoria):
                        resultados.append({
                            "id": row.get("id", ""),
                            "producto": row.get("producto", ""),
                            "categoria": row.get("categoria", ""),
                            "precio": row.get("precio", ""),
                            "stock": row.get("stock", ""),
                        })
        except Exception as e:
            logger.error("Error reading CSV %s: %s", filename, e)

    if not resultados:
        return "No se encontraron productos que coincidan con la búsqueda."

    # Format results
    lineas = []
    for r in resultados:
        precio = f"${int(r['precio']):,}".replace(",", ".")
        stock = r["stock"]
        estado = "Disponible" if int(stock) > 0 else "Sin stock"
        lineas.append(
            f"- {r['producto']} ({r['categoria']}): {precio} | Stock: {stock} ({estado})"
        )

    return "\n".join(lineas)
