/* Tutorial interactivo de la app.
 * Sin librerías: se descarga recién cuando alguien toca el botón "?" del encabezado.
 * Cada paso resalta un elemento marcado con data-tour="..." y muestra una tarjeta con la explicación.
 * Los pasos cuyo elemento no está en la pantalla (o no se ve, p. ej. por el rol) se saltean solos.
 */
(function () {
  // Pasos por pantalla (request.endpoint de Flask). modal: true abre el modal de "Registrar movimiento".
  const PASOS = {
    index: [
      { titulo: '¡Bienvenido!', texto: 'Te muestro en un minuto cómo se usa la app. Podés salir cuando quieras y volver a verlo con el botón <b>?</b> de arriba.' },
      { sel: 'stock-total', titulo: 'Stock total', texto: 'Todo el huevo que hay en la granja, en <b>cajones + maples</b> (1 cajón = 12 maples). La barra muestra cuánto está <b class="t-verde">hecho</b> y cuánto <b class="t-ambar">sin hacer</b>.' },
      { sel: 'conteo', titulo: 'Conteo de inventario', texto: 'Si lo que hay en la granja no coincide con la app, cargá acá lo que contaste. Las diferencias quedan registradas como ajuste.' },
      { sel: 'acciones', titulo: 'Los 3 movimientos del día', texto: '<b>Ingreso:</b> entra huevo del galpón (queda sin hacer).<br><b>Clasificar:</b> pasa de sin hacer a hecho, por calibre.<br><b>Despacho:</b> sale huevo hecho hacia un cliente.' },
      { sel: 'sin-hacer', titulo: 'Sin hacer', texto: 'Huevo en el galpón que falta clasificar, por color. El botón <b>Clasificar</b> abre el formulario ya preparado.' },
      { sel: 'hecho', titulo: 'Hecho', texto: 'Huevo clasificado, listo para despachar. Cambiá entre blancos y de color, y tocá <b>Despachar</b> en el calibre que sale.' },
      { sel: 'ultimas', titulo: 'Últimas operaciones', texto: 'Lo último que se registró. Con <b>Ver todo</b> vas al historial completo.' },
      { sel: 'boton-mas', titulo: 'Registrar movimiento', texto: 'Este botón está en todas las pantallas. Abre el formulario para cargar cualquier movimiento. Veamos cómo es…' },
      { sel: 'op-tipos', modal: true, titulo: '1. Elegí qué hacés', texto: 'Ingreso, Clasificar o Despacho. Debajo te dice qué hace cada uno y, al clasificar o despachar, cuánto stock hay disponible.' },
      { sel: 'op-color', modal: true, titulo: '2. Color del huevo', texto: 'Blanco o de color. Al clasificar y despachar también vas a elegir el <b>calibre</b>.' },
      { sel: 'op-cantidad', modal: true, titulo: '3. Cantidad', texto: 'Escribí cajones y maples sueltos, o sumá rápido con <b>+1</b>, <b>+5</b> y <b>+10</b>. La flecha vuelve a cero.' },
      { sel: 'op-confirmar', modal: true, titulo: '4. Confirmá', texto: 'Revisá el total y confirmá. Si no alcanza el stock, el botón se bloquea y te explica por qué.' },
      { sel: 'nav-historial', titulo: 'Historial', texto: 'Todos los movimientos, agrupados por día, con quién los hizo.' },
      { sel: 'nav-usuarios', titulo: 'Usuarios', texto: 'Para administradores: crear operarios, cambiar contraseñas y permisos.' },
      { sel: 'ayuda', titulo: '¡Listo!', texto: 'Si te perdés, tocá este botón y te vuelvo a guiar. En cada pantalla te explico lo que hay en ella.' },
    ],
    historial: [
      { titulo: 'Historial', texto: 'Acá queda registrado todo lo que se hizo en la app.' },
      { sel: 'filtro-periodo', titulo: 'Período', texto: 'Mirá lo de hoy, los últimos 7 días o todo.' },
      { sel: 'filtro-tipo', titulo: 'Tipo de movimiento', texto: 'Filtrá por ingresos, clasificaciones, despachos o conteos. Deslizá de costado si no entran todos.' },
      { sel: 'lista', titulo: 'Movimientos', texto: 'Cada tarjeta dice qué se hizo, cuánto, a qué hora y quién lo registró.' },
      { sel: 'boton-mas', titulo: 'Registrar', texto: 'Desde acá también podés cargar un movimiento nuevo.' },
      { sel: 'ayuda', titulo: '¡Listo!', texto: 'Tocá <b>?</b> cuando necesites ayuda.' },
    ],
    usuarios: [
      { titulo: 'Usuarios', texto: 'Acá manejás quién puede entrar a la app.' },
      { sel: 'nuevo-usuario', titulo: 'Nuevo usuario', texto: 'Cargá nombre, usuario y contraseña. <b>Operario</b> registra movimientos; <b>Admin</b> además hace conteos y maneja usuarios.' },
      { sel: 'lista-usuarios', titulo: 'Usuarios cargados', texto: 'Con el lápiz cambiás datos, rol o contraseña. Con el tacho lo eliminás (no podés eliminarte a vos mismo).' },
      { sel: 'ayuda', titulo: '¡Listo!', texto: 'Tocá <b>?</b> cuando necesites ayuda.' },
    ],
    inventario: [
      { titulo: 'Conteo de inventario', texto: 'Sirve para que la app coincida con lo que hay de verdad en la granja.' },
      { sel: 'conteo-sin-hacer', titulo: 'Sin hacer', texto: 'Ya vienen cargados los valores actuales. <b>Cambiá solo lo que no coincide</b> con lo que contaste.' },
      { sel: 'conteo-hecho', titulo: 'Hecho', texto: 'Lo mismo para cada color y calibre.' },
      { sel: 'conteo-revisar', titulo: 'Revisar y guardar', texto: 'Ves el total contado y cuántos cambios hay. <b>Revisar</b> te muestra las diferencias antes de guardar.' },
      { sel: 'ayuda', titulo: '¡Listo!', texto: 'Tocá <b>?</b> cuando necesites ayuda.' },
    ],
  };

  const CSS = `
    #tour-capa{position:fixed;inset:0;z-index:70}
    #tour-foco{position:fixed;z-index:70;pointer-events:none;border-radius:16px;box-shadow:0 0 0 2px #34d399,0 0 0 9999px rgba(2,6,23,.78);transition:all .25s ease}
    #tour-tarjeta{position:fixed;z-index:71;width:min(340px,calc(100vw - 24px));background:#0f172a;color:#e2e8f0;border-radius:18px;
      box-shadow:0 0 0 1px #334155,0 20px 40px rgba(0,0,0,.5);padding:16px;font-size:14px;line-height:1.45;transition:top .25s ease,left .25s ease,opacity .2s}
    #tour-tarjeta h3{margin:0 0 6px;font-size:16px;font-weight:800;color:#fff}
    #tour-tarjeta b{color:#fff}#tour-tarjeta .t-verde{color:#34d399}#tour-tarjeta .t-ambar{color:#fbbf24}
    .tour-pie{display:flex;align-items:center;gap:8px;margin-top:14px}
    .tour-cuenta{flex:1;font-size:12px;color:#94a3b8;font-variant-numeric:tabular-nums}
    .tour-pie button{height:40px;padding:0 14px;border-radius:10px;font-weight:700;font-size:14px;border:0;cursor:pointer}
    .tour-sec{background:#1e293b;color:#cbd5e1}.tour-pri{background:#059669;color:#fff}
    .tour-salir{position:absolute;top:8px;right:8px;width:32px;height:32px;border-radius:99px;border:0;background:transparent;color:#94a3b8;font-size:18px;cursor:pointer}
    @media (prefers-reduced-motion:reduce){#tour-foco,#tour-tarjeta{transition:none}}`;

  let pasos = [], actual = -1, capa, foco, tarjeta, elActual = null, modalAbiertoPorTour = false, raf = 0;

  const esperar = ms => new Promise(r => setTimeout(r, ms));
  const visible = el => el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const modalAbierto = () => {
    const b = document.getElementById('modal-operacion-backdrop');
    return b && !b.classList.contains('hidden');
  };

  function crearUI() {
    if (!document.getElementById('tour-css')) {
      const st = document.createElement('style');
      st.id = 'tour-css';
      st.textContent = CSS;
      document.head.appendChild(st);
    }
    capa = document.createElement('div'); capa.id = 'tour-capa';
    foco = document.createElement('div'); foco.id = 'tour-foco';
    tarjeta = document.createElement('div'); tarjeta.id = 'tour-tarjeta';
    tarjeta.setAttribute('role', 'dialog');
    tarjeta.setAttribute('aria-live', 'polite');
    capa.addEventListener('click', e => { e.stopPropagation(); siguiente(); });
    document.body.append(capa, foco, tarjeta);
    addEventListener('resize', reubicarPronto);
    addEventListener('scroll', reubicarPronto, true);
    document.addEventListener('keydown', teclas, true);
  }

  function teclas(e) {
    if (e.key === 'Escape') { e.stopPropagation(); terminar(); }
    else if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); siguiente(); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); anterior(); }
  }

  function reubicarPronto() {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(reubicar);
  }

  // Coloca el recuadro sobre el elemento y la tarjeta arriba o abajo, donde entre
  function reubicar() {
    if (!tarjeta) return;
    const vw = innerWidth, vh = innerHeight, m = 12;
    const th = tarjeta.offsetHeight, tw = tarjeta.offsetWidth;
    if (!elActual) {
      Object.assign(foco.style, { top: vh / 2 + 'px', left: vw / 2 + 'px', width: '0px', height: '0px' });
      tarjeta.style.top = Math.max(m, (vh - th) / 2) + 'px';
      tarjeta.style.left = (vw - tw) / 2 + 'px';
      return;
    }
    const r = elActual.getBoundingClientRect(), pad = 6;
    const top = Math.max(r.top - pad, 4), bottom = Math.min(r.bottom + pad, vh - 4);
    Object.assign(foco.style, {
      top: top + 'px', left: (r.left - pad) + 'px',
      width: (r.width + pad * 2) + 'px', height: Math.max(bottom - top, 0) + 'px',
    });
    let y;
    if (vh - bottom >= th + m * 2) y = bottom + m;
    else if (top >= th + m * 2) y = top - th - m;
    else y = vh - th - m; // el elemento ocupa casi toda la pantalla: tarjeta abajo
    const x = Math.min(Math.max(r.left + r.width / 2 - tw / 2, m), vw - tw - m);
    tarjeta.style.top = y + 'px';
    tarjeta.style.left = x + 'px';
  }

  async function ir(i, dir) {
    if (i < 0) return;
    if (i >= pasos.length) return terminar();
    const paso = pasos[i];

    // Abrir o cerrar el modal de movimientos según lo que pida el paso
    if (paso.modal && !modalAbierto() && window.abrirModalOperacion) {
      abrirModalOperacion('ingreso_galpon');
      modalAbiertoPorTour = true;
      await esperar(330);
    } else if (!paso.modal && modalAbierto() && modalAbiertoPorTour) {
      cerrarModalOperacion();
      modalAbiertoPorTour = false;
      await esperar(300);
    }
    if (!capa) return; // se cerró mientras esperaba

    const el = paso.sel ? document.querySelector(`[data-tour="${paso.sel}"]`) : null;
    if (paso.sel && !visible(el)) return ir(i + dir, dir); // no está en esta pantalla: saltear

    actual = i;
    elActual = el;
    const ultimo = i === pasos.length - 1;
    tarjeta.innerHTML = `
      <button class="tour-salir" aria-label="Salir del tutorial">&times;</button>
      <h3>${paso.titulo}</h3><div>${paso.texto}</div>
      <div class="tour-pie">
        <span class="tour-cuenta">${i + 1} de ${pasos.length}</span>
        ${i > 0 ? '<button class="tour-sec" data-acc="ant">Anterior</button>' : ''}
        <button class="tour-pri" data-acc="sig">${ultimo ? 'Terminar' : 'Siguiente'}</button>
      </div>`;
    tarjeta.querySelector('.tour-salir').onclick = terminar;
    tarjeta.querySelector('[data-acc="sig"]').onclick = siguiente;
    const ant = tarjeta.querySelector('[data-acc="ant"]');
    if (ant) ant.onclick = anterior;

    if (el) {
      const r = el.getBoundingClientRect();
      if (r.top < 70 || r.bottom > innerHeight - 90) {
        el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        await esperar(350);
      }
    }
    reubicar();
    tarjeta.querySelector('[data-acc="sig"]').focus({ preventScroll: true });
  }

  const siguiente = () => ir(actual + 1, 1);
  const anterior = () => ir(actual - 1, -1);

  function terminar() {
    if (!capa) return;
    removeEventListener('resize', reubicarPronto);
    removeEventListener('scroll', reubicarPronto, true);
    document.removeEventListener('keydown', teclas, true);
    capa.remove(); foco.remove(); tarjeta.remove();
    capa = foco = tarjeta = elActual = null;
    if (modalAbiertoPorTour && modalAbierto()) cerrarModalOperacion();
    modalAbiertoPorTour = false;
  }

  window.Tutorial = {
    iniciar() {
      terminar();
      // Solo los pasos que aplican a esta pantalla y a este rol (los del modal se ven recién al abrirlo)
      const hayModal = !!document.getElementById('modal-operacion-sheet');
      pasos = (PASOS[document.body.dataset.pagina] || PASOS.index).filter(p =>
        !p.sel || (p.modal ? hayModal : visible(document.querySelector(`[data-tour="${p.sel}"]`))));
      crearUI();
      ir(0, 1);
    },
  };
})();
