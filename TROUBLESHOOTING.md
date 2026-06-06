# Guía de Resolución de Problemas

A continuación se describen las soluciones a los inconvenientes más frecuentes detectados durante el proceso de instalación y ejecución del sistema.

---

## 1. El Bot no inicia (Puertos ocupados)
El sistema requiere los puertos **5000**, **8000** y **8080** para su funcionamiento. Si otra aplicación se encuentra utilizando estos puertos, Docker no podrá levantar los servicios.

*   **Verificación:**
    *   En sistemas Linux/macOS: ejecute `sudo lsof -i :5000` (reemplace 5000 por 8000 u 8080 para verificar los puertos restantes).
*   **Solución:**
    *   Detenga el proceso que esté utilizando el puerto detectado.
    *   Alternativamente, edite el archivo `chatbotW/docker-compose.yml` y reasigne los puertos en la sección `ports:` (por ejemplo, cambiando `"5000:5000"` por `"5001:5000"`).

## 2. Inconvenientes con la clave de API de Gemini
Si el bot inicia pero no genera respuestas o reporta errores de autenticación, es posible que la clave de API de Google proporcionada sea inválida o esté mal configurada.

*   **Verificación:** Acceda al archivo `chatbotW/.env` y confirme que el valor asignado a `GOOGLE_API_KEY` sea correcto.
*   **Acción:** Genere una nueva credencial en [Google AI Studio](https://aistudio.google.com/), actualice el archivo `.env` y reinicie los contenedores ejecutando:
    ```bash
    docker compose down
    docker compose up -d
    ```

## 3. Errores de permisos al ejecutar Docker
Si al ejecutar los scripts de instalación se obtiene un error de `permission denied` al intentar acceder al socket de Docker:

*   **Solución temporal:** Anteponga `sudo` al comando de ejecución (ejemplo: `sudo ./primera_instalacion.sh`).
*   **Solución recomendada:** Incorpore su usuario al grupo `docker` para otorgar privilegios adecuados:
    ```bash
    sudo usermod -aG docker $USER
    ```
    *Nota: Es necesario cerrar sesión y volver a ingresar para que los cambios surtan efecto.*

## 4. El sistema no reconoce el comando 'docker compose'
Dependiendo de la instalación de Docker, el comando puede reconocerse como `docker-compose` (con guion) o como un plugin `docker compose` (sin guion).

*   **Solución:** Verifique la versión instalada mediante `docker compose version` o `docker-compose version`. Si el script falla, edite el archivo de instalación y sustituya `docker compose` por `docker-compose` en todas las referencias pertinentes.

---

Si los problemas persisten, consulte los registros de los contenedores para identificar el error específico:
```bash
docker logs gemini_whatsapp_bot
```

