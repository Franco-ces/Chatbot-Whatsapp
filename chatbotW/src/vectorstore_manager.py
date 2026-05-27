from pathlib import Path
import json
import hashlib
from langchain_community.vectorstores import FAISS


class VectorStoreManager:

    @staticmethod
    def _get_base_path():
        return Path(__file__).resolve().parent.parent

    @staticmethod
    def _get_vectorstore_path():
        base_path = VectorStoreManager._get_base_path()
        vs_path = base_path / "vectorstore"
        vs_path.mkdir(parents=True, exist_ok=True)
        return vs_path

    @staticmethod
    def _get_metadata_path():
        return VectorStoreManager._get_vectorstore_path() / "metadata.json"

    @staticmethod
    def calcular_hash_archivos(folder_path):
        # Busca dinámicamente tanto PDFs como el JSON de precios
        extensiones = ["*.pdf", "*.json"]
        archivos = []
        
        for ext in extensiones:
            archivos.extend(Path(folder_path).glob(ext))
            
        csv_folder = Path(folder_path).parent / "CSVs"
        if csv_folder.exists():
            archivos.extend(csv_folder.glob("*.csv"))
            
        archivos = sorted(archivos)
        hash_total = hashlib.md5()

        for archivo in archivos:
            hash_total.update(archivo.name.encode())
            hash_total.update(str(archivo.stat().st_mtime).encode())

        return hash_total.hexdigest()

    @staticmethod
    def guardar(vectorstore, folder_path):
        vs_path = VectorStoreManager._get_vectorstore_path()
        metadata_path = VectorStoreManager._get_metadata_path()

        # Guardar FAISS
        vectorstore.save_local(str(vs_path))

        # Guardar hash
        hash_actual = VectorStoreManager.calcular_hash_archivos(folder_path)

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump({"hash": hash_actual}, f, indent=2)

    @staticmethod
    def cargar(embeddings, folder_path):
        vs_path = VectorStoreManager._get_vectorstore_path()
        metadata_path = VectorStoreManager._get_metadata_path()

        if not vs_path.exists() or not metadata_path.exists():
            return None

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Advertencia: metadata.json corrupto ({e}). Reconstruyendo...")
            return None

        hash_guardado = metadata.get("hash")
        hash_actual = VectorStoreManager.calcular_hash_archivos(folder_path)

        if hash_guardado != hash_actual:
            print("Cambios detectados en PDFs. Reconstruyendo índice...")
            return None

        print("Vectorstore actualizado. Cargando desde disco...")

        try:
            return FAISS.load_local(
                str(vs_path),
                embeddings,
                allow_dangerous_deserialization=True
            )
        except Exception as e:
            print(f"Advertencia: no se pudo cargar el vectorstore ({e}). Reconstruyendo...")
            return None