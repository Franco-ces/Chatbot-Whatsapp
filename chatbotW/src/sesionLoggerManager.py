import time
from chat_logger import ChatLogger

class SessionManager:
    # Agregamos la variable max_mensajes inicializada en 6
    def __init__(self, timeout_seconds=300, max_mensajes=6): 
        # El mapa almacenará: { "telefono": { "logger": ChatLogger, "contexto": list, "last_activity": float } }
        self.sessions = {}
        self.timeout = timeout_seconds
        self.max_mensajes = max_mensajes

    def crear_sesion(self, telefono):
        """Inicializa una nueva sesión para un número dado."""
        self.sessions[telefono] = {
            "logger": ChatLogger(),
            "contexto": [], # Ahora es una LISTA para administrar la cantidad de mensajes
            "last_activity": time.time() # Timer inicial
        }
        return self.sessions[telefono]

    def obtener_sesion(self, telefono):
        """Busca una sesión. Retorna None si no existe."""
        # Solo busca, ya NO resetea el tiempo.
        return self.sessions.get(telefono)

    def agregar_mensaje(self, telefono, mensaje, es_bot=False):
        """Agrega mensaje al logger y resetea el timer de inactividad."""
        sesion = self.obtener_sesion(telefono)
        if not sesion:
            sesion = self.crear_sesion(telefono)

        # 1. Guardar en el archivo físico
        if es_bot:
            sesion["logger"].guardar_bot(mensaje)
        else:
            # Aprovechamos y le pasamos el teléfono para que aparezca en el panel web
            sesion["logger"].guardar_usuario(mensaje, identificador=telefono)

        # 2. Actualizar el contexto en memoria
        rol = "BOT" if es_bot else "USER"
        
        # Agregamos el nuevo mensaje al final de la lista
        sesion["contexto"].append(f"{rol}: {mensaje}")
        
        # Si nos pasamos del límite (ej. 6), borramos el elemento 0 (el más viejo)
        if len(sesion["contexto"]) > self.max_mensajes:
            sesion["contexto"].pop(0)
        
        # 3. RESETEO DEL TIMER: Solo ocurre cuando de verdad hay un mensaje nuevo
        sesion["last_activity"] = time.time()

    def obtener_contexto(self, telefono):
        """Retorna el string de contexto acumulado."""
        sesion = self.obtener_sesion(telefono)
        
        if not sesion or not sesion["contexto"]:
            return ""
            
        # Unimos la lista convirtiéndola nuevamente en un string 
        # y le agregamos un \n al final para respetar el formato que pediste.
        return "\n".join(sesion["contexto"]) + "\n"

    def limpiar_sesiones_expiradas(self):
        """Recorre el mapa y elimina sesiones inactivas (más de 5 mins sin mensajes)."""
        ahora = time.time()
        llaves_a_eliminar = []

        for telefono, data in self.sessions.items():
            # Si el tiempo actual menos el último mensaje es mayor a 300s...
            if (ahora - data["last_activity"]) > self.timeout:
                # Primero cerramos el log físicamente
                data["logger"].finalizar_log()
                llaves_a_eliminar.append(telefono)

        # Eliminamos del diccionario
        for telefono in llaves_a_eliminar:
            del self.sessions[telefono]
            print(f"🧹 Sesión inactiva cerrada por timeout: {telefono}")