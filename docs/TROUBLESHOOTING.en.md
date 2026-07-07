# Troubleshooting Guide

Below are the solutions to the most common issues detected during the installation and execution process of the system.

---

## 1. The Bot does not start (Ports in use)
The system requires ports **5000**, **8000**, and **8080** to operate. If another application is using these ports, Docker will not be able to start the services.

*   **Verification:**
    *   On Linux/macOS systems: run `sudo lsof -i :5000` (replace 5000 with 8000 or 8080 to check the remaining ports).
*   **Solution:**
    *   Stop the process using the detected port.
    *   Alternatively, edit the `chatbotW/docker-compose.yml` file and reassign the ports in the `ports:` section (for example, changing `"5000:5000"` to `"5001:5000"`).

## 2. Issues with the Gemini API Key
If the bot starts but does not generate responses or reports authentication errors, the provided Google API key may be invalid or misconfigured.

*   **Verification:** Access the `chatbotW/.env` file and confirm that the value assigned to `GOOGLE_API_KEY` is correct.
*   **Action:** Generate a new credential at [Google AI Studio](https://aistudio.google.com/), update the `.env` file, and restart the containers by running:
    ```bash
    docker compose down
    docker compose up -d
    ```

## 3. Permission errors when running Docker
If when running the installation scripts you get a `permission denied` error when trying to access the Docker socket:

*   **Temporary solution:** Prepend `sudo` to the execution command (example: `sudo ./scripts/primera_instalacion.sh`).
*   **Recommended solution:** Add your user to the `docker` group to grant adequate privileges:
    ```bash
    sudo usermod -aG docker $USER
    ```
    *Note: You need to log out and back in for the changes to take effect.*

## 4. The system does not recognize the 'docker compose' command
Depending on the Docker installation, the command may be recognized as `docker-compose` (with a hyphen) or as a plugin `docker compose` (without a hyphen).

*   **Solution:** Verify the installed version using `docker compose version` or `docker-compose version`. If the script fails, edit the installation file and replace `docker compose` with `docker-compose` in all relevant references.

---

If problems persist, check the container logs to identify the specific error:
```bash
docker logs gemini_whatsapp_bot
```
