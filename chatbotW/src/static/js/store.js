import { apiFetch } from './api.js';

export function initStores(Alpine) {
    Alpine.store('app', {
        botPhone: '',
    });

    Alpine.store('csvEditor', {
        show: false,
        filename: '',
        headers: [],
        rows: [],
        loading: false,
        saving: false,
        status: '',
        statusClass: '',
        dirty: false,

        markDirty() {
            this.dirty = true;
        },

        async edit(filename) {
            if (this.show && this.dirty) {
                if (!confirm('Tenés cambios sin guardar. ¿Seguro que querés descartarlos?')) return;
            }
            this.dirty = false;
            this.show = true;
            this.filename = filename;
            this.loading = true;
            this.status = '';
            try {
                const res = await apiFetch(`/api/csvs/${filename}/data`);
                const data = await res.json();
                this.headers = data.headers;
                this.rows = data.rows;
            } catch (err) {
                this.status = '❌ Error al cargar datos';
                this.statusClass = 'text-red-600';
            } finally {
                this.loading = false;
            }
        },

        async save() {
            this.saving = true;
            this.status = '⏳ Guardando...';
            this.statusClass = 'text-blue-500';
            try {
                const res = await apiFetch(`/api/csvs/${this.filename}/data`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        headers: this.headers,
                        rows: this.rows
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    this.status = '✅ Cambios guardados';
                    this.statusClass = 'text-green-600';
                    this.dirty = false;
                } else {
                    this.status = `❌ ${data.detail || 'Error al guardar'}`;
                    this.statusClass = 'text-red-600';
                }
            } catch (err) {
                this.status = '❌ Error de conexión';
                this.statusClass = 'text-red-600';
            } finally {
                this.saving = false;
                setTimeout(() => this.status = '', 3000);
            }
        },

        addRow() {
            const empty = new Array(this.headers.length).fill('');
            this.rows.push(empty);
            this.markDirty();
        },

        removeRow(index) {
            if (this.dirty && !confirm('¿Eliminar esta fila?')) return;
            this.rows.splice(index, 1);
            this.markDirty();
        },

        cancel(force = false) {
            if (!force && this.dirty && !confirm('Descartar cambios?')) return;
            this.show = false;
            this.filename = '';
            this.headers = [];
            this.rows = [];
            this.dirty = false;
            this.status = '';
        }
    });

    Alpine.store('toasts', {
        list: [],
        add(message, type = 'info') {
            const id = Date.now();
            this.list.push({ id, message, type });
            setTimeout(() => this.remove(id), 3000);
        },
        remove(id) {
            this.list = this.list.filter(t => t.id !== id);
        }
    });

    window.showToast = function(message, type) {
        Alpine.store('toasts').add(message, type);
    };
}
