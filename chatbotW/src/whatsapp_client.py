import requests

class WhatsAppClient:
    def __init__(self, api_url: str, api_key: str, instance_name: str):
        self.api_url = api_url
        self.api_key = api_key
        self.instance_name = instance_name
        self.headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }

    def enviar_mensaje(self, numero: str, texto: str):
        url = f"{self.api_url}/message/sendText/{self.instance_name}"
        
        # Estructura actualizada para Evolution API v2
        payload = {
            "number": numero,
            "text": texto,
            "delay": 2500
        }
        
        try:
            response = requests.post(url, json=payload, headers=self.headers)
            
            # Capturamos y mostramos el error exacto si Evolution API rechaza el payload
            if response.status_code not in [200, 201]:
                print(f"\n[ERROR EVOLUTION API] Código {response.status_code}")
                print(f"Detalle del rechazo: {response.text}\n")
                return None
                
            return response.json()
        except Exception as e:
            print(f"Error en WhatsAppClient al conectar con Evolution: {e}")
            return None