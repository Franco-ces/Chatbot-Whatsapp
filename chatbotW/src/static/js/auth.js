import { apiFetch } from './api.js';

export function initAuth(Alpine) {
    Alpine.store('auth', {
        token: localStorage.getItem('token'),

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
