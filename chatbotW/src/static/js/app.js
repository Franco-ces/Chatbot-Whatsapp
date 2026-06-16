import { apiFetch } from './api.js';
import { initStores } from './store.js';
import { initAuth } from './auth.js';
import { initInstancesPanel } from './instances.js';

document.addEventListener('alpine:init', () => {
    initStores(Alpine);
    initAuth(Alpine);
    initInstancesPanel(Alpine);

    Alpine.data('adminPanel', () => ({
        activeTab: 'dashboard',
        activeInstanceName: '',
        activeInstanceLoaded: false,
        googleApiKeySet: false,
        evolutionApiKeySet: false,
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
        configBotTone: '',
        evoApiKey: '',
        evoApiStatus: '',
        evoApiStatusClass: '',
        configEmail: '',
        configPhoneCode: '+54',
        configPhoneNum: '',
        configStatus: '',
        configStatusClass: '',

        // Gemini model config state
        geminiModel: '',
        geminiEmbeddingsModel: '',
        activeGeminiModel: '',
        activeGeminiEmbeddingsModel: '',
        geminiConfigStatus: '',
        geminiConfigStatusClass: '',

        // Upload state
        pdfUploadStatus: '',
        pdfUploadStatusClass: '',
        csvUploadStatus: '',
        csvUploadStatusClass: '',

        // FAQs state
        faqs: [],

        // Dashboard state
        telemetryData: null,
        telemetryLoading: false,
        telemetryError: '',
        charts: [],

        // Error category labels (Spanish)
        errorCategoryLabels: {
            'E-COM': 'Comunicación',
            'E-RAG': 'RAG',
            'E-CFG': 'Configuración',
            'E-API': 'API',
            'E-SYS': 'Sistema',
            'E-FAQ': 'FAQ',
            'E-TEL': 'Telemetría',
        },

        // Schedules state
        schedules: [],
        scheduleForm: {
            open: false,
            editId: null,
            tipo: '',
            hora_envio: '',
            destino: '',
            header_text: '',
            footer_text: '',
            saving: false,
            tipos: [],
            params: {},
            selectedTipoParams: [],
            destinoHistory: [],
            errors: { tipo: '', hora_envio: '', destino: '' },
            get valid() {
                return (this.tipo || '').trim().length > 0
                    && (this.hora_envio || '').trim().length > 0
                    && (this.destino || '').trim().length > 0;
            },
        },
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

        // Dark mode state
        darkMode: localStorage.getItem('darkMode') === 'true',

        // Quick stats state
        quickStats: null,
        healthData: null,
        healthLoading: false,
        healthPollInterval: null,

        // Password change state
        changePasswordCurrent: '',
        changePasswordNew: '',
        changePasswordConfirm: '',
        changePasswordStatus: '',
        changePasswordStatusClass: '',
        changePasswordLoading: false,

        // Accordion state for Config tab
        accordionState: {
            googleApiKey: false,
            evolutionApiKey: false,
            contactVars: false,
            botTone: false,
            geminiModels: false,
            password: false,
        },

        // Accordion state for Dashboard tab
        dashboardAccordionState: {
            health: false,
            charts: true,
            errorCategories: false,
        },

        init() {
            // Restaurar tab activo desde sessionStorage
            const savedTab = sessionStorage.getItem('activeTab');
            if (savedTab && ['config', 'docs', 'faqs', 'instances', 'dashboard', 'logs', 'reports'].includes(savedTab)) {
                this.activeTab = savedTab;
            }
            this.$watch('activeTab', (val) => {
                sessionStorage.setItem('activeTab', val);
                if (val === 'config') { this.resetAccordions(); this.loadContactConfig(); }
                if (val === 'docs') { this.loadPdfs(); this.loadCsvs(); }
                if (val === 'faqs') this.loadFaqs();
                if (val === 'logs') { this.loadLogs(); this.searchQuery = ''; }
                if (val === 'dashboard') { 
                    this.dashboardAccordionState.health = false;
                    this.dashboardAccordionState.charts = true;
                    this.dashboardAccordionState.errorCategories = false; 
                    this.loadTelemetry(); 
                    this.loadHealth();
                    // Polling cada 30s para reflejar cambios de estado en tiempo real
                    if (this.healthPollInterval) clearInterval(this.healthPollInterval);
                    this.healthPollInterval = setInterval(() => this.loadHealth(true), 30000);
                } else {
                    if (this.healthPollInterval) { clearInterval(this.healthPollInterval); this.healthPollInterval = null; }
                }
                if (val === 'reports') this.loadSchedules();
                if (val !== 'dashboard') this.destroyCharts();
            });
            this.$watch('scheduleForm.tipo', (val) => {
                const tipo = this.scheduleForm.tipos.find(t => t.id === val);
                this.scheduleForm.selectedTipoParams = tipo ? tipo.parametros || [] : [];
                // Reset params when tipo changes
                this.scheduleForm.params = {};
            });

            // Carga inicial: esperar a que el token de auth esté disponible
            // antes de hacer llamadas a la API (mismo patrón que instances.js).
            // Usamos setTimeout(0) para que Alpine termine de inicializar el
            // componente antes de cualquier llamada async.
            const auth = Alpine.store('auth');
            const boot = () => {
                const token = Alpine.store('auth')?.token;
                if (!token) return;
                setTimeout(() => {
                    this.loadContactConfig();
                    this.loadActiveInstance();
                    this.loadQuickStats();
                    this.loadSchedules();
                    if (this.activeTab === 'dashboard') {
                        this.loadTelemetry();
                        this.loadHealth();
                        if (!this.healthPollInterval) {
                            this.healthPollInterval = setInterval(() => this.loadHealth(true), 30000);
                        }
                    }
                    if (this.activeTab === 'reports') this.loadSchedules();
                }, 0);
            };
            if (auth && auth.verified && auth.token) {
                boot();
            } else {
                this.$watch('$store.auth.verified', (verified) => {
                    if (verified && Alpine.store('auth')?.token) boot();
                });
                this.$watch('$store.auth.token', (token) => {
                    if (token && Alpine.store('auth')?.verified) boot();
                });
            }
            // Load destino history from localStorage
            try {
                const stored = localStorage.getItem('destinoHistory');
                if (stored) this.scheduleForm.destinoHistory = JSON.parse(stored);
            } catch (e) {
                this.scheduleForm.destinoHistory = [];
            }
            // Escuchar cambios de instancia activa desde el panel de instancias
            window.addEventListener('active-instance-changed', () => {
                this.loadActiveInstance();
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
            sessionStorage.setItem('activeTab', tab);
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
                if (data.status === "success") this.googleApiKeySet = true;
                window.showToast(data.message, data.status === "success" ? 'success' : 'error');
            } catch (err) {
                this.apiStatus = "✕ Error de conexión";
                window.showToast('Error de conexión al guardar API Key', 'error');
            }
        },

        // --- EVOLUTION API KEY ---
        async saveEvolutionKey() {
            if (!this.evoApiKey) {
                this.evoApiStatus = "⚠ Escribe una clave";
                this.evoApiStatusClass = "mt-3 text-orange-500 font-medium h-5";
                return;
            }
            const formData = new FormData();
            formData.append("key", this.evoApiKey);
            try {
                const res = await apiFetch('/api/evolution-apikey', { method: 'POST', body: formData });
                const data = await res.json();
                this.evoApiStatus = data.message;
                this.evoApiStatusClass = data.status === "success" ? "mt-3 text-green-600 font-medium h-5" : "mt-3 text-red-600 font-medium h-5";
                if (data.status === "success") this.evolutionApiKeySet = true;
                window.showToast(data.message, data.status === "success" ? 'success' : 'error');
            } catch (err) {
                this.evoApiStatus = "✕ Error de conexión";
                this.evoApiStatusClass = "mt-3 text-red-600 font-medium h-5";
                window.showToast('Error de conexión al guardar API Key de Evolution', 'error');
            }
        },

        // --- CONFIG ---
        async loadActiveInstance() {
            try {
                const res = await apiFetch('/api/evolution/active');
                if (res.ok) {
                    const data = await res.json();
                    this.activeInstanceName = data.name || '';
                } else {
                    this.activeInstanceName = '';
                }
            } catch (err) {
                this.activeInstanceName = '';
                window.showToast('Error al verificar instancia activa', 'error');
            } finally {
                this.activeInstanceLoaded = true;
            }
        },

        async loadContactConfig() {
            try {
                const res = await apiFetch('/api/config');
                const data = await res.json();

                this.configBotTone = data.bot_tone || 'profesional';
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
                this.activeGeminiModel = data.gemini_model || '';
                this.activeGeminiEmbeddingsModel = data.gemini_embeddings_model || '';
                this.googleApiKeySet = data.google_api_key_set || false;
                this.evolutionApiKeySet = data.evolution_api_key_set || false;
            } catch (err) {
                console.error("Error al cargar config", err);
                window.showToast('Error al cargar configuración', 'error');
            }
        },

        async saveContactConfig() {
            this.configStatus = "⏳ Guardando...";
            this.configStatusClass = "mt-3 text-blue-500 text-sm font-medium h-5";

            const telefonoFinal = `${this.configPhoneCode} ${this.configPhoneNum}`.trim();
            const formData = new FormData();
            if(this.configBotTone) formData.append("bot_tone", this.configBotTone);
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
                if (data.status === "success") {
                    this.activeGeminiModel = this.geminiModel;
                    this.activeGeminiEmbeddingsModel = this.geminiEmbeddingsModel;
                }
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
                window.showToast('Error al cargar documentos', 'error');
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
                window.showToast('Error al cargar CSVs', 'error');
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
                window.showToast('Error al cargar logs', 'error');
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
                window.showToast('Error al buscar logs', 'error');
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
                window.showToast('Error al leer conversación', 'error');
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
            if (!confirm(`¿Eliminar la pregunta "${faq.pregunta}"? Esta acción no se puede deshacer.`)) return;
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

        // --- DASHBOARD ---
        async loadTelemetry() {
            this.destroyCharts();
            this.telemetryLoading = true;
            this.telemetryError = '';
            this.telemetryData = null;
            try {
                const res = await apiFetch('/api/telemetry/summary?days=7');
                const json = await res.json();
                if (json.status !== 'success') throw new Error(json.message);
                // Map backend field names to frontend-expected names
                const d = json.data;
                this.telemetryData = {
                    ...d,
                    total_errors: d.error_count || 0,
                    error_rate: d.total_messages > 0 ? ((d.error_count / d.total_messages) * 100).toFixed(1) : 0,
                    avg_rag_duration_ms: d.avg_rag_ms || 0,
                    avg_send_duration_ms: d.avg_send_ms || 0,
                    avg_total_duration_ms: (d.avg_rag_ms || 0) + (d.avg_send_ms || 0),
                    total_faq_hits: d.faq_hits || 0,
                    total_cache_hits: d.cache_hits || 0,
                    messages_by_day: (d.daily || []).map(day => ({ date: day.date, count: day.total_messages })),
                    error_categories: d.error_categories || {},
                    error_types: d.error_types || [],
                };
                await this.$nextTick();
                this.initCharts();
            } catch (e) {
                this.telemetryError = 'Error al cargar el dashboard';
                window.showToast('Error al cargar dashboard', 'error');
            } finally {
                this.telemetryLoading = false;
            }
            this.loadQuickStats();
        },

        initCharts() {
            this.destroyCharts();
            if (!window.Chart || !this.telemetryData) return;
            const data = this.telemetryData;

            Chart.defaults.font.family = "'Inter', sans-serif";

            // Messages per day bar chart
            this.charts.push(new Chart(this.$refs.chartMessages, {
                type: 'bar',
                data: {
                    labels: data.messages_by_day.map(d => d.date.slice(5)),
                    datasets: [{ label: 'Mensajes', data: data.messages_by_day.map(d => d.count), backgroundColor: '#3B82F6' }]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
            }));

            // Error rate doughnut
            this.charts.push(new Chart(this.$refs.chartErrors, {
                type: 'doughnut',
                data: {
                    labels: ['Éxito', 'Error'],
                    datasets: [{ data: [data.total_messages - data.total_errors, data.total_errors], backgroundColor: ['#22C55E', '#EF4444'] }]
                },
                options: { responsive: true, maintainAspectRatio: false, cutout: '60%', plugins: { legend: { position: 'bottom' } } }
            }));

            // Avg durations bar chart
            this.charts.push(new Chart(this.$refs.chartDurations, {
                type: 'bar',
                data: {
                    labels: ['RAG', 'Envío', 'Total'],
                    datasets: [{ label: 'ms', data: [data.avg_rag_duration_ms, data.avg_send_duration_ms, data.avg_total_duration_ms], backgroundColor: ['#F59E0B', '#3B82F6', '#8B5CF6'] }]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
            }));

            // Source distribution doughnut
            this.charts.push(new Chart(this.$refs.chartSources, {
                type: 'doughnut',
                data: {
                    labels: ['FAQ', 'Cache', 'RAG / Generación'],
                    datasets: [{ data: [data.total_faq_hits, data.total_cache_hits, data.total_messages - data.total_faq_hits - data.total_cache_hits], backgroundColor: ['#06B6D4', '#F59E0B', '#3B82F6'] }]
                },
                options: { responsive: true, maintainAspectRatio: false, cutout: '60%', plugins: { legend: { position: 'bottom' } } }
            }));

            // Error categories bar chart (only if errors exist)
            if (data.total_errors > 0 && data.error_categories && Object.keys(data.error_categories).length > 0) {
                const catLabels = Object.keys(data.error_categories).map(k => this.errorCategoryLabels[k] || k);
                const catValues = Object.values(data.error_categories);
                const catColors = Object.keys(data.error_categories).map(k => {
                    const colorMap = { 'E-COM': '#3B82F6', 'E-RAG': '#EF4444', 'E-CFG': '#F59E0B', 'E-API': '#8B5CF6', 'E-SYS': '#6B7280', 'E-FAQ': '#06B6D4', 'E-TEL': '#10B981' };
                    return colorMap[k] || '#9CA3AF';
                });
                this.charts.push(new Chart(this.$refs.chartErrorCategories, {
                    type: 'bar',
                    data: {
                        labels: catLabels,
                        datasets: [{ label: 'Errores', data: catValues, backgroundColor: catColors }]
                    },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } } }
                }));
            }
        },

        // --- SCHEDULES (Informes Programados) ---
        async loadSchedules() {
            try {
                const [schedRes, tiposRes] = await Promise.all([
                    apiFetch('/api/reportes/schedules'),
                    apiFetch('/api/reportes/tipos')
                ]);
                if (schedRes.ok) this.schedules = await schedRes.json();
                if (tiposRes.ok) {
                    const tiposData = await tiposRes.json();
                    this.scheduleForm.tipos = tiposData.tipos || [];
                }
            } catch (err) {
                console.error('Error al cargar schedules', err);
                window.showToast('Error al cargar informes programados', 'error');
            }
        },

        getScheduleTipoName(tipoId) {
            const tipo = this.scheduleForm.tipos.find(t => t.id === tipoId);
            return tipo ? tipo.nombre : tipoId;
        },

        formatScheduleTime(hora) {
            if (!hora) return '';
            // hora_envio from DB comes as HH:MM:SS or HH:MM
            return String(hora).substring(0, 5);
        },

        startCreateSchedule() {
            const f = this.scheduleForm;
            f.open = true;
            f.editId = null;
            f.tipo = '';
            f.hora_envio = '08:00';
            f.destino = '';
            f.header_text = '';
            f.footer_text = '';
            f.params = {};
            f.selectedTipoParams = [];
            f.saving = false;
            f.errors = { tipo: '', hora_envio: '', destino: '' };
        },

        startEditSchedule(sched) {
            const f = this.scheduleForm;
            f.open = true;
            f.editId = sched.id;
            f.tipo = sched.tipo;
            // Format time from HH:MM:SS to HH:MM for the time input
            f.hora_envio = this.formatScheduleTime(sched.hora_envio);
            f.destino = sched.destino;
            f.header_text = sched.header_text || '';
            f.footer_text = sched.footer_text || '';
            // Populate params from existing schedule data
            f.params = typeof sched.parametros === 'string'
                ? JSON.parse(sched.parametros || '{}')
                : (sched.parametros || {});
            // Set selectedTipoParams to match the tipo (watcher will also update on tipo change)
            const tipo = f.tipos.find(t => t.id === sched.tipo);
            f.selectedTipoParams = tipo ? tipo.parametros || [] : [];
            f.saving = false;
            f.errors = { tipo: '', hora_envio: '', destino: '' };
        },

        cancelScheduleForm() {
            const f = this.scheduleForm;
            f.open = false;
            f.editId = null;
            f.tipo = '';
            f.hora_envio = '';
            f.destino = '';
            f.header_text = '';
            f.footer_text = '';
            f.params = {};
            f.selectedTipoParams = [];
            f.saving = false;
            f.errors = { tipo: '', hora_envio: '', destino: '' };
        },

        async saveSchedule() {
            const f = this.scheduleForm;
            // Validate
            f.errors = { tipo: '', hora_envio: '', destino: '' };
            if (!f.tipo) f.errors.tipo = 'Seleccioná un tipo de reporte.';
            if (!f.hora_envio) f.errors.hora_envio = 'Ingresá la hora de envío.';
            if (!f.destino.trim()) f.errors.destino = 'Ingresá el número de destino.';
            if (!f.valid) return;

            f.saving = true;
            const isEdit = !!f.editId;
            const url = isEdit ? `/api/reportes/schedules/${f.editId}` : '/api/reportes/schedules';
            const method = isEdit ? 'PUT' : 'POST';
            const body = isEdit ? {
                tipo: f.tipo,
                parametros: f.params,
                hora_envio: f.hora_envio,
                destino: f.destino.trim(),
                header_text: f.header_text || null,
                footer_text: f.footer_text || null,
            } : {
                tipo: f.tipo,
                parametros: f.params,
                hora_envio: f.hora_envio,
                destino: f.destino.trim(),
                header_text: f.header_text || null,
                footer_text: f.footer_text || null,
            };

            try {
                const res = await apiFetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (res.ok || res.status === 201) {
                    window.showToast(isEdit ? 'Informe actualizado' : 'Informe programado', 'success');
                    // Save destino to history
                    const dest = f.destino.trim();
                    if (dest && !f.destinoHistory.includes(dest)) {
                        f.destinoHistory.unshift(dest);
                        if (f.destinoHistory.length > 10) f.destinoHistory = f.destinoHistory.slice(0, 10);
                        try {
                            localStorage.setItem('destinoHistory', JSON.stringify(f.destinoHistory));
                        } catch (e) { /* ignore storage errors */ }
                    }
                    this.cancelScheduleForm();
                    await this.loadSchedules();
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

        async toggleSchedule(sched) {
            try {
                const res = await apiFetch(`/api/reportes/schedules/${sched.id}/toggle`, { method: 'POST' });
                if (res.ok) {
                    window.showToast(sched.activo ? 'Programa desactivado' : 'Programa activado', 'success');
                    await this.loadSchedules();
                } else {
                    window.showToast('Error al cambiar estado', 'error');
                }
            } catch (err) {
                window.showToast('Error de conexión', 'error');
            }
        },

        async confirmDeleteSchedule(sched) {
            const tipoName = this.getScheduleTipoName(sched.tipo);
            if (!confirm(`¿Eliminar el programa de "${tipoName}" para ${sched.destino}? Esta acción no se puede deshacer.`)) return;
            try {
                const res = await apiFetch(`/api/reportes/schedules/${sched.id}`, { method: 'DELETE' });
                if (res.ok) {
                    window.showToast('Programa eliminado', 'success');
                    await this.loadSchedules();
                } else {
                    window.showToast('Error al eliminar', 'error');
                }
            } catch (err) {
                window.showToast('Error de conexión al eliminar', 'error');
            }
        },

        // --- DARK MODE ---
        toggleDarkMode() {
            this.darkMode = !this.darkMode;
            document.documentElement.classList.toggle('dark', this.darkMode);
            localStorage.setItem('darkMode', this.darkMode);
        },

        // --- PASSWORD CHANGE ---
        async changePassword() {
            this.changePasswordStatusClass = '';
            this.changePasswordStatus = '';

            if (!this.changePasswordCurrent || !this.changePasswordNew || !this.changePasswordConfirm) {
                this.changePasswordStatus = 'Completá todos los campos';
                this.changePasswordStatusClass = 'mt-3 text-orange-500 text-sm font-medium';
                return;
            }
            if (this.changePasswordNew.length < 4) {
                this.changePasswordStatus = 'La nueva contraseña debe tener al menos 4 caracteres';
                this.changePasswordStatusClass = 'mt-3 text-red-600 text-sm font-medium';
                return;
            }
            if (this.changePasswordNew !== this.changePasswordConfirm) {
                this.changePasswordStatus = 'Las contraseñas nuevas no coinciden';
                this.changePasswordStatusClass = 'mt-3 text-red-600 text-sm font-medium';
                return;
            }

            this.changePasswordLoading = true;
            const formData = new FormData();
            formData.append('current_password', this.changePasswordCurrent);
            formData.append('new_password', this.changePasswordNew);

            try {
                const res = await apiFetch('/api/auth/change-password', { method: 'POST', body: formData });
                const data = await res.json();
                if (res.ok) {
                    this.changePasswordStatus = data.message;
                    this.changePasswordStatusClass = 'mt-3 text-green-600 text-sm font-medium';
                    // Limpiar campos
                    this.changePasswordCurrent = '';
                    this.changePasswordNew = '';
                    this.changePasswordConfirm = '';
                    // Actualizar token
                    localStorage.setItem('token', data.token);
                    Alpine.store('auth').token = data.token;
                    window.showToast(data.message, 'success');
                } else {
                    const detail = (data.error && data.error.detail) || data.detail || 'Error al cambiar contraseña';
                    this.changePasswordStatus = detail;
                    this.changePasswordStatusClass = 'mt-3 text-red-600 text-sm font-medium';
                    window.showToast(detail, 'error');
                }
            } catch (err) {
                this.changePasswordStatus = 'Error de conexión';
                this.changePasswordStatusClass = 'mt-3 text-red-600 text-sm font-medium';
                window.showToast('Error de conexión al cambiar contraseña', 'error');
            } finally {
                this.changePasswordLoading = false;
            }
        },

        // --- QUICK STATS ---
        async loadQuickStats() {
            try {
                const res = await apiFetch('/api/telemetry/quick-stats');
                if (res.ok) {
                    this.quickStats = await res.json();
                }
            } catch (err) {
                // Silencioso: no queremos un toast cada vez que entra a dashboard
                this.quickStats = null;
            }
        },

        async loadHealth(silent = false) {
            if (!silent) this.healthLoading = true;
            try {
                const res = await apiFetch('/api/health');
                if (res.ok) this.healthData = await res.json();
            } catch (e) {
                this.healthData = null;
                if (!silent) window.showToast('Error al verificar estado del sistema', 'error');
            } finally {
                if (!silent) this.healthLoading = false;
            }
        },

        resetAccordions() {
            this.accordionState = {
                googleApiKey: !this.googleApiKeySet,
                evolutionApiKey: !this.evolutionApiKeySet,
                contactVars: false,
                botTone: false,
                geminiModels: false,
                password: false,
            };
        },

        destroyCharts() {
            this.charts.forEach(c => c.destroy());
            this.charts = [];
        },
    }));
});
