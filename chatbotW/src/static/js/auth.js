import { apiFetch } from './api.js';

// Inactividad timeout (30 minutos sin actividad = auto logout)
const INACTIVITY_TIMEOUT = 30 * 60 * 1000;
let inactivityTimer = null;
let refreshInterval = null;

function resetInactivityTimer() {
    if (inactivityTimer) clearTimeout(inactivityTimer);
    inactivityTimer = setTimeout(() => {
        Alpine.store('auth').logout();
    }, INACTIVITY_TIMEOUT);
}

function startInactivityTracking() {
    // Eventos que cuentan como actividad del usuario
    const events = ['mousedown', 'keydown', 'touchstart', 'scroll'];
    events.forEach(event => {
        document.addEventListener(event, resetInactivityTimer, { passive: true });
    });
    resetInactivityTimer();
}

function startTokenRefresh(token) {
    if (refreshInterval) clearInterval(refreshInterval);
    // Refrescar token cada 30 minutos
    refreshInterval = setInterval(async () => {
        try {
            const res = await fetch('/api/auth/refresh', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const data = await res.json();
                localStorage.setItem('token', data.token);
                Alpine.store('auth').token = data.token;
            } else {
                Alpine.store('auth').logout();
            }
        } catch {
            // Error de red — mantener token actual, fallará en el próximo request
        }
    }, 30 * 60 * 1000);
}

function stopTimers() {
    if (inactivityTimer) clearTimeout(inactivityTimer);
    if (refreshInterval) clearInterval(refreshInterval);
}

export function initAuth(Alpine) {
    Alpine.store('auth', {
        token: localStorage.getItem('token'),
        verified: false,

        async verify() {
            try {
                if (!this.token) return;
                const res = await apiFetch('/api/auth/verify', {
                    headers: { 'Authorization': `Bearer ${this.token}` }
                });
                const data = await res.json();
                if (!data.valid) {
                    this.token = null;
                    localStorage.removeItem('token');
                } else {
                    // Token válido — iniciar refresh e inactivity tracking
                    startTokenRefresh(this.token);
                    startInactivityTracking();
                }
            } catch {
                this.token = null;
                localStorage.removeItem('token');
            } finally {
                this.verified = true;
            }
        },

        init() {
            this.verify();
        },

        async login(password) {
            const fd = new FormData();
            fd.append('password', password);
            const res = await apiFetch('/api/auth/login', { method: 'POST', body: fd });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Contraseña incorrecta');
            }
            const data = await res.json();
            this.token = data.token;
            localStorage.setItem('token', data.token);
            startTokenRefresh(data.token);
            startInactivityTracking();
        },

        logout() {
            stopTimers();
            this.token = null;
            localStorage.removeItem('token');
        }
    });

    Alpine.data('loginForm', () => ({
        password: '',
        showPassword: false,
        loading: false,
        error: '',
        loginShake: false,
        async doLogin() {
            this.loading = true;
            this.error = '';
            try {
                await Alpine.store('auth').login(this.password);
            } catch (e) {
                this.error = e.message;
                this.loginShake = true;
            } finally {
                this.loading = false;
            }
        }
    }));
}
