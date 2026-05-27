import re
import time
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
        contact_name = push_name or numero_limpio  # fallback: el número si no hay nombre

        # El nombre del archivo usa solo el nombre (sin número)
        self.sessions[telefono] = {
            "logger": ChatLogger(contact_name=contact_name),
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
        """Retorna el string de contexto acumulado."""
        sesion = self.obtener_sesion(telefono)

        if not sesion or not sesion["contexto"]:
            return ""

        return "\n".join(sesion["contexto"]) + "\n"

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
