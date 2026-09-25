(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const make = (tag, className = '', text = null) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== null) node.textContent = String(text);
    return node;
  };
  const config = window.BIRDING_CONFIG;
  const state = { all: [], selected: null, cache: new Map(), request: 0, map: null,
    photos: [], photoIndex: 0, lastFocus: null, demo: false };
  const dateLabel = date => date ? new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC'
  }).format(new Date(`${date}T12:00:00Z`)) : 'Sample visit · date not supplied';
  const announce = text => { $('app-status').textContent = text; };
  const publicImage = path => {
    if (typeof path !== 'string' || !path.startsWith('photos/')) return '';
    const url = new URL(path, document.baseURI);
    const base = new URL('photos/', document.baseURI);
    return url.origin === base.origin && url.pathname.startsWith(base.pathname) ? url.href : '';
  };
  async function fetchJSON(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Unable to load ${url} (HTTP ${response.status}).`);
    return response.json();
  }
  const visitPhotos = visits => visits.flatMap(visit => (visit.observations || []).flatMap(observation =>
    (observation.photos || []).map(photo => ({ ...photo, observation, visit }))));
  function setStats() {
    const species = new Set(state.all.flatMap(f => f.properties.speciesIds || []));
    const photos = new Set(state.all.flatMap(f => f.properties.photoPaths || []));
    const entries = [[state.all.length, state.demo ? 'Demo places' : 'Locations'],
      [species.size, state.demo ? 'Verified species' : 'Bird species'],
      [photos.size, state.demo ? 'Sample photo' : 'Photographs']];
    $('stats').replaceChildren(...entries.map(([value, label]) => {
      const cell = make('div'); cell.append(make('strong', '', String(value).padStart(2, '0')), make('span', '', label)); return cell;
    }));
  }
  function emptyState(title, message) {
    const panel = make('div', 'empty-detail'); panel.append(make('p', 'eyebrow', 'The birding notebook'), make('h2', '', title), make('p', '', message)); return panel;
  }
  async function getPlace(feature) {
    const id = feature.properties.id;
    if (!/^[a-z0-9][a-z0-9-]*$/.test(id)) throw new Error('Invalid location identifier.');
    const bundled = window.BIRDING_DATA?.places?.[id];
    if (bundled) return bundled;
    if (!state.cache.has(id)) state.cache.set(id, fetchJSON(`data/places/${id}.json`).catch(error => { state.cache.delete(id); throw error; }));
    return state.cache.get(id);
  }
  async function selectPlace(id, source = 'auto') {
    const feature = state.all.find(f => f.properties.id === id);
    if (!feature) return;
    if ($('lightbox').open && state.selected !== id) $('lightbox').close();
    const request = ++state.request;
    state.selected = id; state.map?.select(id);
    if (source !== 'history') {
      const hash = `#${encodeURIComponent(id)}`;
      if (location.hash !== hash) {
        const method = source === 'auto' ? 'replaceState' : 'pushState';
        try { history[method](null, '', hash); }
        catch (_) { location.hash = hash; }
      }
    }
    $('detail').setAttribute('aria-busy', 'true');
    try {
      const place = await getPlace(feature);
      if (request !== state.request) return;
      renderDetail(place); announce('');
      if (source === 'map') {
        if (matchMedia('(max-width: 760px)').matches) $('detail').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
        $('detail-title').focus({ preventScroll: true });
      }
    } catch (error) {
      if (request !== state.request) return;
      $('detail').replaceChildren(emptyState('This entry could not be opened.', `${error.message} Please try again or open the static catalogue.`));
      announce('The location data could not be loaded. The other entries are still available.');
    } finally { if (request === state.request) $('detail').removeAttribute('aria-busy'); }
  }
  function renderDetail(place) {
    const visits = place.visits; state.photos = visitPhotos(visits);
    const detail = $('detail'); detail.replaceChildren();
    const head = make('div', 'detail-head');
    const top = make('div', 'detail-topline');
    top.append(make('p', 'eyebrow', 'From the field'));
    if (place.demo) top.append(make('span', 'badge', 'EXAMPLE LOCATION'));
    const title = make('h2', '', place.name); title.id = 'detail-title'; title.tabIndex = -1;
    const precision = place.locationPrecision === 'hidden' ? 'Location withheld' : place.locationPrecision === 'exact' ? 'Public location' : 'Approximate public location';
    const meta = make('p', 'location-meta', [place.region, precision].filter(Boolean).join(' · '));
    const chips = make('div', 'habitat-chips');
    for (const habitat of place.habitats || []) chips.append(make('span', 'chip', habitat));
    head.append(top, title, meta, chips);
    if (place.summary) head.append(make('p', 'detail-description', place.summary));
    detail.append(head);
    const tablist = make('div', 'detail-tabs'); tablist.setAttribute('role', 'tablist'); tablist.setAttribute('aria-label', 'Location content');
    const tabs = [];
    for (const [name, label] of [['photos', `Photographs (${state.photos.length})`], ['notes', `Visit notes (${visits.length})`]]) {
      const tab = make('button', '', label); tab.type = 'button'; tab.id = `tab-${name}`;
      tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', `panel-${name}`); tab.setAttribute('aria-selected', String(name === 'photos')); tab.tabIndex = name === 'photos' ? 0 : -1;
      const activate = () => {
        for (const item of tabs) {
          const selected = item === tab;
          item.setAttribute('aria-selected', String(selected)); item.tabIndex = selected ? 0 : -1;
          $(item.getAttribute('aria-controls')).hidden = !selected;
        }
      };
      tab.addEventListener('click', activate);
      tab.addEventListener('keydown', event => {
        if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault(); const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[tabs.length - 1] : tabs.find(x => x !== tab);
        next.click(); next.focus();
      });
      tabs.push(tab); tablist.append(tab);
    }
    detail.append(tablist);
    const gallery = make('section', 'gallery-panel'); gallery.id = 'panel-photos'; gallery.setAttribute('role', 'tabpanel'); gallery.setAttribute('aria-labelledby', 'tab-photos');
    state.photos.forEach((photo, index) => gallery.append(photoCard(photo, index, place)));
    if (!state.photos.length) gallery.append(make('p', 'photo-notes', 'No photographs have been added for these visits yet. The observations are in Visit notes.'));
    const notes = make('section', 'visits-panel'); notes.id = 'panel-notes'; notes.hidden = true; notes.setAttribute('role', 'tabpanel'); notes.setAttribute('aria-labelledby', 'tab-notes');
    for (const visit of visits) {
      const article = make('article', 'visit'); article.append(make('h3', '', dateLabel(visit.date)));
      if (visit.notes) article.append(make('p', '', visit.notes));
      for (const observation of visit.observations || []) {
        const row = make('div', 'observation');
        row.append(make('strong', '', observation.nameEn || observation.nameZh || 'Unidentified bird'));
        if (observation.nameZh && observation.nameEn) row.append(document.createTextNode(` · ${observation.nameZh}`));
        if (observation.scientificName) row.append(make('em', 'species-extra', ` ${observation.scientificName}`));
        if (observation.count !== null && observation.count !== undefined) row.append(document.createTextNode(` · Count: ${observation.count}`));
        if (observation.notes) row.append(make('p', '', observation.notes));
        article.append(row);
      }
      if (visit.checklistUrl && /^https:\/\//.test(visit.checklistUrl)) {
        const a = make('a', '', 'Open checklist ↗'); a.href = visit.checklistUrl; a.target = '_blank'; a.rel = 'noopener noreferrer'; article.append(a);
      }
      notes.append(article);
    }
    if (!visits.length) notes.append(make('p', 'photo-notes', 'No visits have been recorded yet.'));
    detail.append(gallery, notes);
    const footer = make('div', 'detail-footer');
    const share = make('button', '', 'Copy location link ↗'); share.type = 'button'; share.addEventListener('click', copyLink);
    const back = make('a', 'back-to-map', 'Back to map ↑'); back.href = '#map-stage';
    back.addEventListener('click', event => { event.preventDefault(); $('map-stage').scrollIntoView({ behavior: 'smooth', block: 'start' }); });
    footer.append(share, back);
    const privacy = make('span', 'location-meta', place.locationPrecision === 'hidden' ? 'Map pin withheld' : 'Public pin only');
    footer.append(privacy); detail.append(footer);
  }
  function photoCard(photo, index, place) {
    const card = make('figure', 'photo-card'), button = make('button', 'photo-open'); button.type = 'button';
    button.setAttribute('aria-label', `Open photograph: ${photo.caption || photo.observation.nameEn || 'Bird photograph'}`);
    const image = make('img'); image.src = publicImage(photo.thumb || photo.src); image.alt = photo.alt || photo.caption || 'Bird photograph';
    image.loading = 'lazy'; image.decoding = 'async'; image.width = photo.width; image.height = photo.height;
    image.addEventListener('error', () => {
      image.remove(); button.prepend(make('p', 'photo-notes', 'This image is unavailable. Check the photo filename.')); button.disabled = true;
    }, { once: true });
    button.append(image, make('span', 'enlarge', 'View photograph ↗')); button.addEventListener('click', () => openLightbox(index));
    card.append(button);
    const caption = make('figcaption');
    if (place.demo) caption.append(make('p', 'photo-origin', 'Sample image · not assigned to this location'));
    const title = make('div', 'photo-caption-title');
    title.append(make('h3', '', photo.observation.nameEn || photo.observation.nameZh || 'Unidentified bird'));
    if (photo.visit.date) title.append(make('span', '', dateLabel(photo.visit.date)));
    caption.append(title);
    if (photo.observation.nameZh) caption.append(make('p', 'species-extra', photo.observation.nameZh));
    if (photo.observation.scientificName) caption.append(make('em', 'species-extra', photo.observation.scientificName));
    if (!photo.observation.identified) caption.append(make('p', 'species-extra', 'Identification unconfirmed · not counted in the species total'));
    if (photo.caption) caption.append(make('p', 'photo-notes', photo.caption));
    card.append(caption); return card;
  }
  async function copyLink() {
    const url = new URL(location.href); url.hash = state.selected || '';
    try { await navigator.clipboard.writeText(url.href); announce('Location link copied.'); }
    catch { window.prompt('Copy this location link:', url.href); }
  }
  function openLightbox(index) {
    state.photoIndex = index; state.lastFocus = document.activeElement; updateLightbox();
    $('lightbox').showModal(); document.body.classList.add('no-scroll'); $('lightbox-close').focus();
  }
  function updateLightbox() {
    const photo = state.photos[state.photoIndex]; if (!photo) return;
    $('lightbox-title').textContent = photo.observation.nameEn || photo.observation.nameZh || 'Bird photograph';
    $('lightbox-image').src = publicImage(photo.src); $('lightbox-image').alt = photo.alt || photo.caption || 'Bird photograph';
    const metadata = [photo.camera, photo.lens, photo.settings].filter(Boolean).join(' · ');
    const place = state.all.find(f => f.properties.id === state.selected)?.properties;
    $('lightbox-caption').textContent = [photo.caption, metadata, place?.demo ? 'Demonstration only: the photograph is not assigned to this location.' : (photo.visit.date ? dateLabel(photo.visit.date) : '')].filter(Boolean).join('\n');
    $('photo-counter').textContent = `${state.photoIndex + 1} / ${state.photos.length}`;
    const previous = $('photo-prev'), next = $('photo-next');
    const focused = document.activeElement;
    previous.disabled = state.photoIndex === 0;
    next.disabled = state.photoIndex === state.photos.length - 1;
    // Disabling a focused button can move focus out of the dialog in Chromium.
    // Keep focus inside so the arrow keys and Escape continue to work.
    if ($('lightbox').open && (focused === previous || focused === next) && focused.disabled) {
      const target = !previous.disabled ? previous : (!next.disabled ? next : $('lightbox-close'));
      target.focus({ preventScroll: true });
    }
  }
  function nextPhoto(delta) {
    const next = state.photoIndex + delta;
    if (next >= 0 && next < state.photos.length) { state.photoIndex = next; updateLightbox(); }
  }
  function readHash() {
    try { return decodeURIComponent(location.hash.slice(1)); } catch { return ''; }
  }
  function handleHash() {
    const id = readHash();
    if (state.all.some(f => f.properties.id === id)) {
      selectPlace(id, 'history');
    }
  }
  async function init() {
    $('copyright-year').textContent = new Date().getFullYear();
    $('lightbox-close').addEventListener('click', () => $('lightbox').close());
    $('lightbox').addEventListener('close', () => { document.body.classList.remove('no-scroll'); if (state.lastFocus?.isConnected) state.lastFocus.focus({ preventScroll: true }); });
    $('lightbox').addEventListener('click', event => { if (event.target === $('lightbox')) {
      const r = $('lightbox').getBoundingClientRect();
      if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) $('lightbox').close();
    } });
    $('lightbox').addEventListener('keydown', event => {
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); nextPhoto(event.key === 'ArrowLeft' ? -1 : 1); }
    });
    $('photo-prev').addEventListener('click', () => nextPhoto(-1)); $('photo-next').addEventListener('click', () => nextPhoto(1));
    $('lightbox-image').addEventListener('error', () => { $('lightbox-caption').textContent = 'The full-size image could not be loaded. Please check the photo file.'; });
    window.addEventListener('hashchange', handleHash);
    try {
      const data = window.BIRDING_DATA?.index || await fetchJSON('data/locations.geojson');
      if (!Array.isArray(data.features)) throw new Error('Invalid location index.');
      const real = data.features.filter(f => !f.properties.demo);
      state.demo = real.length === 0 && config.showExamplesWhenEmpty;
      state.all = real.length ? real : (state.demo ? data.features : []);
      $('demo-notice').hidden = !state.demo || state.all.length === 0;
      setStats();
      try {
        state.map = new window.BirdingMap(config, selectPlace);
        state.map.init().catch(error => { $('map-status').textContent = 'Overview unavailable; open the photo catalogue for all records.'; console.warn(error.message); });
      } catch (error) { $('map-status').textContent = 'Map unavailable; open the photo catalogue for all records.'; console.warn(error.message); }
      state.map?.setFeatures(state.all);
      const hash = readHash();
      const first = state.all.find(f => f.properties.id === hash) || state.all[0];
      if (first) await selectPlace(first.properties.id, hash === first.properties.id ? 'history' : 'auto');
      else $('detail').replaceChildren(emptyState('The notebook is ready.', 'There are no published birding records yet.'));
    } catch (error) {
      $('detail').replaceChildren(emptyState('The journal could not be loaded.', 'Check data/locations.geojson, or rebuild it with python3 tools/build_birding_data.py.'));
      $('map-status').textContent = 'Location data unavailable'; announce(error.message);
    }
  }
  init();
})();
