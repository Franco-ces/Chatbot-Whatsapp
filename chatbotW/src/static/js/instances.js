// instances.js — Alpine component for the WhatsApp Instance admin tab.
// See design.md §SPA Module Layout for the state shape and method list.
//
// Lifecycle: registered via app.js's `alpine:init` listener. State lives
// in the component instance; nothing leaks to Alpine stores. The `init()`
// hook (Alpine's name for the constructor) kicks off the initial
// `loadInstances()` so the table is populated the first time the tab
// becomes visible.

import { apiFetch } from './api.js';

const QR_POLL_INTERVAL_MS = 5000;

export function initInstancesPanel(Alpine) {
    Alpine.data('instancesPanel', () => ({
        // ─── State ─────────────────────────────────────────────────
        instances: [],
        loading: false,
        selected: null,
        showQr: false,
        showSwap: false,
        qrPolling: null,
        acknowledge: false,
        swapTarget: null,
        swapError: '',
        createForm: { name: '', error: '', saving: false },
        // `createForm` se declara aca, no en el HTML, para que el panel
        // sea self-contained: el state vive en el componente Alpine y
        // `x-model="createForm.name"` en el form apunta directamente a
        // esta propiedad. Declararlo dos veces (aca y al final del
        // objeto) no rompe nada pero ensucia: solo necesitamos UNA.

        // ─── Computed ─────────────────────────────────────────────
        get canActivate() {
            return this.acknowledge
                && this.swapTarget
                && this.swapTarget.connectionState === 'open';
        },

        // ─── Init ─────────────────────────────────────────────────
        init() {
            this.loadInstances();
        },

        // ─── List ─────────────────────────────────────────────────
        async loadInstances() {
            this.loading = true;
            try {
                const res = await apiFetch('/api/evolution/instances');
                if (res.ok) {
                    const data = await res.json();
                    this.instances = data.instances || [];
                }
            } catch (err) {
                console.error('Error al cargar instancias', err);
                window.showToast('Error al cargar instancias', 'error');
            } finally {
                this.loading = false;
            }
        },

        async createInstance() {
            // Pulled from the form bound to this.createForm in the HTML.
            const form = this.createForm;
            const name = (form.name || '').trim();
            form.error = '';
            if (!name) {
                form.error = 'Escribí un nombre para la instancia.';
                return;
            }
            form.saving = true;
            try {
                const res = await apiFetch('/api/evolution/instances', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name }),
                });
                if (res.status === 201) {
                    const created = await res.json();
                    window.showToast('Instancia creada', 'success');
                    form.name = '';
                    await this.loadInstances();
                    // Abrimos el modal QR con la instancia recién creada
                    // para que el operador la escanee. Sin este paso el
                    // flow terminaba en el toast y la instancia quedaba
                    // en estado `close` sin que el bot la vinculara.
                    // Preferimos la versión de la lista refrescada (tiene
                    // los alias correctos); caemos a la respuesta del POST
                    // si no aparece (drift raro entre Evolution y el list).
                    const fromList = this.instances.find(i => i.name === name);
                    await this.openQrModal(fromList || created);
                } else {
                    const err = await res.json().catch(() => ({}));
                    const detail = (err.error && err.error.detail) || 'Error al crear';
                    form.error = detail;
                    window.showToast(detail, 'error');
                }
            } catch (err) {
                form.error = 'Error de conexión';
                window.showToast('Error de conexión al crear', 'error');
            } finally {
                form.saving = false;
            }
        },

        // ─── QR Modal ─────────────────────────────────────────────
        async openQrModal(inst) {
            this.selected = inst;
            this._qrPayload = null;
            this.acknowledge = false; // reset on every modal open
            this.showQr = true;
            // Native <dialog> needs .showModal() to be modal + escapeable.
            // x-show only toggles display; we call the API in nextTick so
            // the dialog is in the DOM (it is — x-show keeps it mounted).
            this.$nextTick(() => {
                const dlg = this.$refs.qrDialog;
                if (dlg && typeof dlg.showModal === 'function') {
                    dlg.showModal();
                }
                this.focusFirstInModal();
            });
            await this.refreshQr();
            this.startQrPoll();
        },

        async refreshQr() {
            if (!this.selected) return;
            try {
                const res = await apiFetch(
                    `/api/evolution/instances/${encodeURIComponent(this.selected.name)}/qr`
                );
                if (!res.ok) return;
                const data = await res.json();
                if (this.selected) {
                    this.selected.connectionState = data.state;
                }
                this._qrPayload = data;
                // Si la instancia ya esta abierta, paramos de pollear.
                if (data.state === 'open') this.stopQrPoll();
            } catch (err) {
                console.error('Error al obtener QR', err);
            }
        },

        startQrPoll() {
            this.stopQrPoll();
            this.qrPolling = setInterval(() => this.refreshQr(), QR_POLL_INTERVAL_MS);
        },

        stopQrPoll() {
            if (this.qrPolling !== null) {
                clearInterval(this.qrPolling);
                this.qrPolling = null;
            }
        },

        closeQrModal() {
            this.stopQrPoll();
            const dlg = this.$refs.qrDialog;
            if (dlg && dlg.open) dlg.close();
            this.showQr = false;
            this.selected = null;
            this._qrPayload = null;
        },

        // ─── Swap Modal ───────────────────────────────────────────
        openSwapModal(inst) {
            this.swapTarget = inst;
            this.swapError = '';
            this.acknowledge = false; // mandatory reset per spec
            this.showSwap = true;
            this.$nextTick(() => this.focusFirstInModal());
        },

        closeSwapModal() {
            this.showSwap = false;
            this.swapTarget = null;
            this.swapError = '';
            this.acknowledge = false;
        },

        async confirmSwap() {
            if (!this.canActivate) return;
            const name = this.swapTarget.name;
            try {
                const res = await apiFetch('/api/evolution/active', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name }),
                });
                if (res.ok) {
                    window.showToast(`Instancia '${name}' activada`, 'success');
                    this.closeSwapModal();
                    await this.loadInstances();
                } else {
                    const err = await res.json().catch(() => ({}));
                    const detail = (err.error && err.error.detail) || 'Error al activar';
                    this.swapError = detail;
                    window.showToast(detail, 'error');
                }
            } catch (err) {
                this.swapError = 'Error de conexión';
                window.showToast('Error de conexión al activar', 'error');
            }
        },

        // ─── Modal: focus trap + Esc ─────────────────────────────
        focusFirstInModal() {
            // Find the open dialog (by [role=dialog] or <dialog>) and
            // move focus into it. Used by the focus-trap handler.
            const dialog = document.querySelector(
                '[role="dialog"][aria-modal="true"]:not(.hidden), dialog[open]'
            );
            if (!dialog) return;
            const focusable = this._focusableIn(dialog);
            if (focusable.length > 0) focusable[0].focus();
        },

        _focusableIn(root) {
            const sel = [
                'a[href]',
                'button:not([disabled])',
                'input:not([disabled])',
                'select:not([disabled])',
                'textarea:not([disabled])',
                '[tabindex]:not([tabindex="-1"])',
            ].join(',');
            return Array.from(root.querySelectorAll(sel));
        },

        trapTabKey(event) {
            // Wired via @keydown.tab on each dialog. Capture-phase handler
            // keeps focus inside the modal when Tab/Shift+Tab would escape.
            const dialog = event.currentTarget;
            if (!dialog) return;
            const focusable = this._focusableIn(dialog);
            if (focusable.length === 0) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        },

        onModalKeydown(event) {
            // Esc closes the active modal AND resets the acknowledgement
            // (per spec: "Esc closes the modal AND resets acknowledge").
            // Backdrop click is intentionally a no-op (no @click here).
            if (event.key === 'Escape') {
                if (this.showSwap) {
                    this.closeSwapModal();
                } else if (this.showQr) {
                    this.closeQrModal();
                }
            }
        },

    }));
}
