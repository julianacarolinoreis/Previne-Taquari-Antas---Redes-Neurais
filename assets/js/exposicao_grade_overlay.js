/* PREVINE · overlay grade exposição v2 (areal) em mapas Leaflet. */
(function (global) {
  'use strict';

  var PLACES = {
    mucum: {
      file: 'grade_exposta_mucum_v2.geojson',
      label: 'Exposição v2 · areal @17,02 m',
      hand: 17.02,
      cidade: 'Muçum'
    },
    santa: {
      file: 'grade_exposta_santa_tereza_v2.geojson',
      label: 'Exposição v2 · areal @15 m',
      hand: 15,
      cidade: 'Santa Tereza'
    }
  };

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (s) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[s];
    });
  }

  function mount(map, layerControl, opts) {
    opts = opts || {};
    var place = PLACES[opts.place];
    if (!map || !layerControl || !place || typeof L === 'undefined') return null;

    var base = opts.basePath || 'assets/data/exposicao_cruzada/';
    var layer = L.geoJSON(null, {
      style: function (feature) {
        var frac = (feature.properties && feature.properties.frac_exposta != null)
          ? Number(feature.properties.frac_exposta)
          : 0.4;
        return {
          color: '#0f766e',
          weight: 1,
          fillColor: '#14b8a6',
          fillOpacity: Math.max(0.12, Math.min(0.55, 0.12 + frac * 0.45))
        };
      },
      onEachFeature: function (feature, lyr) {
        var p = feature.properties || {};
        var frac = p.frac_exposta != null ? Math.round(p.frac_exposta * 100) + '%' : '—';
        lyr.bindTooltip(
          (p.id_grade || 'célula') + ' · ~' + (p.pop != null ? p.pop : '—') + ' pessoas · ' + frac,
          { sticky: true }
        );
        lyr.bindPopup(
          '<div style="font:12px/1.4 system-ui,sans-serif">' +
            '<b>Exposição HAND v2 · areal</b><br>' +
            '<span style="color:#5c6b63">' + esc(place.cidade) + ' · limiar ' + place.hand + ' m</span><br>' +
            'Célula: ' + esc(p.id_grade || '—') + '<br>' +
            'Pop. ~' + (p.pop != null ? p.pop : '—') +
            ' · Dom. ~' + (p.dom != null ? p.dom : '—') + '<br>' +
            'Fração exposta: ' + frac +
            '</div>'
        );
      }
    });

    fetch(base + place.file, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (gj) {
        if (!gj || !gj.features) return;
        layer.addData(gj);
        layerControl.addOverlay(layer, place.label);
        if (opts.autoAdd) layer.addTo(map);
      })
      .catch(function () { /* camada opcional */ });

    return layer;
  }

  global.PREVINE_EXPOSICAO_OVERLAY = {
    PLACES: PLACES,
    mount: mount
  };
})(typeof window !== 'undefined' ? window : globalThis);
