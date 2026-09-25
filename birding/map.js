/* A detailed Leaflet map with a dependency-free local overview as its fallback.
 * The same public GeoJSON point data drives both views. No geocoding in the browser.
 */
(() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const svgNode = (tag, attrs = {}) => {
    const node = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    return node;
  };
  const project = (lng, lat) => [lng, -Math.log(Math.tan(Math.PI / 4 + Math.max(-85, Math.min(85, lat)) * Math.PI / 360)) * 180 / Math.PI];
  const unproject = (x, y) => [x, (2 * Math.atan(Math.exp(-y * Math.PI / 180)) - Math.PI / 2) * 180 / Math.PI];
  const boundsBox = ([west, south, east, north]) => {
    const a = project(west, north), b = project(east, south);
    return { x: a[0], y: a[1], w: b[0] - a[0], h: b[1] - a[1] };
  };
  const pathFor = geometry => {
    const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
    return polygons.map(polygon => polygon.map(ring => ring.map((p, i) => {
      const q = project(p[0], p[1]);
      return `${i ? 'L' : 'M'}${q[0].toFixed(5)},${q[1].toFixed(5)}`;
    }).join(' ') + ' Z').join(' ')).join(' ');
  };

  class BirdingMap {
    constructor(config, onSelect) {
      this.config = config;
      this.onSelect = onSelect;
      this.host = document.getElementById('outline-map');
      this.svg = svgNode('svg', { class: 'overview-svg', role: 'group', tabindex: '0',
        'aria-label': 'UK birding map. Scroll or use plus and minus to zoom, drag or use arrow keys to pan. Tab to a location marker and press Enter to open it.' });
      this.host.append(this.svg);
      this.features = [];
      this.selected = null;
      this.labels = [];
      this.cities = [];
      this.street = null;
      this.streetMode = false;
      this.streetLoading = false;
      this.reset(false);
      this.bindControls();
      this.resizeObserver = new ResizeObserver(() => {
        if (!this.view) return;
        const center = [this.view.x + this.view.w / 2, this.view.y + this.view.h / 2];
        this.view.w = this.view.h * this.aspect();
        this.view.x = center[0] - this.view.w / 2;
        this.render();
        if (this.street) this.street.invalidateSize();
      });
      this.resizeObserver.observe(this.host.parentElement);
    }
    width() { return this.host.parentElement.getBoundingClientRect().width || 600; }
    height() { return this.host.parentElement.getBoundingClientRect().height || 516; }
    aspect() { return this.width() / this.height(); }
    fitBox(box, margin = 1.04) {
      const cx = box.x + box.w / 2, cy = box.y + box.h / 2;
      let h = Math.max(box.h, box.w / this.aspect()) * margin;
      const w = h * this.aspect();
      return { x: cx - w / 2, y: cy - h / 2, w, h };
    }
    reset(render = true) {
      this.baseView = this.fitBox(boundsBox(this.config.ukBounds));
      this.view = { ...this.baseView };
      if (render) this.render();
      if (this.streetMode && this.street) {
        const [w, s, e, n] = this.config.ukBounds;
        this.street.fitBounds([[s, w], [n, e]], { padding: [15, 15] });
      }
    }
    async init() {
      let data = window.BIRDING_UK_CONTEXT;
      if (!data) {
        const response = await fetch('assets/uk-context.geojson');
        if (!response.ok) throw new Error('The overview map data could not be loaded.');
        data = await response.json();
      }
      const grid = svgNode('g', { 'aria-hidden': 'true' });
      for (let lng = -12; lng <= 6; lng += 4) {
        const a = project(lng, 47), b = project(lng, 63);
        grid.append(svgNode('path', { d: `M${a} L${b}`, class: 'map-graticule' }));
      }
      for (let lat = 48; lat <= 62; lat += 2) {
        const a = project(-14, lat), b = project(8, lat);
        grid.append(svgNode('path', { d: `M${a} L${b}`, class: 'map-graticule' }));
      }
      this.svg.append(grid);
      const land = svgNode('g', { 'aria-hidden': 'true' });
      for (const feature of data.features) land.append(svgNode('path', {
        d: pathFor(feature.geometry), class: feature.properties.kind === 'water' ? 'map-water' : 'map-land', 'fill-rule': 'evenodd'
      }));
      this.svg.append(land);
      const labelGroup = svgNode('g', { 'aria-hidden': 'true' });
      const labels = [
        [-4.55, 57.25, 'SCOTLAND', false], [-1.9, 52.8, 'ENGLAND', false],
        [-4.0, 52.0, 'WALES', false], [-6.8, 54.95, 'N. IRELAND', false],
        [-8.15, 53.25, 'IRELAND', false], [-0.7, 60.78, 'SHETLAND', false],
        [2.4, 56.0, 'North Sea', true], [-10.8, 57.1, 'Atlantic Ocean', true]
      ];
      for (const [lng, lat, name, sea] of labels) {
        const p = project(lng, lat), text = svgNode('text', { x: p[0], y: p[1], class: sea ? 'sea-label' : 'country-label' });
        text.textContent = name;
        labelGroup.append(text); this.labels.push({ node: text, sea });
      }
      this.svg.append(labelGroup);
      const cityGroup = svgNode('g', { 'aria-hidden': 'true' });
      for (const city of window.BIRDING_CITIES || []) {
        const [x, y] = project(...city.coordinates);
        const group = svgNode('g', { class: 'map-city' });
        const dot = svgNode('circle', { cx: x, cy: y, class: 'city-dot' });
        const label = svgNode('text', { class: 'city-label' });
        label.textContent = city.name;
        group.append(dot, label); cityGroup.append(group);
        this.cities.push({ ...city, x, y, group, dot, label });
      }
      this.svg.append(cityGroup);
      this.pointsLayer = svgNode('g'); this.svg.append(this.pointsLayer);
      this.render();
      this.status('Local overview · scroll to zoom, drag to move');
      if (this.config.defaultMap === 'street' && !this.streetMode && !this.streetLoading) await this.toggleStreet();
    }
    status(message) { document.getElementById('map-status').textContent = message; }
    setFeatures(features) {
      this.features = features.filter(f => f.geometry && f.geometry.type === 'Point');
      this.render(); this.renderStreetPoints();
    }
    select(id, focus = false) {
      this.selected = id;
      this.render(); this.renderStreetPoints();
      const f = this.features.find(x => x.properties.id === id);
      if (focus && f) {
        if (this.streetMode && this.street) {
          const [lng, lat] = f.geometry.coordinates;
          this.street.setView([lat, lng], Math.max(this.street.getZoom(), 9));
        } else {
          const [x, y] = project(...f.geometry.coordinates);
          const h = Math.min(this.view.h, this.baseView.h / 2.5);
          this.view = { x: x - h * this.aspect() / 2, y: y - h / 2, w: h * this.aspect(), h };
          this.render();
        }
      }
    }
    zoom(factor, anchor = null, screenAnchor = [0.5, 0.5]) {
      if (!Number.isFinite(factor) || factor <= 0) return;
      const minHeight = this.baseView.h / 16384;
      const h = Math.max(minHeight, Math.min(this.baseView.h * 1.3, this.view.h / factor));
      const cx = anchor ? anchor[0] : this.view.x + this.view.w / 2;
      const cy = anchor ? anchor[1] : this.view.y + this.view.h / 2;
      this.view = { x: cx - h * this.aspect() * screenAnchor[0], y: cy - h * screenAnchor[1], w: h * this.aspect(), h };
      this.render();
    }
    render() {
      if (!this.view) return;
      const { x, y, w, h } = this.view;
      this.svg.setAttribute('viewBox', `${x} ${y} ${w} ${h}`);
      const scale = this.width() / w;
      for (const label of this.labels) {
        label.node.setAttribute('font-size', (label.sea ? 11 : 8) / scale);
        label.node.style.letterSpacing = `${(label.sea ? 1.4 : 1.1) / scale}px`;
      }
      this.renderPoints();
      this.renderCities(scale);
    }
    renderCities(scale) {
      const zoom = this.baseView.h / this.view.h;
      const occupied = this.pointLabelBoxes || [];
      const intersects = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
      for (const city of this.cities) {
        const px = (city.x - this.view.x) * scale, py = (city.y - this.view.y) * scale;
        city.group.setAttribute('display', 'none');
        if (zoom < (city.minZoom || 1.4) || px < 0 || px > this.width() || py < 0 || py > this.height()) continue;
        const textWidth = city.name.length * 6.5;
        // Try both sides and above/below the dot so nearby birding pins remain readable.
        const positions = [[7, 0], [-textWidth - 7, 0], [7, 32], [7, -32], [-textWidth - 7, 32], [-textWidth - 7, -32]];
        for (const [dx, dy] of positions) {
          const box = { left: px + dx - 3, right: px + dx + textWidth + 3, top: py + dy - 9, bottom: py + dy + 9 };
          if (box.left < 3 || box.right > this.width() - 3 || box.top < 3 || box.bottom > this.height() - 3 || occupied.some(other => intersects(box, other))) continue;
          city.dot.setAttribute('r', 2 / scale);
          city.dot.setAttribute('stroke-width', 1 / scale);
          city.label.setAttribute('x', city.x + dx / scale);
          city.label.setAttribute('y', city.y + dy / scale);
          city.label.setAttribute('font-size', 11 / scale);
          city.label.setAttribute('stroke-width', 3 / scale);
          city.group.removeAttribute('display');
          occupied.push(box);
          break;
        }
      }
    }
    renderPoints() {
      if (!this.pointsLayer) return;
      const focusedId = document.activeElement?.getAttribute('data-map-id');
      this.pointsLayer.replaceChildren();
      const scale = this.width() / this.view.w;
      this.pointLabelBoxes = [];
      const groups = [];
      for (const feature of this.features) {
        const p = project(...feature.geometry.coordinates);
        let group = groups.find(g => Math.hypot(g.x - p[0], g.y - p[1]) * scale < 40);
        if (!group) { group = { x: p[0], y: p[1], items: [] }; groups.push(group); }
        const n = group.items.length;
        group.x = (group.x * n + p[0]) / (n + 1); group.y = (group.y * n + p[1]) / (n + 1);
        group.items.push(feature);
      }
      for (const group of groups) {
        const clustered = group.items.length > 1;
        const f = group.items[0];
        const id = clustered ? `cluster-${f.properties.id}` : f.properties.id;
        const selected = group.items.some(x => x.properties.id === this.selected);
        const g = svgNode('g', { class: `map-point${selected ? ' selected' : ''}`, role: 'button', tabindex: '0',
          transform: `translate(${group.x},${group.y})`, 'data-map-id': id,
          'aria-label': clustered ? `Zoom to ${group.items.length} locations` : `View ${f.properties.name}`,
          'aria-pressed': !clustered && selected ? 'true' : 'false' });
        const title = svgNode('title'); title.textContent = group.items.map(x => x.properties.name).join(' · '); g.append(title);
        const hitWidth = clustered ? 40 : Math.max(65, 42 + (f.properties.mapLabel || f.properties.name).length * 5);
        const px = (group.x - this.view.x) * scale, py = (group.y - this.view.y) * scale;
        this.pointLabelBoxes.push({ left: px - 20, right: px + hitWidth - 20, top: py - 20, bottom: py + 20 });
        g.append(svgNode('rect', { x: -20 / scale, y: -20 / scale, width: hitWidth / scale, height: 40 / scale, fill: 'transparent' }));
        g.append(svgNode('circle', { r: 19 / scale, class: 'pin-shadow' }));
        g.append(svgNode('circle', { r: 12 / scale, class: 'pin-core' }));
        const text = svgNode('text', { class: 'pin-text', 'font-size': 10 / scale, y: 0 });
        text.textContent = clustered ? String(group.items.length) : '•'; g.append(text);
        if (!clustered) {
          const caption = svgNode('text', { x: 19 / scale, y: 0, 'font-size': 9 / scale, class: 'pin-caption', 'stroke-width': 3 / scale });
          caption.style.strokeWidth = `${3 / scale}px`;
          caption.textContent = f.properties.mapLabel || f.properties.name;
          g.append(caption);
        }
        const action = () => {
          if (clustered) this.zoom(2, [group.x, group.y]);
          else this.onSelect(f.properties.id, 'map');
        };
        g.addEventListener('click', event => { event.stopPropagation(); action(); });
        g.addEventListener('keydown', event => {
          if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); action(); }
        });
        this.pointsLayer.append(g);
        if (focusedId === id) g.focus({ preventScroll: true });
      }
    }
    bindControls() {
      document.getElementById('zoom-in').addEventListener('click', () => this.zoom(1.5));
      document.getElementById('zoom-out').addEventListener('click', () => this.zoom(1 / 1.5));
      document.getElementById('reset-view').addEventListener('click', () => this.reset());
      document.getElementById('street-toggle').addEventListener('click', () => this.toggleStreet());
      this.svg.addEventListener('wheel', event => {
        if (!event.deltaY || this.streetMode) return;
        event.preventDefault();
        const rect = this.svg.getBoundingClientRect();
        const matrix = this.svg.getScreenCTM();
        if (!matrix) return;
        const pointer = this.svg.createSVGPoint();
        pointer.x = event.clientX; pointer.y = event.clientY;
        const point = pointer.matrixTransform(matrix.inverse());
        const anchor = [point.x, point.y];
        const screenAnchor = [(point.x - this.view.x) / this.view.w, (point.y - this.view.y) / this.view.h];
        const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? rect.height : 1);
        this.zoom(Math.exp(-Math.max(-300, Math.min(300, delta)) * 0.002), anchor, screenAnchor);
      }, { passive: false });
      let drag = null;
      this.svg.addEventListener('pointerdown', event => {
        if (event.pointerType !== 'mouse' || event.button !== 0 || event.target.closest('.map-point')) return;
        drag = { x: event.clientX, y: event.clientY, view: { ...this.view } };
        this.svg.setPointerCapture(event.pointerId); this.svg.classList.add('dragging');
      });
      this.svg.addEventListener('pointermove', event => {
        if (!drag) return;
        const scale = this.width() / this.view.w;
        this.view.x = drag.view.x - (event.clientX - drag.x) / scale;
        this.view.y = drag.view.y - (event.clientY - drag.y) / scale;
        this.render();
      });
      const stop = () => { drag = null; this.svg.classList.remove('dragging'); };
      this.svg.addEventListener('pointerup', stop); this.svg.addEventListener('pointercancel', stop);
      this.svg.addEventListener('keydown', event => {
        const delta = this.view.h / 10;
        if (event.key === '+' || event.key === '=') this.zoom(1.5);
        else if (event.key === '-') this.zoom(1 / 1.5);
        else if (event.key === 'ArrowLeft') this.view.x -= delta;
        else if (event.key === 'ArrowRight') this.view.x += delta;
        else if (event.key === 'ArrowUp') this.view.y -= delta;
        else if (event.key === 'ArrowDown') this.view.y += delta;
        else return;
        event.preventDefault(); this.render();
      });
    }
    async loadLeaflet() {
      if (window.L && this.leafletStyleReady) return;
      const load = (type, url, integrity) => new Promise((resolve, reject) => {
        const node = document.createElement(type);
        if (type === 'link') { node.rel = 'stylesheet'; node.href = url; }
        else node.src = url;
        // SRI uses CORS, which browsers disallow for local file:// assets.
        if (integrity && location.protocol !== 'file:') { node.integrity = integrity; node.crossOrigin = 'anonymous'; }
        const timeout = setTimeout(() => { node.remove(); reject(new Error('Map library timed out')); }, 12000);
        node.onload = () => { clearTimeout(timeout); resolve(); };
        node.onerror = () => { clearTimeout(timeout); node.remove(); reject(new Error('Map library unavailable')); };
        document.head.append(node);
      });
      await Promise.all([
        this.leafletStyleReady || load('link', this.config.leaflet.css, this.config.leaflet.cssIntegrity).then(() => { this.leafletStyleReady = true; }),
        window.L || load('script', this.config.leaflet.js, this.config.leaflet.jsIntegrity)
      ]);
    }
    async toggleStreet() {
      if (this.streetLoading) return;
      const toggle = document.getElementById('street-toggle');
      if (!this.streetMode) {
        this.streetLoading = true; toggle.disabled = true;
        this.status('Loading the online street map…');
        try {
          await this.loadLeaflet();
          if (!this.street) {
            this.street = window.L.map('street-map', { scrollWheelZoom: true, zoomControl: true, zoomSnap: 0, minZoom: 3, maxZoom: 18 });
            this.streetTiles = window.L.tileLayer(this.config.tileUrl, {
              attribution: this.config.tileAttribution, maxZoom: 18, minZoom: 3
            }).addTo(this.street);
            this.streetPoints = window.L.layerGroup().addTo(this.street);
            this.streetTiles.on('tileload', () => {
              this.streetHasTiles = true;
              clearTimeout(this.tileTimeout);
            });
            this.streetTiles.on('tileerror', () => {
              this.streetTileErrors = true;
              if (this.streetMode) this.status('Some map tiles are unavailable. Overview is available above.');
            });
            this.streetTiles.on('load', () => {
              if (!this.streetMode) return;
              if (!this.streetHasTiles && this.streetTileErrors) this.fallbackToOverview();
              else if (!this.streetTileErrors) this.status('Street map · scroll to zoom, drag to move');
            });
          }
          this.streetMode = true;
        } catch (error) {
          this.status('Street map unavailable. The local overview and photos still work.');
          console.warn(error.message);
          return;
        } finally { this.streetLoading = false; toggle.disabled = false; }
      } else {
        this.copyStreetView();
        this.streetMode = false;
      }
      this.showMapMode();
      if (this.streetMode) {
        const [lng, lat] = unproject(this.view.x + this.view.w / 2, this.view.y + this.view.h / 2);
        this.street.invalidateSize();
        const zoom = Math.max(3, Math.min(18, Math.log2(this.street.getSize().x * 360 / (256 * this.view.w))));
        this.street.setView([lat, lng], zoom, { animate: false });
        this.renderStreetPoints();
        this.status('Street map · scroll to zoom, drag to move');
        if (!this.streetHasTiles) {
          this.streetTileErrors = false;
          this.tileTimeout = setTimeout(() => this.fallbackToOverview(), 12000);
          // A retry after an offline visit must request the failed tiles again.
          if (this.streetRetry) this.streetTiles.redraw();
          this.streetRetry = true;
        }
      } else {
        clearTimeout(this.tileTimeout);
        this.render();
        this.status('Local overview · scroll to zoom, drag to move');
      }
    }
    showMapMode() {
      this.host.hidden = this.streetMode;
      document.getElementById('street-map').hidden = !this.streetMode;
      document.getElementById('outline-controls').hidden = this.streetMode;
      document.getElementById('outline-credit').hidden = this.streetMode;
      document.querySelector('.north').hidden = this.streetMode;
      const toggle = document.getElementById('street-toggle');
      toggle.setAttribute('aria-pressed', String(this.streetMode));
      toggle.textContent = this.streetMode ? 'Overview' : 'Street map ↗';
    }
    copyStreetView() {
      if (!this.street) return;
      const bounds = this.street.getBounds();
      this.view = boundsBox([bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()]);
    }
    fallbackToOverview() {
      clearTimeout(this.tileTimeout);
      if (!this.streetMode || this.streetHasTiles) return;
      this.copyStreetView();
      this.streetMode = false;
      this.showMapMode(); this.render();
      this.status('Street map unavailable. Local overview · scroll to zoom, drag to move');
    }
    renderStreetPoints() {
      if (!this.streetPoints) return;
      this.streetPoints.clearLayers();
      for (const feature of this.features) {
        const p = feature.properties, [lng, lat] = feature.geometry.coordinates;
        const label = document.createElement('span'); label.textContent = p.name;
        const marker = window.L.marker([lat, lng], {
          title: p.name, alt: `View ${p.name}`, keyboard: true,
          icon: window.L.divIcon({ className: `street-pin${p.id === this.selected ? ' selected' : ''}`, html: '•', iconSize: [28, 28], iconAnchor: [14, 14] })
        }).bindTooltip(label).addTo(this.streetPoints);
        marker.on('click', () => this.onSelect(p.id, 'map'));
      }
    }
  }
  window.BirdingMap = BirdingMap;
})();
