import { apiFetch } from './api.js';

export function initAuth(Alpine) {
    Alpine.store('auth', {
        token: localStorage.getItem('token'),
        // Flag que indica si `verify()` ya termino (true = sabemos
        // si el token es valido). Los componentes que dependan de
        // auth deben esperar a que sea true antes de disparar
        // requests; asi evitamos cargar datos con un token muerto
        // que devuelve 401 y dispara toasts de error confusos.
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
                }
            } catch {
                this.token = null;
                localStorage.removeItem('token');
            } finally {
                // Marcamos como verificado SIEMPRE (con o sin token,
                // con exito o error de red): cualquier estado terminal
                // es valido para que los componentes decidan que hacer.
                this.verified = true;
            }
        },

        init() {
            this.verify();
        },

        async login(username, password) {
            const fd = new FormData();
            fd.append('username', username);
            fd.append('password', password);
            const res = await apiFetch('/api/auth/login', { method: 'POST', body: fd });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Credenciales inválidas');
            }
            const data = await res.json();
            this.token = data.token;
            localStorage.setItem('token', data.token);
        },

        logout() {
            this.token = null;
            localStorage.removeItem('token');
        }
    });

    Alpine.data('loginForm', () => ({
        username: '',
        password: '',
        loading: false,
        error: '',
        async doLogin() {
            this.loading = true;
            this.error = '';
            try {
                await Alpine.store('auth').login(this.username, this.password);
            } catch (e) {
                this.error = e.message;
            } finally {
                this.loading = false;
            }
        }
    }));
}
