import { apiFetch } from './api.js';
import { initStores } from './store.js';
import { initAuth } from './auth.js';
import { initInstancesPanel } from './instances.js';

document.addEventListener('alpine:init', () => {
    initStores(Alpine);
    initAuth(Alpine);
    initInstancesPanel(Alpine);

    Alpine.data('adminPanel', () => ({
        activeTab: 'config',
        pdfs: [],
        csvs: [],
        logs: [],
        searchResults: [],
        searchQuery: '',
        currentLogContent: '',
        currentLogTitle: 'Selecciona un archivo para leer',
        loadingLog: false,

        // Config state
        apiKey: '',
        apiStatus: '',
        apiStatusClass: '',
        configEmail: '',
        configPhoneCode: '+54',
        configPhoneNum: '',
        configStatus: '',
        configStatusClass: '',

        // Gemini model config state
        geminiModel: '',
        geminiEmbeddingsModel: '',
        geminiConfigStatus: '',
        geminiConfigStatusClass: '',

        // Upload state
        pdfUploadStatus: '',
        pdfUploadStatusClass: '',
        csvUploadStatus: '',
        csvUploadStatusClass: '',

        // FAQs state
        faqs: [],
        faqForm: {
            open: false,
            editId: null,
            pregunta: '',
            respuesta: '',
            saving: false,
            errors: { pregunta: '', respuesta: '' },
            get valid() {
                const p = (this.pregunta || '').trim();
                const r = (this.respuesta || '').trim();
                return p.length > 0 && p.length <= 500 && r.length > 0 && r.length <= 500;
            },
        },

        init() {
            this.$watch('activeTab', (val) => {
                if (val === 'config') this.loadContactConfig();
                if (val === 'docs') { this.loadPdfs(); this.loadCsvs(); }
                if (val === 'faqs') this.loadFaqs();
                if (val === 'logs') { this.loadLogs(); this.searchQuery = ''; }
            });
            this.$nextTick(() => {
                this.loadContactConfig();
            });
        },
        
        switchTab(tab) {
            const editor = Alpine.store('csvEditor');
            if (editor?.dirty) {
                if (!confirm('Tenés cambios sin guardar en el CSV. ¿Descartarlos?')) return;
                editor.cancel(true);
            } else if (editor?.show && tab !== 'docs') {
                editor.cancel(true);
            }
            this.activeTab = tab;
        },

        // --- API KEY ---
        async saveApiKey() {
            if (!this.apiKey) {
                this.apiStatus = "⚠ Escribe una clave";
                this.apiStatusClass = "mt-3 text-orange-500 font-medium h-5";
                return;
            }
            const formData = new FormData();
            formData.append("key", this.apiKey);
            try {
                const res = await apiFetch('/api/apikey', { method: 'POST', body: formData });
                const data = await res.json();
                this.apiStatus = data.message;
                this.apiStatusClass = data.status === "success" ? "mt-3 text-green-600 font-medium h-5" : "mt-3 text-red-600 font-medium h-5";
                window.showToast(data.message, data.status === "success" ? 'success' : 'error');
            } catch (err) {
                this.apiStatus = "✕ Error de conexión";
                window.showToast('Error de conexión al guardar API Key', 'error');
            }
        },

        // --- CONFIG ---
        async loadContactConfig() {
            try {
                const res = await apiFetch('/api/config');
                const data = await res.json();

                this.configEmail = data.email || '';
                const telCompleto = data.telefono || '';
                let numeroSinCodigo = telCompleto;

                // Basic logic to split country code
                const codes = ['+54', '+56', '+57', '+52', '+51', '+598', '+58', '+591', '+595', '+593', '+1', '+34'].sort((a,b)=>b.length-a.length);
                for (let code of codes) {
                    if (telCompleto.startsWith(code)) {
                        this.configPhoneCode = code;
                        numeroSinCodigo = telCompleto.substring(code.length).trim();
                        break;
                    }
                }
                this.configPhoneNum = numeroSinCodigo;

                // Load Gemini model config
                this.geminiModel = data.gemini_model || '';
                this.geminiEmbeddingsModel = data.gemini_embeddings_model || '';
            } catch (err) {
                console.error("Error al cargar config", err);
            }
        },

        async saveContactConfig() {
            this.configStatus = "⏳ Guardando...";
            this.configStatusClass = "mt-3 text-blue-500 text-sm font-medium h-5";

            const telefonoFinal = `${this.configPhoneCode} ${this.configPhoneNum}`.trim();
            const formData = new FormData();
            if(this.configEmail) formData.append("email", this.configEmail);
            if(this.configPhoneNum) formData.append("telefono", telefonoFinal);

            try {
                const res = await apiFetch('/api/config', { method: 'POST', body: formData });
                const data = await res.json();
                this.configStatus = data.message;
                this.configStatusClass = data.status === "success" ? "mt-3 text-green-600 font-medium h-5" : "mt-3 text-red-600 font-medium h-5";
                window.showToast(data.message, data.status === "success" ? 'success' : 'error');
            } catch (err) {
                this.configStatus = "✕ Error al guardar datos";
                this.configStatusClass = "mt-3 text-red-600 font-medium h-5";
                window.showToast('Error al guardar datos', 'error');
            }
        },

        // --- GEMINI MODEL CONFIG ---
        async saveGeminiConfig() {
            this.geminiConfigStatus = "⏳ Guardando...";
            this.geminiConfigStatusClass = "mt-3 text-blue-500 text-sm font-medium h-5";

            const formData = new FormData();
            if (this.geminiModel) formData.append("gemini_model", this.geminiModel);
            if (this.geminiEmbeddingsModel) formData.append("gemini_embeddings_model", this.geminiEmbeddingsModel);

            try {
                const res = await apiFetch('/api/config', { method: 'POST', body: formData });
                const data = await res.json();
                this.geminiConfigStatus = data.message;
                this.geminiConfigStatusClass = data.status === "success" ? "mt-3 text-green-600 font-medium h-5" : "mt-3 text-red-600 font-medium h-5";
                window.showToast(data.message, data.status === "success" ? 'success' : 'error');
            } catch (err) {
                this.geminiConfigStatus = "✕ Error al guardar modelos";
                this.geminiConfigStatusClass = "mt-3 text-red-600 font-medium h-5";
                window.showToast('Error al guardar modelos', 'error');
            }
        },

        // --- PDFS ---
        async loadPdfs() {
            this.pdfs = [];
            try {
                const res = await apiFetch('/api/pdfs');
                const data = await res.json();
                this.pdfs = data.pdfs || [];
            } catch (err) {
                console.error(err);
            }
        },

        async uploadPdfs(event) {
            const files = event.target.files;
            if (files.length === 0) return;

            for (let f of files) {
                if (!f.name.toLowerCase().endsWith('.pdf')) {
                    this.pdfUploadStatus = "✕ Solo se permiten archivos .pdf";
                    this.pdfUploadStatusClass = "mt-3 text-red-600 text-sm font-medium h-5";
                    window.showToast(`"${f.name}" no es un PDF`, 'error');
                    return;
                }
            }
            this.pdfUploadStatus = "⏳ Subiendo...";
            this.pdfUploadStatusClass = "mt-3 text-blue-500 text-sm font-medium h-5";
            
            const formData = new FormData();
            for(let i=0; i<files.length; i++) formData.append("files", files[i]);

            try {
                await apiFetch('/api/pdfs', { method: 'POST', body: formData });
                this.pdfUploadStatus = "✓ Subida exitosa";
                this.pdfUploadStatusClass = "mt-3 text-green-600 text-sm font-medium h-5";
                window.showToast('PDFs subidos', 'success');
                event.target.value = ''; // clear input
                this.loadPdfs();
            } catch (err) {
                this.pdfUploadStatus = "✕ Error al subir";
                this.pdfUploadStatusClass = "mt-3 text-red-600 text-sm font-medium h-5";
                window.showToast('Error al subir PDFs', 'error');
            }
        },

        async deletePdf(filename) {
            if(!confirm(`¿Seguro que deseas eliminar ${filename}?`)) return;
            try {
                await apiFetch(`/api/pdfs/${filename}`, { method: 'DELETE' });
                this.loadPdfs();
            } catch (err) {
                window.showToast('Error al borrar', 'error');
            }
        },

        downloadFile(url, filename) {
            const token = localStorage.getItem('token');
            fetch(url, { headers: { 'Authorization': `Bearer ${token}` } })
                .then(res => res.blob())
                .then(blob => {
                    const a = document.createElement('a');
                    a.href = window.URL.createObjectURL(blob);
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                })
                .catch(() => window.showToast('Error al descargar', 'error'));
        },

        // --- CSVS ---
        async loadCsvs() {
            this.csvs = [];
            try {
                const res = await apiFetch('/api/csvs');
                const data = await res.json();
                this.csvs = data.csvs || [];
            } catch (err) {
                console.error(err);
            }
        },

        async uploadCsvs(event) {
            const files = event.target.files;
            if (files.length === 0) return;

            this.csvUploadStatus = "⏳ Subiendo...";
            this.csvUploadStatusClass = "mt-3 text-blue-500 text-sm font-medium h-5";
            
            const formData = new FormData();
            for(let i=0; i<files.length; i++) formData.append("files", files[i]);

            try {
                const res = await apiFetch('/api/csvs', { method: 'POST', body: formData });
                if (!res.ok) {
                    const errData = await res.json();
                    throw new Error(errData.detail || 'Error al subir');
                }
                this.csvUploadStatus = "✓ Subida exitosa";
                this.csvUploadStatusClass = "mt-3 text-green-600 text-sm font-medium h-5";
                window.showToast('CSVs subidos', 'success');
                event.target.value = '';
                this.loadCsvs();
            } catch (err) {
                this.csvUploadStatus = `✕ ${err.message}`;
                this.csvUploadStatusClass = "mt-3 text-red-600 text-sm font-medium h-5";
                window.showToast(err.message, 'error');
            }
        },

        async deleteCsv(filename) {
            if(!confirm(`¿Seguro que deseas eliminar ${filename}?`)) return;
            try {
                await apiFetch(`/api/csvs/${filename}`, { method: 'DELETE' });
                this.loadCsvs();
                if (Alpine.store('csvEditor').filename === filename) {
                    Alpine.store('csvEditor').cancel();
                }
            } catch (err) {
                window.showToast('Error al borrar', 'error');
            }
        },

        // --- LOGS ---
        get displayLogs() {
            return this.searchQuery.trim() ? this.searchResults : this.logs.map(log => ({ filename: log }));
        },

        async loadLogs() {
            this.logs = [];
            try {
                const res = await apiFetch('/api/logs');
                if (res.ok) {
                    const data = await res.json();
                    this.logs = data.logs || [];
                }
            } catch (err) {
                console.error(err);
            }
        },

        async performSearch() {
            if (!this.searchQuery.trim()) return;
            try {
                const res = await apiFetch(`/api/logs/search?q=${encodeURIComponent(this.searchQuery)}`);
                if (res.ok) {
                    const data = await res.json();
                    this.searchResults = data.results || [];
                }
            } catch (err) {
                console.error(err);
            }
        },

        async readLog(filename) {
            this.currentLogTitle = `${filename}`;
            this.currentLogContent = '';
            this.loadingLog = true;
            try {
                const res = await apiFetch(`/api/logs/${filename}`);
                if (res.ok) {
                    const data = await res.json();
                    this.currentLogContent = this.formatLogContent(data.contenido);
                } else {
                    this.currentLogContent = '<div class="text-center text-red-500 font-bold mt-4">Error del servidor al leer el archivo.</div>';
                }
            } catch (err) {
                this.currentLogContent = '<div class="text-center text-red-500 mt-4">Error de conexión.</div>';
            } finally {
                this.loadingLog = false;
            }
        },

        formatLogContent(rawText) {
            if (!rawText) return '<div class="text-gray-500 text-sm text-center">Log vacío</div>';
            
            const lines = rawText.split('\n');
            let html = '';
            
            let messages = [];
            let currentMessage = null;

            // 1. Agrupar las líneas que pertenecen a un mismo mensaje multilínea
            lines.forEach(line => {
                if (line.startsWith('id_usuario|||') || 
                    line.startsWith('id_bot|||') || 
                    line.startsWith('id_audio|||') || 
                    line.startsWith('asistente|||') ||
                    line.startsWith('Chat iniciado') || 
                    line.startsWith('Chat finalizado')) {
                    
                    if (currentMessage !== null) {
                        messages.push(currentMessage);
                    }
                    currentMessage = line;
                } else {
                    // Es un salto de línea dentro del mensaje actual
                    if (currentMessage !== null) {
                        currentMessage += '\n' + line;
                    }
                }
            });
            if (currentMessage !== null) {
                messages.push(currentMessage);
            }

            // 2. Renderizar los mensajes agrupados
            messages.forEach(fullMsg => {
                fullMsg = fullMsg.trim();
                if (!fullMsg) return;

                const parts = fullMsg.split('|||');

                // Si es un mensaje de chat normal
                if (parts.length >= 4) {
                    const type = parts[0].trim();
                    const identifier = parts[1].trim();
                    const timeStr = parts[2].trim();
                    const content = parts.slice(3).join('|||').trim();

                    if (type === 'id_usuario' || type === 'id_audio') {
                        // Reemplazamos los verdaderos \n por <br> para que HTML los dibuje bien
                        let formatted = type === 'id_audio' ? '<i class=\"fas fa-microphone text-gray-500 mr-1\"></i> <i>Mensaje de audio</i>' : this.escapeHtml(content).replace(/\n/g, '<br>');
                        
                        html += `
                            <div class="flex justify-end animate-fade-in">
                                <div class="bg-[#d9fdd3] text-gray-800 rounded-lg py-2 px-3 max-w-[80%] shadow-sm relative text-sm font-medium">
                                    ${formatted}
                                    <div class="text-[10px] text-gray-500 text-right mt-1">${timeStr}</div>
                                </div>
                            </div>`;
                    } else if (type === 'id_bot' || type === 'asistente') {
                        let formatted = this.escapeHtml(content).replace(/\n/g, '<br>').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
                        html += `
                            <div class="flex justify-start animate-fade-in">
                                <div class="bg-white text-gray-800 rounded-lg py-2 px-3 max-w-[80%] shadow-sm relative text-sm font-medium border border-gray-100">
                                    ${formatted}
                                    <div class="text-[10px] text-gray-400 text-right mt-1">${timeStr}</div>
                                </div>
                            </div>`;
                    }
                } else {
                    // Si es un mensaje de sistema (ej: "Chat iniciado el...")
                    const cleanSys = fullMsg.replace(/=/g, '').trim();
                    if (cleanSys) {
                        html += `
                            <div class="flex justify-center animate-fade-in my-2">
                                <div class="bg-[#e5e7eb] text-gray-500 text-[11px] px-3 py-1 rounded-md opacity-90 text-center max-w-[90%] font-medium">
                                    ${this.escapeHtml(cleanSys)}
                                </div>
                            </div>`;
                    }
                }
            });

            return html || '<div class="text-center text-gray-500 text-sm mt-auto mb-auto">No hay mensajes parseables en este log.</div>';
        },

        escapeHtml(str) {
            return str
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        },

        // --- FAQS ---
        async loadFaqs() {
            this.faqs = [];
            try {
                const res = await apiFetch('/api/faqs');
                if (res.ok) {
                    this.faqs = await res.json();
                }
            } catch (err) {
                console.error('Error al cargar FAQs', err);
                window.showToast('Error al cargar FAQs', 'error');
            }
        },

        _validateFaqForm() {
            const f = this.faqForm;
            f.errors.pregunta = '';
            f.errors.respuesta = '';
            const p = (f.pregunta || '').trim();
            const r = (f.respuesta || '').trim();
            if (!p) f.errors.pregunta = 'La pregunta no puede estar vacía.';
            else if (p.length > 500) f.errors.pregunta = 'La pregunta no puede superar los 500 caracteres.';
            if (!r) f.errors.respuesta = 'La respuesta no puede estar vacía.';
            else if (r.length > 500) f.errors.respuesta = 'La respuesta no puede superar los 500 caracteres.';
            return !f.errors.pregunta && !f.errors.respuesta;
        },

        startCreateFaq() {
            const f = this.faqForm;
            f.open = true;
            f.editId = null;
            f.pregunta = '';
            f.respuesta = '';
            f.saving = false;
            f.errors = { pregunta: '', respuesta: '' };
        },

        startEditFaq(faq) {
            const f = this.faqForm;
            f.open = true;
            f.editId = faq.id;
            f.pregunta = faq.pregunta;
            f.respuesta = faq.respuesta;
            f.saving = false;
            f.errors = { pregunta: '', respuesta: '' };
        },

        cancelFaqForm() {
            const f = this.faqForm;
            f.open = false;
            f.editId = null;
            f.pregunta = '';
            f.respuesta = '';
            f.saving = false;
            f.errors = { pregunta: '', respuesta: '' };
        },

        async saveFaq() {
            if (!this._validateFaqForm()) return;
            const f = this.faqForm;
            f.saving = true;
            const isEdit = !!f.editId;
            const url = isEdit ? `/api/faqs/${f.editId}` : '/api/faqs';
            const method = isEdit ? 'PUT' : 'POST';
            try {
                const res = await apiFetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pregunta: f.pregunta.trim(), respuesta: f.respuesta.trim() }),
                });
                if (res.ok) {
                    window.showToast(isEdit ? 'FAQ actualizada' : 'FAQ creada', 'success');
                    this.cancelFaqForm();
                    await this.loadFaqs();
                } else {
                    const errData = await res.json().catch(() => ({}));
                    const detail = (errData.error && errData.error.detail) || 'Error al guardar';
                    window.showToast(detail, 'error');
                }
            } catch (err) {
                window.showToast('Error de conexión al guardar', 'error');
            } finally {
                f.saving = false;
            }
        },

        async confirmDeleteFaq(faq) {
            if (!confirm(`¿Eliminar la pregunta "${faq.pregunta}"?`)) return;
            try {
                const res = await apiFetch(`/api/faqs/${faq.id}`, { method: 'DELETE' });
                if (res.status === 204 || res.ok) {
                    window.showToast('FAQ eliminada', 'success');
                    await this.loadFaqs();
                } else {
                    window.showToast('Error al eliminar', 'error');
                }
            } catch (err) {
                window.showToast('Error de conexión al eliminar', 'error');
            }
        },
    }));
});
