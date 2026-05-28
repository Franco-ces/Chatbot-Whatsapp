import csv
from pathlib import Path
import sys

def verificar_datos():
    # Obtiene la ruta de la carpeta CSVs (asumiendo que este script esta en src/)
    base_path = Path(__file__).resolve().parent.parent
    csvs_path = base_path / "CSVs"
    
    if not csvs_path.exists():
        print("[ERROR] La carpeta 'CSVs' no existe en la ruta esperada.")
        sys.exit(1)
        
    # Verificar archivos CSV
    archivos_csv = list(csvs_path.glob("*.csv"))
    if not archivos_csv:
        print("[ADVERTENCIA] No se encontraron archivos .csv en la carpeta CSVs.")
    
    for archivo in archivos_csv:
        try:
            with open(archivo, "r", encoding="utf-8") as f:
                lector = csv.reader(f)
                filas = list(lector)
                if not filas:
                    print(f"[ADVERTENCIA] El archivo CSV {archivo.name} esta vacio.")
                else:
                    print(f"[OK] CSV '{archivo.name}' validado correctamente ({len(filas)} filas).")
        except UnicodeDecodeError:
            print(f"[ERROR] de codificacion en {archivo.name}: El archivo debe estar guardado como UTF-8.")
            sys.exit(1)
        except Exception as e:
            print(f"[ERROR] al leer o procesar el CSV {archivo.name}: {e}")
            sys.exit(1)
            
    print("\n[EXITO] ¡Todos los datos han pasado la validacion exitosamente!")

if __name__ == "__main__":
    print("="*50)
    print("Iniciando validacion de datos (CSV)...")
    print("="*50)
    verificar_datos()
