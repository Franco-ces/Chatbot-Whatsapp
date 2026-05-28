import re
import time
from pathlib import Path
from chat_logger import ChatLogger


class SessionManager:
    """Maneja sesiones por número de teléfono.

    - Cada sesión tiene su propio ChatLogger (uno por contacto).
    - El logger acumula mensajes en memoria y los escribe a disco
      cuando la sesión expira (timeout de inactividad).
    - El identificador visible en los logs incluye el nombre y el
      número de teléfono: "Nombre (numero)" para permitir búsqueda
      por ambos.
    """

    def __init__(self, timeout_seconds=300, max_mensajes=6):
        # Mapa: { "telefono": { "logger": ChatLogger, "contexto": list,
        #                        "last_activity": float, "contact_name": str,
        #                        "phone_number": str } }
        self.sessions = {}
        self.timeout = timeout_seconds
        self.max_mensajes = max_mensajes

    # ------------------------------------------------------------------
    # Públicos
    # ------------------------------------------------------------------

    def crear_sesion(self, telefono, push_name=""):
        """Inicializa una nueva sesión para un número dado."""
        numero_limpio = self._limpiar_numero(telefono)

        # Usar push_name si tiene contenido real (no solo guiones, espacios, etc.)
        if push_name and self._es_nombre_valido(push_name):
            contact_name = push_name
        else:
            contact_name = numero_limpio

        # El nombre del archivo usa el formato: chat_{numero}_{nombre}.txt
        self.sessions[telefono] = {
            "logger": ChatLogger(phone_number=numero_limpio, contact_name=contact_name),
            "contexto": [],
            "last_activity": time.time(),
            "contact_name": contact_name,
            "phone_number": numero_limpio,
        }
        return self.sessions[telefono]

    def obtener_sesion(self, telefono):
        """Busca una sesión. Retorna None si no existe."""
        return self.sessions.get(telefono)

    def agregar_mensaje(self, telefono, mensaje, es_bot=False, push_name=""):
        """Agrega mensaje al logger y resetea el timer de inactividad."""
        sesion = self.obtener_sesion(telefono)
        if not sesion:
            sesion = self.crear_sesion(telefono, push_name)

        # Identificador visible: "Nombre (numero)" así se puede buscar por ambos
        nombre = sesion.get("contact_name", telefono)
        numero = sesion.get("phone_number", "")
        identificador = f"{nombre} ({numero})" if numero else nombre

        # 1. Guardar en el buffer del logger
        if es_bot:
            sesion["logger"].guardar_bot(mensaje)
        else:
            sesion["logger"].guardar_usuario(mensaje, identificador=identificador)

        # 2. Actualizar el contexto en memoria
        rol = "BOT" if es_bot else "USER"
        sesion["contexto"].append(f"{rol}: {mensaje}")

        if len(sesion["contexto"]) > self.max_mensajes:
            sesion["contexto"].pop(0)

        # 3. Reset del timer de inactividad
        sesion["last_activity"] = time.time()

    def obtener_contexto(self, telefono):
        """Retorna el string de contexto acumulado en memoria."""
        sesion = self.obtener_sesion(telefono)

        if not sesion or not sesion["contexto"]:
            return ""

        return "\n".join(sesion["contexto"]) + "\n"

    def leer_ultimos_mensajes(self, telefono, cantidad=10):
        """Lee los últimos N mensajes: los del disco + los del buffer en memoria.

        Formato de cada línea del log/buffer:
            {role}|||{identifier}|||{time}|||{message}

        Retorna una lista de dicts:
            [{"role": "USER", "message": "...", "time": "..."}, ...]
        """
        sesion = self.obtener_sesion(telefono)
        if not sesion:
            return []

        mensajes = []

        # 1. Leer mensajes del disco (sesiones anteriores)
        log_file = sesion["logger"].log_file
        if log_file.exists():
            try:
                lineas = log_file.read_text(encoding="utf-8").splitlines()
                for linea in lineas:
                    parsed = self._parsear_linea_log(linea)
                    if parsed:
                        mensajes.append(parsed)
            except Exception:
                pass

        # 2. Agregar mensajes del buffer en memoria (sesión actual)
        for linea in sesion["logger"].buffer:
            parsed = self._parsear_linea_log(linea)
            if parsed:
                mensajes.append(parsed)

        # Retornar los últimos N
        return mensajes[-cantidad:] if len(mensajes) > cantidad else mensajes

    @staticmethod
    def _parsear_linea_log(linea):
        """Parsea una línea del log con formato {role}|||{ident}|||{time}|||{msg}."""
        partes = linea.strip().split("|||")
        if len(partes) < 4:
            return None
        role_raw, _ident, hora, mensaje = partes[0], partes[1], partes[2], partes[3]
        if role_raw == "id_usuario":
            role = "USER"
        elif role_raw == "id_bot":
            role = "BOT"
        else:
            return None
        return {"role": role, "message": mensaje, "time": hora}

    def limpiar_sesiones_expiradas(self):
        """Recorre el mapa y finaliza sesiones inactivas (> timeout sin mensajes)."""
        ahora = time.time()
        llaves_a_eliminar = []

        for telefono, data in self.sessions.items():
            if (ahora - data["last_activity"]) > self.timeout:
                data["logger"].finalizar_log()       # flush + cierre
                llaves_a_eliminar.append(telefono)

        for telefono in llaves_a_eliminar:
            nombre = self.sessions[telefono].get("contact_name", telefono)
            del self.sessions[telefono]
            print(f"🧹 Sesión inactiva cerrada por timeout: {nombre} ({telefono})")

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    @staticmethod
    def _limpiar_numero(jid: str) -> str:
        """Extrae solo el número del JID de WhatsApp.

        Ej: '2262337131@s.whatsapp.net' → '2262337131'
        """
        return re.sub(r'@.*$', '', jid).strip()

    @staticmethod
    def _es_nombre_valido(nombre: str) -> bool:
        """Verifica que el nombre tenga al menos un carácter alfanumérico.

        Filtra push_names que solo contienen guiones, puntos, guiones bajos, etc.
        Ej: '-', '_', '.', '---' → False
        Ej: 'Juan', 'Juan Pérez', 'A' → True
        """
        return bool(re.search(r'[a-zA-Z0-9áéíóúñÁÉÍÓÚÑ]', nombre))
