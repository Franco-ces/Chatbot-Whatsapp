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
        activeName: '',
        loading: false,
        selected: null,
        showQr: false,
        showSwap: false,
        qrPolling: null,
        acknowledge: false,
        swapTarget: null,
        swapError: '',
        createForm: { name: '', error: '', saving: false },
        openMenus: [], // Nombres de las instancias con menú kebab abierto (permite múltiples)
        _instancesPoll: null, // Interval ID para polling silencioso de estados
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

        isActive(inst) {
            // El backend devuelve la activa en /api/evolution/active
            // (es lo que esta en `config_bot.json`). Comparamos por
            // nombre: Evolution permite nombres duplicados solo si
            // son unicos, asi que el match es 1:1.
            return inst && inst.name === this.activeName;
        },

        // ─── Init ─────────────────────────────────────────────────
        init() {
            // No llamar a loadInstances si no estamos autenticados: el
            // endpoint devuelve 401 y dispara un toast de error confuso
            // ANTES de que el usuario tenga chance de loguearse. En su
            // lugar, esperamos al $watch sobre el auth store y cargamos
            // cuando aparezca el token.
            //
            // Ademas, esperamos a `auth.verified` para no disparar el
            // load con un token muerto que esta en localStorage pero que
            // el backend ya rechazo. `verify()` corre async al boot;
            // si saltamos directo al `if (auth.token)`, la request sale
            // con un token invalido y el 401 se traduce en un toast
            // espurio. Por eso: (1) si `verified` ya es true, podemos
            // decidir ya; (2) si no, esperamos al watch y ahi decidimos
            // con el estado terminal del verify.
            const auth = Alpine.store('auth');
            const tryLoad = () => {
                // Re-leemos el store al disparar: entre el watch y el
                // callback `auth.token` puede haber cambiado (ej: el
                // verify determino que era invalido y lo limpio).
                if (Alpine.store('auth').token) this.loadInstances();
            };
            if (auth && auth.verified) {
                tryLoad();
            } else {
                this.$watch('$store.auth.verified', (verified) => {
                    if (verified) tryLoad();
                });
                // Edge case: si el usuario YA esta logueado cuando se
                // monta el componente (token en localStorage), el watch
                // sobre `verified` lo cubre. Pero si el token aparece
                // DESPUES (caso login fresco en la misma sesion), el
                // watch sobre `token` es el que dispara. Mantenemos
                // ambos para cubrir las dos ventanas de tiempo.
                this.$watch('$store.auth.token', (token) => {
                    if (token && Alpine.store('auth').verified) {
                        tryLoad();
                    }
                });
            }
            // Cerrar menús kebab al hacer click fuera de cualquier menú o kebab
            document.addEventListener('click', (e) => {
                if (this.openMenus.length === 0) return;
                const target = e.target;
                if (!target.closest('[data-kebab-menu]')) {
                    this.openMenus = [];
                }
            });

            // Polling silencioso cada 30s para reflejar cambios de estado
            // en tiempo real (ej: instancia huerfana cuando el usuario
            // desvincula WhatsApp desde su telefono).
            this._instancesPoll = setInterval(async () => {
                try {
                    await Promise.all([
                        this.refreshInstancesList(),
                        this.refreshActiveInstance(),
                    ]);
                    this._syncBotPhone();
                } catch (e) {
                    // Silencioso: no mostramos toast en polling
                }
            }, 30000);
        },

        // ─── List ─────────────────────────────────────────────────
        async refreshInstancesList() {
            // Recarga SOLO la lista de instancias. Usado por confirmSwap
            // despues de activar (el activeName se setea optimistamente;
            // no queremos pisarlo con el valor stale del server mientras
            // el write async del config esta en cola).
            try {
                const res = await apiFetch('/api/evolution/instances');
                if (res.ok) {
                    const data = await res.json();
                    this.instances = data.instances || [];
                } else if (res.status === 401) {
                    // Token expirado/invalido: auth.verify() lo va a
                    // limpiar de localStorage. No mostramos toast: es
                    // un estado esperado (el operador va a ver la
                    // pantalla de login), no un error de UI. Esto es
                    // una red de seguridad para el caso raro en que
                    // un request se cuele entre el verify y el init
                    // del componente. La fix de fondo es el `verified`
                    // flag en auth.js + el watch en este init().
                    //
                    // NO clobereamos `this.instances` aca: si el
                    // operador ya tenia una lista renderizada (caso
                    // swap/deactivate con sesion larga en la que el
                    // token expiro entre la accion y el refresh),
                    // preservarla es mejor UX que vaciarla de repente.
                } else {
                    console.error('Error al cargar instancias', res.status);
                    window.showToast('Error al cargar instancias', 'error');
                }
            } catch (err) {
                console.error('Error al cargar instancias', err);
                window.showToast('Error al cargar instancias', 'error');
            }
        },

        async refreshActiveInstance() {
            // Recarga SOLO la instancia activa desde el server. Usado
            // por el boton Refrescar y por el init post-login.
            try {
                const res = await apiFetch('/api/evolution/active');
                if (res.ok) {
                    const data = await res.json();
                    this.activeName = data.name || '';
                } else {
                    this.activeName = '';
                }
            } catch (err) {
                this.activeName = '';
            }
        },

        async loadInstances() {
            this.loading = true;
            try {
                // Pedimos lista + activa en paralelo. La activa decide
                // que botones quedan deshabilitados (no se puede eliminar
                // la activa, y 'Activar' solo tiene sentido si NO es la
                // actual). Si el GET /active falla seguimos: la lista
                // se muestra igual, solo queda sin marca de activa.
                await Promise.all([
                    this.refreshInstancesList(),
                    this.refreshActiveInstance(),
                ]);
                // Sincronizar botPhone desde la instancia activa.
                // El telefono se extrae de ownerJid: "5491112345678@s.whatsapp.net"
                // → "5491112345678". Si no hay activa o ownerJid es null,
                // botPhone queda vacio y el boton de WhatsApp se deshabilita.
                this._syncBotPhone();
            } finally {
                this.loading = false;
            }
        },

        _syncBotPhone() {
            const active = this.instances.find(i => i.name === this.activeName);
            const phone = (active && active.ownerJid)
                ? active.ownerJid.split('@')[0]
                : '';
            Alpine.store('app').botPhone = phone;
        },

        async deleteInstance(inst) {
            if (!inst || !inst.name) return;
            // Doble guard por si el HTML se desincroniza: el backend
            // igual va a rechazar con 409 si la instancia es la activa.
            if (this.isActive(inst)) {
                window.showToast(
                    'No podés eliminar la instancia activa. Primero activá otra.',
                    'error'
                );
                return;
            }
            const name = inst.name;
            // `window.confirm` bloquea el thread; suficiente para una
            // accion destructiva sin meter un modal entero.
            const ok = window.confirm(
                `¿Eliminar la instancia "${name}" de Evolution? `
                + 'Esta acción no se puede deshacer (también se borra '
                + 'su sesión de WhatsApp si está vinculada).'
            );
            if (!ok) return;
            try {
                const res = await apiFetch(
                    `/api/evolution/instances/${encodeURIComponent(name)}`,
                    { method: 'DELETE' }
                );
                if (res.status === 204) {
                    window.showToast(`Instancia '${name}' eliminada`, 'success');
                    await this.loadInstances();
                } else {
                    // 404, 409, 5xx, etc. El backend ya formatea el error.
                    const err = await res.json().catch(() => ({}));
                    const detail = (err.error && err.error.detail)
                        || `Error al eliminar (HTTP ${res.status})`;
                    window.showToast(detail, 'error');
                }
            } catch (err) {
                console.error('Error al eliminar instancia', err);
                window.showToast('Error de conexión al eliminar', 'error');
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
                    // `fromCreate: true` le pide al modal que auto-active
                    // cuando el QR marque `open` (solo si no hay otra
                    // activa). La vista de lista no setea este flag.
                    const fromList = this.instances.find(i => i.name === name);
                    await this.openQrModal(fromList || created, { fromCreate: true });
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

        // ─── Kebab Menu ─────────────────────────────────────────
        toggleMenu(instName) {
            // Alterna el menú kebab: puede haber múltiples abiertos
            const idx = this.openMenus.indexOf(instName);
            if (idx >= 0) {
                this.openMenus.splice(idx, 1);
            } else {
                this.openMenus.push(instName);
            }
        },
        isMenuOpen(instName) {
            return this.openMenus.includes(instName);
        },
        closeAllMenus() {
            this.openMenus = [];
        },

        // ─── Deactivate Instance ────────────────────────────────
        async deactivateInstance(inst) {
            if (!inst || !inst.name) return;
            const name = inst.name;
            // Solo se puede desactivar la instancia activa
            if (!this.isActive(inst)) {
                window.showToast(
                    'Solo podés desactivar la instancia activa.',
                    'error'
                );
                return;
            }
            const ok = window.confirm(
                `¿Desactivar la instancia "${name}"? `
                + 'El bot dejará de recibir mensajes hasta que actives otra.'
            );
            if (!ok) return;
            try {
                const res = await apiFetch(
                    `/api/evolution/instances/${encodeURIComponent(name)}/deactivate`,
                    { method: 'POST' }
                );
                if (res.ok) {
                    window.showToast(`Instancia "${name}" desactivada`, 'success');
                    // Optimista: el server ya deshabilito el webhook (parte
                    // critica) y encolo el clear del config. El GET /active
                    // puede devolver el valor viejo durante ~100s mientras
                    // el worker drena la cola. Marcamos activeName='' para
                    // que la UI muestre el estado consistente con lo que
                    // el usuario espera, y refrescamos SOLO la lista (no
                    // pisamos activeName con el stale del server).
                    this.activeName = '';
                    window.dispatchEvent(new CustomEvent('active-instance-changed'));
                    await this.refreshInstancesList();
                    this._syncBotPhone();
                } else {
                    const err = await res.json().catch(() => ({}));
                    const detail = (err.error && err.error.detail)
                        || `Error al desactivar (HTTP ${res.status})`;
                    window.showToast(detail, 'error');
                }
            } catch (err) {
                console.error('Error al desactivar instancia', err);
                window.showToast('Error de conexión al desactivar', 'error');
            }
        },

        // ─── Copy wa.me link ──────────────────────────────────────
        async copyWaLink(inst) {
            // Defense in depth: el binding :disabled del HTML ya cubre
            // ownerJid null, pero si alguien llama al metodo por devtools
            // o si el binding se desincroniza, no queremos terminar con
            // un clipboard.writeText("https://wa.me/") (URL invalida).
            if (!inst || !inst.ownerJid) return;

            // Mismo regex que SesionLoggerManager._limpiar_numero
            // (src/sesionLoggerManager.py:160) y que el navbar del bot
            // (index.html:83). Strip de cualquier sufijo @-lo-que-sea,
            // no solo @s.whatsapp.net, por si Evolution cambia el formato.
            const local = String(inst.ownerJid).replace(/@.*$/, '');

            // Edge case: JID corrupto tipo "@s.whatsapp.net" — el strip
            // devuelve "". Sin este guard copiariamos un link roto y
            // el usuario no se entera.
            if (!local) {
                window.showToast('Número inválido para esta instancia', 'error');
                return;
            }

            const url = 'https://wa.me/' + local;
            // Admin UI = 127.0.0.1:8000 (contexto seguro), no hace falta
            // fallback execCommand. try/catch convierte cualquier rechazo
            // del browser en un toast legible.
            try {
                await navigator.clipboard.writeText(url);
                window.showToast('Link copiado', 'success');
            } catch (err) {
                window.showToast('No se pudo copiar el link', 'error');
            }
        },

        // ─── QR Modal ─────────────────────────────────────────────
        async openQrModal(inst, opts = {}) {
            this.selected = inst;
            this._qrPayload = null;
            this.acknowledge = false; // reset on every modal open
            // Si entramos desde el flow "crear instancia nueva", queremos
            // auto-activar en cuanto el QR marque `open` (siempre que no
            // haya OTRA activa — sino seria un swap silencioso sobre
            // una instancia sana). La vista de lista nunca setea este
            // flag, asi que el QR ahi es puramente informativo.
            this._pendingAutoActivate = opts.fromCreate === true;
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
                if (data.state === 'open') {
                    this.stopQrPoll();
                    // Auto-activar SOLO si entramos por el flow create
                    // y no hay otra activa. La condicion de "no hay otra"
                    // es critica: auto-activar sobre una activa sana
                    // seria un swap destructivo que el operador no pidio.
                    if (this._pendingAutoActivate && !this.activeName) {
                        this._pendingAutoActivate = false;
                        await this.activateQuietly(this.selected.name);
                    }
                }
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

        async activateQuietly(name) {
            // Activacion sin modal ni confirmacion. Pensada para el
            // flow create->scan->auto: cuando el QR confirma `open`
            // y no hay otra activa, vinculamos en el mismo tick.
            // Si algo falla (red, 409, etc.) NO mostramos error bloqueante:
            // la instancia ya existe y el operador puede tocar "Activar"
            // a mano desde la lista. Solo avisamos para que sepa que
            // quedo pendiente.
            this._pendingAutoActivate = false;
            try {
                const res = await apiFetch('/api/evolution/active', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name }),
                });
                if (res.ok) {
                    window.showToast(`Instancia '${name}' activada`, 'success');
                    window.dispatchEvent(new CustomEvent('active-instance-changed'));
                    await this.loadInstances();
                } else {
                    const err = await res.json().catch(() => ({}));
                    const detail = (err.error && err.error.detail) || 'Error al activar';
                    window.showToast(
                        `${detail}. Cliqueá Activá para hacerlo a mano.`,
                        'warning'
                    );
                }
            } catch (err) {
                console.error('Error al auto-activar instancia', err);
                window.showToast(
                    'No se pudo activar automáticamente. Cliqueá Activá.',
                    'warning'
                );
            }
        },

        closeQrModal() {
            this.stopQrPoll();
            const dlg = this.$refs.qrDialog;
            if (dlg && dlg.open) dlg.close();
            this.showQr = false;
            this.selected = null;
            this._qrPayload = null;
            // El flag es por-apertura: si el operador cierra el modal
            // antes de escanear, no queremos dispararlo en una apertura
            // posterior (ej: re-abre la lista y toca el boton QR).
            this._pendingAutoActivate = false;
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
                    // Optimista: la parte crítica (disable_webhook +
                    // set_webhook) ya está hecha en el server. El write
                    // del config corre async en background; el GET /active
                    // puede devolver el valor VIEJO durante ~100s mientras
                    // el worker drena la cola. Marcamos activeName acorde
                    // a lo que el usuario espera y refrescamos SOLO la
                    // lista (no pisamos activeName con el stale del server).
                    this.activeName = name;
                    window.dispatchEvent(new CustomEvent('active-instance-changed'));
                    await this.refreshInstancesList();
                    this._syncBotPhone();
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
