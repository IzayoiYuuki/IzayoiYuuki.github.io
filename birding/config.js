/* Settings only. Location records live in data/places/*.json. */
window.BIRDING_CONFIG = Object.freeze({
  owner: 'Yuqi Liu',
  // Demo entries are shown ONLY while there are no real records.
  showExamplesWhenEmpty: true,
  // Detailed roads and city labels, with the local overview as an offline fallback.
  defaultMap: 'street',
  // [west, south, east, north]. Includes Northern Ireland, Orkney and Shetland.
  ukBounds: [-8.7, 49.8, 2.1, 61.1],
  tileUrl: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  tileAttribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
  leaflet: {
    js: 'assets/leaflet/leaflet.js',
    css: 'assets/leaflet/leaflet.css',
    jsIntegrity: 'sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=',
    cssIntegrity: 'sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY='
  }
});
