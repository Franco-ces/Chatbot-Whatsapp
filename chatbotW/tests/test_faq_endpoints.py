"""Tests para los endpoints CRUD de FAQ (Task 6).

Cubre los escenarios del spec faq-storage:
- GET /api/faqs (auth + happy + missing file)
- POST /api/faqs (happy + 3 fallas de validación)
- PUT /api/faqs/{id} (happy + id inexistente)
- DELETE /api/faqs/{id} (happy + id inexistente)
- Atomic write observable (monkeypatch sobre os.replace)
"""
import json
import re
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest


@pytest.fixture
def faqs_path(tmp_path, monkeypatch):
    """Redirige FAQS_PATH a un archivo temporal antes de importar la app."""
    target = tmp_path / "faqs.json"
    # Pre-construir el módulo interface parcheando FAQS_PATH para tests deterministas.
    # Usamos importlib para tener un módulo fresco; alternativamente parchamos in-place
    # luego de importarlo. Como el fixture corre antes del client, parcheamos in-place.
    import interface
    monkeypatch.setattr(interface, "FAQS_PATH", target)
    return target


@pytest.fixture
def auth_token(faqs_path):
    """Devuelve un JWT válido contra la SECRET_KEY en uso de la app."""
    from jose import jwt
    from interface import SECRET_KEY
    return jwt.encode({"sub": "admin"}, SECRET_KEY, algorithm="HS256")


@pytest.fixture
async def client(faqs_path):
    """AsyncClient ASGI contra interface.app. AuthMiddleware corre real."""
    import interface
    transport = httpx.ASGITransport(app=interface.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ────────────────────────────────────────────────────────────────────────
# GET /api/faqs
# ────────────────────────────────────────────────────────────────────────

class TestListarFAQs:
    @pytest.mark.asyncio
    async def test_sin_auth_devuelve_401(self, client):
        resp = await client.get("/api/faqs")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_archivo_inexistente_devuelve_lista_vacia(self, client, auth_token):
        # faqs.json no existe en este tmp_path
        resp = await client.get("/api/faqs", headers=_auth(auth_token))
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_archivo_con_filas_devuelve_las_filas(self, client, faqs_path, auth_token):
        faqs_path.write_text(json.dumps([
            {"id": "abc", "pregunta": "¿Horario?", "respuesta": "9-18"},
            {"id": "def", "pregunta": "¿Precio?", "respuesta": "$100"},
        ]), encoding="utf-8")
        resp = await client.get("/api/faqs", headers=_auth(auth_token))
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert body[0]["id"] == "abc"
        assert body[0]["pregunta"] == "¿Horario?"
        assert body[0]["respuesta"] == "9-18"

    @pytest.mark.asyncio
    async def test_archivo_vacio_get_devuelve_lista_vacia(self, client, faqs_path, auth_token):
        """Regresión: faqs.json existe pero está vacío (0 bytes). GET no debe
        explotar con 500; debe devolver [].
        """
        faqs_path.write_text("", encoding="utf-8")
        resp = await client.get("/api/faqs", headers=_auth(auth_token))
        assert resp.status_code == 200
        assert resp.json() == []


# ────────────────────────────────────────────────────────────────────────
# POST /api/faqs
# ────────────────────────────────────────────────────────────────────────

class TestCrearFAQ:
    @pytest.mark.asyncio
    async def test_sin_auth_devuelve_401(self, client):
        resp = await client.post("/api/faqs", json={"pregunta": "p", "respuesta": "r"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_crear_fila_valida_devuelve_201_y_persiste(self, client, faqs_path, auth_token):
        resp = await client.post(
            "/api/faqs",
            json={"pregunta": "Horario", "respuesta": "Lun a Vie 9-18hs"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 201
        body = resp.json()
        # Tiene id generado
        assert "id" in body and len(body["id"]) > 0
        assert body["pregunta"] == "Horario"
        assert body["respuesta"] == "Lun a Vie 9-18hs"
        # Se persistió en disco
        on_disk = json.loads(faqs_path.read_text(encoding="utf-8"))
        assert len(on_disk) == 1
        assert on_disk[0]["id"] == body["id"]

    @pytest.mark.asyncio
    async def test_archivo_vacio_post_no_devuelve_500(self, client, faqs_path, auth_token):
        """Regresión: faqs.json existe pero está vacío (0 bytes), p.ej. cuando un
        bind mount de Docker crea un archivo vacío en el primer arranque.
        El primer POST debe recuperar la lista vacía, no explotar con 500.
        """
        faqs_path.write_text("", encoding="utf-8")
        resp = await client.post(
            "/api/faqs",
            json={"pregunta": "Horario", "respuesta": "Lun a Vie 9-18hs"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["pregunta"] == "Horario"
        # El primer POST reescribe el archivo con contenido válido
        on_disk = json.loads(faqs_path.read_text(encoding="utf-8"))
        assert len(on_disk) == 1

    @pytest.mark.asyncio
    async def test_pregunta_vacia_devuelve_400(self, client, auth_token):
        resp = await client.post(
            "/api/faqs",
            json={"pregunta": "", "respuesta": "ok"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == "E-FAQ-001"

    @pytest.mark.asyncio
    async def test_respuesta_vacia_devuelve_400(self, client, auth_token):
        resp = await client.post(
            "/api/faqs",
            json={"pregunta": "ok", "respuesta": "   "},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == "E-FAQ-001"

    @pytest.mark.asyncio
    async def test_pregunta_excede_500_chars_devuelve_400(self, client, auth_token):
        resp = await client.post(
            "/api/faqs",
            json={"pregunta": "x" * 501, "respuesta": "ok"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == "E-FAQ-001"

    @pytest.mark.asyncio
    async def test_respuesta_excede_500_chars_devuelve_400(self, client, auth_token):
        resp = await client.post(
            "/api/faqs",
            json={"pregunta": "ok", "respuesta": "y" * 501},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == "E-FAQ-001"

    @pytest.mark.asyncio
    async def test_escritura_atomica_usa_os_replace(self, client, faqs_path, auth_token, monkeypatch):
        """El guardado debe ir por temp + os.replace: el SOURCE del replace debe ser un .tmp."""
        import interface
        real_replace = interface.os.replace

        captured = {"src": None, "dst": None}

        def fake_replace(src, dst):
            captured["src"] = src
            captured["dst"] = dst
            return real_replace(src, dst)

        monkeypatch.setattr(interface.os, "replace", fake_replace)

        resp = await client.post(
            "/api/faqs",
            json={"pregunta": "Atomic?", "respuesta": "yes"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 201
        # El source del replace debe ser un archivo temporal, NO el destino final.
        assert captured["src"] is not None, "Debió llamar a os.replace"
        assert str(captured["src"]) != str(captured["dst"]), "Source y destination no pueden ser iguales"
        assert str(captured["src"]).endswith(".tmp"), f"Source debe ser .tmp, fue {captured['src']}"
        assert str(captured["dst"]) == str(faqs_path), "Destination debe ser faqs.json"


# ────────────────────────────────────────────────────────────────────────
# PUT /api/faqs/{id}
# ────────────────────────────────────────────────────────────────────────

class TestActualizarFAQ:
    @pytest.mark.asyncio
    async def test_sin_auth_devuelve_401(self, client):
        resp = await client.put("/api/faqs/abc", json={"pregunta": "p", "respuesta": "r"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_id_existente_reemplaza_y_persiste(self, client, faqs_path, auth_token):
        faqs_path.write_text(json.dumps([
            {"id": "abc", "pregunta": "Vieja", "respuesta": "Vieja respuesta"},
        ]), encoding="utf-8")
        resp = await client.put(
            "/api/faqs/abc",
            json={"pregunta": "Nueva", "respuesta": "Nueva respuesta"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "abc"
        assert body["pregunta"] == "Nueva"
        assert body["respuesta"] == "Nueva respuesta"
        on_disk = json.loads(faqs_path.read_text(encoding="utf-8"))
        assert on_disk[0]["pregunta"] == "Nueva"

    @pytest.mark.asyncio
    async def test_id_inexistente_devuelve_404(self, client, faqs_path, auth_token):
        faqs_path.write_text(json.dumps([]), encoding="utf-8")
        resp = await client.put(
            "/api/faqs/xyz",
            json={"pregunta": "p", "respuesta": "r"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "E-FAQ-003"

    @pytest.mark.asyncio
    async def test_solo_reemplaza_el_id_solicitado(self, client, faqs_path, auth_token):
        """PUT no debe afectar otras filas."""
        faqs_path.write_text(json.dumps([
            {"id": "abc", "pregunta": "A", "respuesta": "a"},
            {"id": "def", "pregunta": "D", "respuesta": "d"},
        ]), encoding="utf-8")
        resp = await client.put(
            "/api/faqs/abc",
            json={"pregunta": "A2", "respuesta": "a2"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 200
        on_disk = json.loads(faqs_path.read_text(encoding="utf-8"))
        assert len(on_disk) == 2
        # La fila def NO cambió
        assert {"id": "def", "pregunta": "D", "respuesta": "d"} in on_disk
        # La fila abc SÍ cambió
        assert {"id": "abc", "pregunta": "A2", "respuesta": "a2"} in on_disk

    @pytest.mark.asyncio
    async def test_validacion_falla_devuelve_400(self, client, faqs_path, auth_token):
        faqs_path.write_text(json.dumps([
            {"id": "abc", "pregunta": "p", "respuesta": "r"},
        ]), encoding="utf-8")
        resp = await client.put(
            "/api/faqs/abc",
            json={"pregunta": "", "respuesta": "r"},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == "E-FAQ-001"


# ────────────────────────────────────────────────────────────────────────
# DELETE /api/faqs/{id}
# ────────────────────────────────────────────────────────────────────────

class TestEliminarFAQ:
    @pytest.mark.asyncio
    async def test_sin_auth_devuelve_401(self, client):
        resp = await client.delete("/api/faqs/abc")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_id_existente_elimina_y_persiste(self, client, faqs_path, auth_token):
        faqs_path.write_text(json.dumps([
            {"id": "abc", "pregunta": "p", "respuesta": "r"},
            {"id": "def", "pregunta": "x", "respuesta": "y"},
        ]), encoding="utf-8")
        resp = await client.delete("/api/faqs/abc", headers=_auth(auth_token))
        assert resp.status_code == 204
        # 204 No Content
        assert resp.content == b""
        on_disk = json.loads(faqs_path.read_text(encoding="utf-8"))
        assert len(on_disk) == 1
        assert on_disk[0]["id"] == "def"

    @pytest.mark.asyncio
    async def test_id_inexistente_devuelve_404(self, client, faqs_path, auth_token):
        faqs_path.write_text(json.dumps([]), encoding="utf-8")
        resp = await client.delete("/api/faqs/xyz", headers=_auth(auth_token))
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "E-FAQ-003"

    @pytest.mark.asyncio
    async def test_id_generado_es_uuid4_valido(self, client, faqs_path, auth_token):
        """Cada POST debe generar un id único y persistente."""
        import uuid as uuid_mod
        resp1 = await client.post(
            "/api/faqs",
            json={"pregunta": "P1", "respuesta": "R1"},
            headers=_auth(auth_token),
        )
        resp2 = await client.post(
            "/api/faqs",
            json={"pregunta": "P2", "respuesta": "R2"},
            headers=_auth(auth_token),
        )
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        id1 = resp1.json()["id"]
        id2 = resp2.json()["id"]
        # Ambos son UUIDs parseables
        uuid_mod.UUID(id1)
        uuid_mod.UUID(id2)
        # Y son distintos
        assert id1 != id2


# ────────────────────────────────────────────────────────────────────────
# FAQS_PATH configurable para named volume (PR 2 fixup)
#
# Cuando el operator corre los containers, FAQS_VOLUME_MOUNT apunta al
# punto de montaje del named volume `faq_data` (ver docker-compose.yml).
# interface.FAQS_PATH debe resolver a <mount> / "faqs.json" en ese caso,
# y caer al path local (ROOT_DIR/"faqs.json") en desarrollo.
# ────────────────────────────────────────────────────────────────────────

class TestFAQSPathVolumeConfig:
    def test_faqs_path_uses_volume_mount_when_env_var_set(self, monkeypatch, tmp_path):
        """GIVEN FAQS_VOLUME_MOUNT=/some/path WHEN faq_paths loaded THEN FAQS_PATH = /some/path/faqs.json."""
        monkeypatch.setenv("FAQS_VOLUME_MOUNT", str(tmp_path))
        # Reimport limpio para que tome la env var. faq_paths es el módulo
        # centralizado; hay que reimportarlo antes que interface.
        import importlib
        import faq_paths
        import interface as interface_mod
        importlib.reload(faq_paths)
        importlib.reload(interface_mod)
        try:
            assert faq_paths.FAQS_PATH == tmp_path / "faqs.json"
            # interface re-exporta el mismo path — son la misma cosa.
            assert interface_mod.FAQS_PATH == faq_paths.FAQS_PATH
        finally:
            # Revertimos para no contaminar el resto de los tests.
            monkeypatch.delenv("FAQS_VOLUME_MOUNT")
            importlib.reload(faq_paths)
            importlib.reload(interface_mod)

    def test_faqs_path_falls_back_to_root_dir_when_no_env_var(self, monkeypatch):
        """GIVEN FAQS_VOLUME_MOUNT no está seteada WHEN faq_paths loaded THEN FAQS_PATH = ROOT_DIR/faqs.json (compat dev local)."""
        monkeypatch.delenv("FAQS_VOLUME_MOUNT", raising=False)
        import importlib
        import faq_paths
        import interface as interface_mod
        importlib.reload(faq_paths)
        importlib.reload(interface_mod)
        assert faq_paths.FAQS_PATH == faq_paths._ROOT_DIR / "faqs.json"
        assert interface_mod.FAQS_PATH == faq_paths.FAQS_PATH
        # Y NO vive bajo el volume mount (estamos en dev local).
        assert str(faq_paths.FAQS_PATH).endswith("faqs.json")

    def test_rag_orchestrator_uses_centralized_faqs_path(self, monkeypatch, tmp_path):
        """GIVEN FAQS_VOLUME_MOUNT=/docker/path WHEN rag_orchestrator imported THEN el FAQMatcher se construye con la ruta centralizada, no con un literal hardcodeado.

        Bug de PR 2: rag_orchestrator construía el FAQMatcher con
        `_ROOT_DIR / "faqs.json"`, ignorando FAQS_VOLUME_MOUNT. Resultado:
        admin-ui escribía en /app/faqs_data/faqs.json, el bot leía un
        inexistente /app/faqs.json, _rows=[], match()=None, RAG de
        fallback. Centralizamos en faq_paths para que esto no pueda
        volver a pasar.
        """
        monkeypatch.setenv("FAQS_VOLUME_MOUNT", str(tmp_path))
        try:
            import importlib
            import faq_paths
            import rag_orchestrator
            importlib.reload(faq_paths)
            importlib.reload(rag_orchestrator)
            # rag_orchestrator importa FAQS_PATH al definir el módulo.
            # La pregunta es: ¿usa la versión centralizada?
            assert rag_orchestrator.FAQS_PATH is faq_paths.FAQS_PATH, (
                "rag_orchestrator debe importar FAQS_PATH desde faq_paths, "
                "no redefinirlo ni hardcodearlo. Si diverge, admin y bot "
                "ven archivos distintos y los matches se rompen en "
                "silencio (sin log de error)."
            )
        finally:
            monkeypatch.delenv("FAQS_VOLUME_MOUNT")
            import importlib
            import faq_paths
            import rag_orchestrator
            importlib.reload(faq_paths)
            importlib.reload(rag_orchestrator)

    def test_docker_compose_mounts_faq_data_at_directory_path(self):
        """El named volume `faq_data` se monta en una ruta de DIRECTORIO, no de archivo,
        y AMBOS servicios (admin-ui y whatsapp-bot) setean FAQS_VOLUME_MOUNT
        apuntando al mismo directorio.

        Bug de PR 2: el volume se montaba en `/app/faqs.json` (path-archivo).
        Docker trata los named volumes como directorios, por lo que creaba
        un directorio en esa ruta y los `os.replace` fallaban con
        `Is a directory`. El path destino tiene que ser un directorio
        (típicamente `/app/faqs_data`); `faqs.json` vive ADENTRO de ese
        directorio como archivo regular.

        Bug adicional (hotfix 4): sólo admin-ui tenía FAQS_VOLUME_MOUNT
        seteada, así que el bot caía al fallback _ROOT_DIR/faqs.json y
        leía un archivo inexistente. El matcher devolvía 0 rows y el
        bot respondía con el fallback RAG sin error visible.
        """
        compose_path = Path(__file__).resolve().parent.parent / "docker-compose.yml"
        text = compose_path.read_text(encoding="utf-8")
        # Ningún `faq_data:` puede apuntar a un path que termine en `faqs.json`.
        bad_mounts = re.findall(r"faq_data:/app/faqs\.json(?!\w)", text)
        assert bad_mounts == [], (
            f"faq_data volume está montado en un path-archivo. Los named "
            f"volumes SIEMPRE son directorios; el destino debe ser un "
            f"directorio (ej: /app/faqs_data), no el archivo final "
            f"(/app/faqs.json). Ocurrencias: {bad_mounts}"
        )
        # Y como contrato: FAQS_VOLUME_MOUNT tiene que estar seteada
        # en TODOS los servicios que montan faq_data (hoy: admin-ui y
        # whatsapp-bot). Si no, el servicio sin la env var cae al
        # fallback _ROOT_DIR/faqs.json y lee un archivo inexistente.
        mount_match = re.search(r"faq_data:(/app/faqs_data)\b", text)
        assert mount_match is not None, (
            "No se encontró un mount de faq_data en un directorio. "
            "Esperaba algo tipo `faq_data:/app/faqs_data`."
        )
        mount_dir = mount_match.group(1)
        # Buscamos TODAS las apariciones de FAQS_VOLUME_MOUNT= y nos
        # aseguramos de que coincidan con el mount_dir.
        env_values = re.findall(r"FAQS_VOLUME_MOUNT=(\S+)", text)
        assert len(env_values) >= 2, (
            f"FAQS_VOLUME_MOUNT debe estar seteada en TODOS los "
            f"servicios que montan faq_data (admin-ui y whatsapp-bot). "
            f"Encontré {len(env_values)} ocurrencias: {env_values}."
        )
        for value in env_values:
            assert value == mount_dir, (
                f"FAQS_VOLUME_MOUNT={value!r} debe coincidir con el "
                f"destino del mount faq_data ({mount_dir!r})."
            )
