/**
 * Kendall - Planetary Multi-Decadal Trend & Era Shift Detector (2000–2025)
 * Mission Control Architecture for Planetary Data Detectives
 * Pair-programmed for NASA Space Apps / Advanced Agentic Coding
 */

(function () {
  'use strict';

  // --- Constants & Grid Configuration ---
  const N_LATS = 72;
  const N_LONS = 144;
  const TOTAL_CELLS = N_LATS * N_LONS; // 10,368
  const TARGET_LATS = [];
  for (let i = 0; i < N_LATS; i++) {
    TARGET_LATS.push(-88.75 + i * 2.5);
  }
  const TARGET_LONS = [];
  for (let j = 0; j < N_LONS; j++) {
    TARGET_LONS.push(-178.75 + j * 2.5);
  }

  const VARIABLES_LIST = [
    { id: 'gpm_precip', name: 'Precipitation', agency: 'GPM IMERG V07', unit: 'mm/mo/dec' },
    { id: 'gldas_precip', name: 'GLDAS Precip', agency: 'GLDAS Noah 2.1', unit: 'mm/mo/dec' },
    { id: 'gldas_soil_moist', name: 'Soil Moisture', agency: 'GLDAS Noah 2.1', unit: 'kg/m²/dec' },
    { id: 'gldas_temp', name: '2m Air Temp', agency: 'GLDAS Noah 2.1', unit: '°C/dec' },
    { id: 'gldas_evap', name: 'Evapotranspiration', agency: 'GLDAS Noah 2.1', unit: 'mm/mo/dec' },
    { id: 'merra2_aod', name: 'Aerosol Optical Depth', agency: 'MERRA-2 550nm', unit: 'AOD/dec' },
    { id: 'gldas_swe', name: 'Snow Water Equiv', agency: 'GLDAS Noah 2.1', unit: 'kg/m²/dec' },
    { id: 'gldas_snow_depth', name: 'Snow Depth', agency: 'GLDAS Noah 2.1', unit: 'm/dec' },
    { id: 'merra2_ts', name: 'Skin Temp (Land+Sea)', agency: 'MERRA-2 M2TMNXSLV', unit: '°C/dec' },
    { id: 'merra2_wind', name: '10m Wind Speed', agency: 'MERRA-2 M2TMNXSLV', unit: 'm/s/dec' },
    { id: 'merra2_ps', name: 'Surface Pressure', agency: 'MERRA-2 M2TMNXSLV', unit: 'hPa/dec' },
    { id: 'merra2_tqv', name: 'Column Water Vapor', agency: 'MERRA-2 M2TMNXSLV', unit: 'kg/m²/dec' },
  ];


  const CLIMATE_EVENTS = {
    20: '2002 El Niño Emergence',
    88: '2007 Strong La Niña Cooling',
    124: '2010 Global Monsoon Surge',
    163: '2014 TRMM ➔ GPM Sensor Break',
    186: '2015–16 Super El Niño Drought',
    246: '2020–22 Triple-Dip La Niña',
    280: '2023–24 Historic Global Marine Heatwave',
  };

  // Global State
  let savedProj = 'globe';
  try {
    const sp = localStorage.getItem('kendall_projection');
    if (sp === 'mercator' || sp === 'globe' || sp === 'flat') {
      savedProj = sp === 'flat' ? 'mercator' : sp;
    }
  } catch (e) {}

  const state = {
    currentVarId: 'gpm_precip',
    currentPin: { lat: -3.75, lon: -61.25 },
    cellIndex: { latIdx: 34, lonIdx: 47 },
    viewMode: 'trend', // 'trend' or 'monthly'
    projection: savedProj, // 'globe' or 'mercator'
    oppositeTwins: false,
    speckleFilter: false,
    isPlaying: false,
    playbackSpeed: 1, // 1x, 2x, 4x
    currentMonthIdx: 0,
    totalMonths: 304,
    cache: {}, // varId -> { meta, trend, anomalies }
    map: null,
    pinMarker: null,
    charts: {
      timeseries: null,
      detectability: null,
    },
    isSpinningIntro: true,
    isFadingGrid: false,
    isMorphing: false,
    hasInitializedProjection: false,
    lineupMode: 'monthly', // 'monthly' or 'trend'
    inspectorData: null,
    chartDates: null,
    chartSeries: null,

    // Step 1-5 Custom Analysis State
    selectionMode: 'point', // 'point' or 'region'
    isDrawingRegion: false,
    drawStartLngLat: null,
    regionBbox: { s: -15, n: 5, w: -75, e: -45 }, // default Amazon Basin
    regionHandles: [],
    startYear: 2000,
    endYear: 2025,
    seasonFilter: 'ALL', // 'ALL', 'DJF', 'MAM', 'JJA', 'SON', 'CUSTOM'
    customMonths: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    analysisChoicesCount: 0,
  };

  // --- Utility: Animated Number Counter ---
  function animateNumber(element, targetVal, decimals = 2, prefix = '') {
    if (!element) return;
    const startVal = parseFloat(element.dataset.currentVal || '0') || 0;
    element.dataset.currentVal = targetVal;
    const obj = { val: startVal };
    gsap.to(obj, {
      val: targetVal,
      duration: 0.6,
      ease: 'power2.out',
      onUpdate: () => {
        const sign = obj.val > 0 && prefix ? prefix : '';
        element.textContent = sign + obj.val.toFixed(decimals);
      },
    });
  }

  // --- Utility: Normalize Angle (-180° to +180°) with Wraparound ---
  function normalizeAngle(deg) {
    let a = deg % 360;
    if (a > 180) a -= 360;
    if (a < -180) a += 360;
    return a;
  }

  // --- Utility: Show On-Screen Error Notice ---
  function showToast(msg) {
    const toast = document.getElementById('error-toast');
    const toastMsg = document.getElementById('toast-msg');
    if (toast && toastMsg) {
      toastMsg.textContent = msg;
      toast.classList.remove('hidden');
    }
  }

  // --- Decompression & Data Fetching ---
  async function fetchGzipJson(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
    if (typeof DecompressionStream !== 'undefined') {
      const ds = new DecompressionStream('gzip');
      const stream = resp.body.pipeThrough(ds);
      const text = await new Response(stream).text();
      return JSON.parse(text);
    } else {
      const buf = await resp.arrayBuffer();
      const text = new TextDecoder().decode(buf);
      return JSON.parse(text);
    }
  }

  async function fetchGzipBinary(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
    if (typeof DecompressionStream !== 'undefined') {
      const ds = new DecompressionStream('gzip');
      const stream = resp.body.pipeThrough(ds);
      const buf = await new Response(stream).arrayBuffer();
      return new Int16Array(buf);
    } else {
      const buf = await resp.arrayBuffer();
      return new Int16Array(buf);
    }
  }

  async function loadVariable(varId) {
    if (state.cache[varId]) return state.cache[varId];
    const basePath = `data/${varId}`;
    try {
      const [meta, trend, anomalies] = await Promise.all([
        fetch(`${basePath}/meta.json`).then((r) => {
          if (!r.ok) throw new Error(`Failed to load ${basePath}/meta.json`);
          return r.json();
        }),
        fetchGzipJson(`${basePath}/trend.json.gz`),
        fetchGzipBinary(`${basePath}/anomalies.bin.gz`),
      ]);
      const dataObj = { meta, trend, anomalies };
      state.cache[varId] = dataObj;
      return dataObj;
    } catch (err) {
      console.error(`Error loading variable ${varId}:`, err);
      showToast(`Data load notice: Failed to load ${varId} (${err.message}).`);
      throw err;
    }
  }

  // --- Colorblind-Safe Diverging Color Interpolation (Cyan to Orange) ---
  // Midpoint is dark neutral #162138; -1 is Cyan #22D3EE; +1 is Orange #FF6B35
  function getDivergingColorRgba(normVal, alpha = 0.85) {
    const t = Math.max(-1, Math.min(1, normVal));
    let r, g, b;
    if (t < 0) {
      // Cyan [-1] -> Neutral [0]
      const u = -t; // 0 (neutral) to 1 (pure cyan)
      r = Math.round(22 + u * (34 - 22));
      g = Math.round(33 + u * (211 - 33));
      b = Math.round(56 + u * (238 - 56));
    } else {
      // Neutral [0] -> Orange [+1]
      const u = t; // 0 (neutral) to 1 (pure orange)
      r = Math.round(22 + u * (255 - 22));
      g = Math.round(33 + u * (107 - 33));
      b = Math.round(56 + u * (53 - 56));
    }
    return [r, g, b, Math.round(alpha * 255)];
  }

  // --- Coordinate Snapping to 2.5° Grid ---
  function snapCoordsToGrid(lat, lon) {
    let latIdx = Math.round((lat - -88.75) / 2.5);
    latIdx = Math.max(0, Math.min(N_LATS - 1, latIdx));

    let normLon = lon;
    while (normLon < -180) normLon += 360;
    while (normLon > 180) normLon -= 360;

    let lonIdx = Math.round((normLon - -178.75) / 2.5);
    lonIdx = Math.max(0, Math.min(N_LONS - 1, lonIdx));

    return {
      latIdx,
      lonIdx,
      snappedLat: TARGET_LATS[latIdx],
      snappedLon: TARGET_LONS[lonIdx],
    };
  }

  // --- Trend Grid Raster Canvas Generator ---
  function renderTrendGridCanvases(varData) {
    const { trend } = varData;
    const slopeScale = trend.slope_scale || 1.0;
    const slopes = trend.slopes;
    const valid = trend.valid;
    const sigFdr = trend.significant_fdr;
    const clusterSig = trend.cluster_significant || sigFdr;
    const useSpeckleFilter = state.speckleFilter;
    const oppositeTwins = state.oppositeTwins;

    // Calculate robust 95th percentile slope max for normalization
    let maxAbsSlope = 0.001;
    for (let i = 0; i < N_LATS; i++) {
      for (let j = 0; j < N_LONS; j++) {
        if (valid[i][j] === 1 && slopes[i][j] !== -32768) {
          const absVal = Math.abs(slopes[i][j] * slopeScale);
          if (absVal > maxAbsSlope) maxAbsSlope = absVal;
        }
      }
    }
    const normMax = maxAbsSlope * 0.75;

    // Create 2 internal canvases for West and East hemispheres (144 x 144 each)
    const wCanvas = document.createElement('canvas');
    wCanvas.width = 144;
    wCanvas.height = 144;
    const wCtx = wCanvas.getContext('2d');

    const eCanvas = document.createElement('canvas');
    eCanvas.width = 144;
    eCanvas.height = 144;
    const eCtx = eCanvas.getContext('2d');

    // Helper: Draw cell on target context
    function drawCell(ctx, cellX, cellY, normVal, isSig, isMasked, isFdrSig, slopeVal) {
      const px = cellX * 2;
      const py = cellY * 2;
      const pw = 2;
      const ph = 2;

      if (isMasked) {
        ctx.fillStyle = 'rgba(15, 23, 42, 0.4)';
        ctx.fillRect(px, py, pw, ph);
        return;
      }

      if (oppositeTwins) {
        // Only show significant cells; mute the rest
        if (!isFdrSig) {
          ctx.fillStyle = 'rgba(15, 23, 42, 0.25)';
          ctx.fillRect(px, py, pw, ph);
          return;
        }
        // Vibrant neon glow for opposite twins
        if (slopeVal < 0) {
          ctx.fillStyle = 'rgba(34, 211, 238, 0.95)'; // Cyan
        } else {
          ctx.fillStyle = 'rgba(255, 107, 53, 0.95)'; // Orange
        }
        ctx.fillRect(px, py, pw, ph);
        return;
      }

      // Standard diverging scale
      const [r, g, b, a] = getDivergingColorRgba(normVal, Math.abs(normVal) > 0.1 ? 0.88 : 0.45);
      ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${a / 255})`;
      ctx.fillRect(px, py, pw, ph);

      // Significance stippling dot
      if (isSig) {
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(px + 0.5, py + 0.5, 1, 1);
      }
    }

    // Loop over rows (i = lat) and cols (j = lon)
    for (let i = 0; i < N_LATS; i++) {
      const latIdx = N_LATS - 1 - i; // Flip so North is top
      for (let j = 0; j < N_LONS; j++) {
        const isValid = valid[latIdx][j] === 1;
        const rawSlope = slopes[latIdx][j];
        const isMasked = !isValid || rawSlope === -32768;
        const slopeVal = isMasked ? 0 : rawSlope * slopeScale;
        const normVal = isMasked ? 0 : Math.max(-1, Math.min(1, slopeVal / normMax));
        const isFdrSig = sigFdr[latIdx][j] === 1;
        const isSig = useSpeckleFilter ? clusterSig[latIdx][j] === 1 : isFdrSig;

        if (j < 72) {
          drawCell(wCtx, j, i, normVal, isSig, isMasked, isFdrSig, slopeVal);
        } else {
          drawCell(eCtx, j - 72, i, normVal, isSig, isMasked, isFdrSig, slopeVal);
        }
      }
    }

    return {
      westDataUrl: wCanvas.toDataURL(),
      eastDataUrl: eCanvas.toDataURL(),
      normMax,
    };
  }

  // --- Monthly Anomaly Filmstrip Canvas Generator ---
  function renderMonthlyGridCanvases(varData, monthIdx) {
    const { meta, anomalies, trend } = varData;
    const valid = trend.valid;
    const comp = meta.compression || {};
    const scale = comp.anom_scale_factor || comp.scale || 0.01;
    const offset = comp.anom_offset || comp.offset || 0.0;

    const wCanvas = document.createElement('canvas');
    wCanvas.width = 144;
    wCanvas.height = 144;
    const wCtx = wCanvas.getContext('2d');

    const eCanvas = document.createElement('canvas');
    eCanvas.width = 144;
    eCanvas.height = 144;
    const eCtx = eCanvas.getContext('2d');

    const m = Math.max(0, Math.min(state.totalMonths - 1, monthIdx));
    const monthOffset = m * (N_LATS * N_LONS);

    for (let i = 0; i < N_LATS; i++) {
      const latIdx = N_LATS - 1 - i;
      const latOffset = latIdx * N_LONS;
      for (let j = 0; j < N_LONS; j++) {
        const isValid = valid[latIdx][j] === 1;
        if (!isValid) {
          const ctx = j < 72 ? wCtx : eCtx;
          const cx = (j < 72 ? j : j - 72) * 2;
          const cy = i * 2;
          ctx.fillStyle = 'rgba(15, 23, 42, 0.4)';
          ctx.fillRect(cx, cy, 2, 2);
          continue;
        }

        const valIdx = monthOffset + latOffset + j;
        const rawInt = anomalies[valIdx];
        if (rawInt === -32768) {
          const ctx = j < 72 ? wCtx : eCtx;
          const cx = (j < 72 ? j : j - 72) * 2;
          const cy = i * 2;
          ctx.fillStyle = 'rgba(15, 23, 42, 0.4)';
          ctx.fillRect(cx, cy, 2, 2);
          continue;
        }

        const val = rawInt * scale + offset;
        const normVal = Math.max(-1, Math.min(1, val / 40.0));
        const [r, g, b, a] = getDivergingColorRgba(normVal, Math.abs(normVal) > 0.05 ? 0.9 : 0.4);

        const ctx = j < 72 ? wCtx : eCtx;
        const cx = (j < 72 ? j : j - 72) * 2;
        const cy = i * 2;
        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${a / 255})`;
        ctx.fillRect(cx, cy, 2, 2);
      }
    }

    return {
      westDataUrl: wCanvas.toDataURL(),
      eastDataUrl: eCanvas.toDataURL(),
    };
  }

  // --- Map Initialization with Globe Projection & CARTO / TopoJSON Fallback ---
  async function initMap() {
    return new Promise((resolve) => {
      let mapLoaded = false;
      const cartoStyleUrl = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

      function buildFallbackStyle(geoData) {
        return {
          version: 8,
          sources: {
            'fallback-countries': {
              type: 'geojson',
              data: geoData,
            },
          },
          layers: [
            {
              id: 'bg-navy',
              type: 'background',
              paint: { 'background-color': '#0B1630' },
            },
            {
              id: 'land-fill',
              type: 'fill',
              source: 'fallback-countries',
              paint: { 'fill-color': '#112240', 'fill-opacity': 0.8 },
            },
            {
              id: 'land-borders',
              type: 'line',
              source: 'fallback-countries',
              paint: { 'line-color': '#22D3EE', 'line-width': 0.8, 'line-opacity': 0.35 },
            },
          ],
        };
      }

      const map = new maplibregl.Map({
        container: 'map',
        clickTolerance: 16,
        style: cartoStyleUrl,
        center: [0, 20],
        zoom: 1.5,
        minZoom: 1,
        maxZoom: 7,
        projection: { type: state.projection },
        touchZoomRotate: true,
        touchPitch: false, // Disables two-finger vertical drag for tilt (prevents touch zoom conflicts)
        dragRotate: true,
        dragPan: {
          linearity: 0.3,
          maxSpeed: 1400,
          deceleration: 2500,
        },
        doubleClickZoom: true,
        scrollZoom: true,
      });

      state.map = map;
      setupMapInteraction(map);

      // Explicitly disable touch pitch (tilt must not trigger on two-finger gestures)
      if (map.touchPitch) {
        map.touchPitch.disable();
      }

      // Explicitly configure touch zoom & rotate with midpoint anchoring
      if (map.touchZoomRotate) {
        map.touchZoomRotate.enable();
        map.touchZoomRotate.enableRotation();
        // Remove rotation threshold deadband so rotation follows fingers immediately (0.00 px drift)
        if (map.touchZoomRotate._touchRotate) {
          map.touchZoomRotate._touchRotate._isBelowThreshold = () => false;
        }
      }
      map.dragRotate.enable();

      // Safari trackpad / iOS gesture listeners (gesturestart / gesturechange / gestureend)
      const mapContainer = document.getElementById('map-container');
      if (mapContainer) {
        let gestureInitialZoom = 0;
        let gestureInitialBearing = 0;
        let gestureCenterLngLat = null;
        let activeTouchCount = 0;

        mapContainer.addEventListener('touchstart', (e) => {
          activeTouchCount = e.touches ? e.touches.length : 0;
        }, { passive: true });
        mapContainer.addEventListener('touchmove', (e) => {
          activeTouchCount = e.touches ? e.touches.length : 0;
        }, { passive: true });
        mapContainer.addEventListener('touchend', (e) => {
          activeTouchCount = e.touches ? e.touches.length : 0;
        }, { passive: true });
        mapContainer.addEventListener('touchcancel', () => {
          activeTouchCount = 0;
        }, { passive: true });

        mapContainer.addEventListener('gesturestart', (e) => {
          e.preventDefault();
          if (state.isMorphing || !state.map) return;
          gestureInitialZoom = map.getZoom();
          gestureInitialBearing = map.getBearing();
          const rect = mapContainer.getBoundingClientRect();
          const px = e.clientX - rect.left;
          const py = e.clientY - rect.top;
          gestureCenterLngLat = map.unproject([px, py]);
        }, { passive: false });

        mapContainer.addEventListener('gesturechange', (e) => {
          e.preventDefault();
          if (state.isMorphing || !state.map) return;

          // If touch events are active on a touchscreen, let MapLibre's built-in touchZoomRotate
          // handle it natively without conflict or double-application
          if (activeTouchCount >= 2) return;

          if (e.scale && e.scale > 0) {
            const targetZoom = Math.max(
              map.getMinZoom(),
              Math.min(map.getMaxZoom(), gestureInitialZoom + Math.log2(e.scale))
            );
            if (gestureCenterLngLat) {
              map.setZoom(targetZoom, { around: gestureCenterLngLat });
            } else {
              map.setZoom(targetZoom);
            }
          }
          if (typeof e.rotation === 'number') {
            // Safari e.rotation is clockwise-positive degrees.
            // MapLibre bearing decreases when rotating clockwise:
            // bearing = startBearing - e.rotation (with wraparound normalization)
            const targetBearing = normalizeAngle(gestureInitialBearing - e.rotation);
            map.setBearing(targetBearing);
          }
        }, { passive: false });

        mapContainer.addEventListener('gestureend', (e) => {
          e.preventDefault();
        }, { passive: false });

        // Two-finger tap zooms out
        let twoFingerTapTime = 0;
        let twoFingerTapPos = null;

        mapContainer.addEventListener('touchstart', (e) => {
          if (e.touches && e.touches.length === 2) {
            twoFingerTapTime = performance.now();
            twoFingerTapPos = {
              x: (e.touches[0].clientX + e.touches[1].clientX) / 2,
              y: (e.touches[0].clientY + e.touches[1].clientY) / 2,
            };
          } else {
            twoFingerTapTime = 0;
          }
        }, { passive: true });

        mapContainer.addEventListener('touchend', (e) => {
          if (twoFingerTapTime && e.touches && e.touches.length === 0) {
            const duration = performance.now() - twoFingerTapTime;
            if (duration < 280 && twoFingerTapPos) {
              const rect = mapContainer.getBoundingClientRect();
              const tapLngLat = map.unproject([
                twoFingerTapPos.x - rect.left,
                twoFingerTapPos.y - rect.top,
              ]);
              map.easeTo({
                zoom: Math.max(map.getMinZoom(), map.getZoom() - 1),
                around: tapLngLat,
                duration: 300,
              });
            }
            twoFingerTapTime = 0;
            twoFingerTapPos = null;
          }
        }, { passive: true });
      }

      // Compass needle tracking
      function updateCompass() {
        const bearing = map.getBearing();
        const pitch = map.getPitch();
        const needle = document.getElementById('compass-needle-svg');
        const btn = document.getElementById('btn-reset-north');
        if (needle) {
          needle.style.transform = `rotate(${-bearing}deg)`;
        }
        if (btn) {
          if (Math.abs(bearing) > 0.5 || Math.abs(pitch) > 0.5) {
            btn.classList.remove('hidden');
          } else {
            btn.classList.add('hidden');
          }
        }
      }

      // 3D Tilt button UI tracking
      function updateTiltUI() {
        const pitch = map.getPitch();
        const btn = document.getElementById('btn-toggle-tilt');
        const label = document.getElementById('tilt-label');
        if (btn && label) {
          if (pitch > 10) {
            btn.classList.add('active');
            label.textContent = '3D';
          } else {
            btn.classList.remove('active');
            label.textContent = '2D';
          }
        }
      }

      map.on('rotate', updateCompass);
      map.on('pitch', () => {
        updateCompass();
        updateTiltUI();
      });
      map.on('move', updateCompass);

      map.on('error', async (e) => {
        if (!mapLoaded && e && e.error && e.error.status >= 400) {
          console.warn('MapLibre CARTO style load issue; triggering offline TopoJSON fallback...');
          try {
            const resp = await fetch('countries-110m.json');
            const topo = await resp.json();
            const geo = topojson.feature(topo, topo.objects.countries);
            map.setStyle(buildFallbackStyle(geo));
            showToast('Live tiles unavailable; displaying offline TopoJSON coastlines.');
          } catch (topoErr) {
            console.error('Failed to load fallback TopoJSON:', topoErr);
          }
        }
      });

      map.on('load', () => {
        mapLoaded = true;
        state.map = map;
        setupMapInteraction(map);

        const dummyCanvas = document.createElement('canvas');
        dummyCanvas.width = 2;
        dummyCanvas.height = 2;
        const dummyData = dummyCanvas.toDataURL();

        // West Hemisphere Source & Layer
        map.addSource('grid-west', {
          type: 'image',
          url: dummyData,
          coordinates: [
            [-180, 85.051129],
            [0, 85.051129],
            [0, -85.051129],
            [-180, -85.051129],
          ],
        });
        map.addLayer({
          id: 'trend-layer-west',
          type: 'raster',
          source: 'grid-west',
          paint: {
            'raster-opacity': 0.88,
            'raster-resampling': 'nearest',
            'raster-fade-duration': 350,
          },
        });

        // East Hemisphere Source & Layer
        map.addSource('grid-east', {
          type: 'image',
          url: dummyData,
          coordinates: [
            [0, 85.051129],
            [180, 85.051129],
            [180, -85.051129],
            [0, -85.051129],
          ],
        });
        map.addLayer({
          id: 'trend-layer-east',
          type: 'raster',
          source: 'grid-east',
          paint: {
            'raster-opacity': 0.88,
            'raster-resampling': 'nearest',
            'raster-fade-duration': 350,
          },
        });

        // Interactive Region Selection GeoJSON Layer (Fill & Outline)
        map.addSource('region-selection', {
          type: 'geojson',
          data: {
            type: 'FeatureCollection',
            features: [],
          },
        });
        map.addLayer({
          id: 'region-fill',
          type: 'fill',
          source: 'region-selection',
          paint: {
            'fill-color': '#22D3EE',
            'fill-opacity': 0.18,
          },
        });
        map.addLayer({
          id: 'region-outline',
          type: 'line',
          source: 'region-selection',
          paint: {
            'line-color': '#22D3EE',
            'line-width': 1.8,
            'line-dasharray': [3, 2],
          },
        });

        // Intro globe slow spin (only runs when in globe view)
        let bearing = 0;
        function spinGlobe() {
          if (state.isSpinningIntro && state.projection === 'globe' && state.map) {
            bearing = (bearing + 0.12) % 360;
            state.map.rotateTo(bearing, { duration: 0 });
            requestAnimationFrame(spinGlobe);
          }
        }
        if (state.projection === 'globe') {
          requestAnimationFrame(spinGlobe);
        }

        resolve(map);
      });
    });
  }

  // --- 3D Pitch / Tilt View Toggle (0° <-> 45°) ---
  function toggleTilt() {
    if (!state.map || state.isMorphing) return;
    const curPitch = state.map.getPitch();
    const targetPitch = curPitch > 10 ? 0 : 45;
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    state.map.easeTo({
      pitch: targetPitch,
      duration: prefersReduced ? 0 : 500,
    });
  }

  // --- Projection Switch Engine with 900ms Morph Animation ---
  function setProjection(type, animate = true) {
    if (!state.map) return;
    if (state.isMorphing) return; // Ignore repeated toggle clicks during active morph

    const normType = (type === 'flat' || type === 'mercator') ? 'mercator' : 'globe';
    const currentNorm = state.projection === 'flat' ? 'mercator' : state.projection;
    if (currentNorm === normType && state.hasInitializedProjection) return;
    state.hasInitializedProjection = true;
    state.projection = normType;

    try {
      localStorage.setItem('kendall_projection', normType);
    } catch (e) {}

    const projGroup = document.getElementById('proj-toggle-group');
    const btnFlat = document.getElementById('btn-proj-flat');
    const btnGlobe = document.getElementById('btn-proj-globe');
    const mapContainer = document.getElementById('map-container');

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const shouldAnimate = animate && !prefersReduced;

    if (projGroup) {
      projGroup.dataset.proj = (normType === 'mercator' ? 'flat' : 'globe');
    }
    if (btnFlat && btnGlobe) {
      btnFlat.classList.toggle('active', normType === 'mercator');
      btnFlat.setAttribute('aria-checked', normType === 'mercator' ? 'true' : 'false');
      btnGlobe.classList.toggle('active', normType === 'globe');
      btnGlobe.setAttribute('aria-checked', normType === 'globe' ? 'true' : 'false');
    }

    if (!shouldAnimate) {
      // Instant switch for reduced motion or initialization
      if (normType === 'mercator') {
        state.isSpinningIntro = false;
        state.map.setBearing(0);
        state.map.setPitch(0);
        state.map.setProjection({ type: 'mercator' });
      } else {
        state.map.setProjection({ type: 'globe' });
      }
      const varData = state.cache[state.currentVarId];
      if (varData) updateGridLayer(varData);
      return;
    }

    // --- 900ms Morph Animation Sequence ---
    state.isMorphing = true;
    if (mapContainer) mapContainer.classList.add('is-morphing');

    const curZoom = state.map.getZoom();
    const fadeObj = { op: 0.88 };

    if (normType === 'globe') {
      // Sequence: Flat -> Globe (~900ms)
      // Phase 1 (0 to 280ms): Ease zoom out slightly, dip grid opacity
      state.map.easeTo({
        zoom: Math.max(state.map.getMinZoom(), curZoom - 0.4),
        duration: 280,
        easing: (t) => t * (2 - t),
      });

      gsap.to(fadeObj, {
        op: 0.35,
        duration: 0.24,
        ease: 'power1.in',
        onUpdate: () => {
          if (state.map.getLayer('trend-layer-west')) {
            state.map.setPaintProperty('trend-layer-west', 'raster-opacity', fadeObj.op);
            state.map.setPaintProperty('trend-layer-east', 'raster-opacity', fadeObj.op);
          }
        },
      });

      // Phase 2 (at 280ms): Morph geometry into sphere, update grid raster
      setTimeout(() => {
        state.map.setProjection({ type: 'globe' });
        const varData = state.cache[state.currentVarId];
        if (varData) updateGridLayer(varData);

        // Phase 3 (280ms to 900ms): Settle camera smoothly back to original zoom, restore grid opacity
        state.map.easeTo({
          zoom: curZoom,
          duration: 620,
          easing: (t) => 1 - Math.pow(1 - t, 3),
        });

        gsap.to(fadeObj, {
          op: 0.88,
          duration: 0.55,
          ease: 'power2.out',
          onUpdate: () => {
            if (state.map.getLayer('trend-layer-west')) {
              state.map.setPaintProperty('trend-layer-west', 'raster-opacity', fadeObj.op);
              state.map.setPaintProperty('trend-layer-east', 'raster-opacity', fadeObj.op);
            }
          },
        });
      }, 280);

      // Phase 4 (at 900ms): Morph complete, unlock pointer events
      setTimeout(() => {
        state.isMorphing = false;
        if (mapContainer) mapContainer.classList.remove('is-morphing');
      }, 900);

    } else {
      // Sequence: Globe -> Flat (~900ms)
      state.isSpinningIntro = false;

      // Phase 1 (0 to 280ms): Ease bearing and pitch to 0, pull camera back slightly, dip grid opacity
      state.map.easeTo({
        zoom: Math.max(state.map.getMinZoom(), curZoom - 0.35),
        bearing: 0,
        pitch: 0,
        duration: 280,
        easing: (t) => t * (2 - t),
      });

      gsap.to(fadeObj, {
        op: 0.35,
        duration: 0.24,
        ease: 'power1.in',
        onUpdate: () => {
          if (state.map.getLayer('trend-layer-west')) {
            state.map.setPaintProperty('trend-layer-west', 'raster-opacity', fadeObj.op);
            state.map.setPaintProperty('trend-layer-east', 'raster-opacity', fadeObj.op);
          }
        },
      });

      // Phase 2 (at 280ms): Switch projection to flat mercator plane, re-align raster layers
      setTimeout(() => {
        state.map.setProjection({ type: 'mercator' });
        const varData = state.cache[state.currentVarId];
        if (varData) updateGridLayer(varData);

        // Phase 3 (280ms to 900ms): Settle camera to target level zoom at flat plane
        state.map.easeTo({
          zoom: curZoom,
          bearing: 0,
          pitch: 0,
          duration: 620,
          easing: (t) => 1 - Math.pow(1 - t, 3),
        });

        gsap.to(fadeObj, {
          op: 0.88,
          duration: 0.55,
          ease: 'power2.out',
          onUpdate: () => {
            if (state.map.getLayer('trend-layer-west')) {
              state.map.setPaintProperty('trend-layer-west', 'raster-opacity', fadeObj.op);
              state.map.setPaintProperty('trend-layer-east', 'raster-opacity', fadeObj.op);
            }
          },
        });
      }, 280);

      // Phase 4 (at 900ms): Morph complete, unlock pointer events
      setTimeout(() => {
        state.isMorphing = false;
        if (mapContainer) mapContainer.classList.remove('is-morphing');
      }, 900);
    }
  }

  // --- Dynamic Grid Update with 400ms Smooth Cross-Fade ---
  function updateGridLayer(varData) {
    if (!state.map) return;
    const { westDataUrl, eastDataUrl, normMax } =
      state.viewMode === 'trend'
        ? renderTrendGridCanvases(varData)
        : renderMonthlyGridCanvases(varData, state.currentMonthIdx);

    const wSource = state.map.getSource('grid-west');
    const eSource = state.map.getSource('grid-east');

    if (wSource && eSource) {
      if (state.viewMode === 'trend' && !state.isFadingGrid) {
        state.isFadingGrid = true;
        // 400ms Cross-Fade: Dip opacity -> update image -> ease back in
        const fadeObj = { op: 0.88 };
        gsap.to(fadeObj, {
          op: 0.2,
          duration: 0.18,
          ease: 'power1.in',
          onUpdate: () => {
            if (state.map.getLayer('trend-layer-west')) {
              state.map.setPaintProperty('trend-layer-west', 'raster-opacity', fadeObj.op);
              state.map.setPaintProperty('trend-layer-east', 'raster-opacity', fadeObj.op);
            }
          },
          onComplete: () => {
            wSource.updateImage({ url: westDataUrl });
            eSource.updateImage({ url: eastDataUrl });
            gsap.to(fadeObj, {
              op: 0.88,
              duration: 0.22,
              ease: 'power1.out',
              onUpdate: () => {
                if (state.map.getLayer('trend-layer-west')) {
                  state.map.setPaintProperty('trend-layer-west', 'raster-opacity', fadeObj.op);
                  state.map.setPaintProperty('trend-layer-east', 'raster-opacity', fadeObj.op);
                }
              },
              onComplete: () => {
                state.isFadingGrid = false;
              },
            });
          },
        });
      } else {
        wSource.updateImage({ url: westDataUrl });
        eSource.updateImage({ url: eastDataUrl });
      }
    }

    // Animate Legend min/max
    if (state.viewMode === 'trend' && normMax) {
      const legMin = document.getElementById('legend-min');
      const legMax = document.getElementById('legend-max');
      const legUnit = document.getElementById('legend-unit');
      if (legMin && legMax) {
        animateNumber(legMin, -normMax, 2, '-');
        animateNumber(legMax, normMax, 2, '+');
      }
      if (legUnit && varData.meta) {
        legUnit.textContent = varData.meta.trend_units || 'units/decade';
      }
    }
  }

  // --- Animated HTML Pin Marker with Ripple Effect ---
  function dropPinMarker(lat, lon) {
    if (!state.map) return;
    if (state.pinMarker) {
      state.pinMarker.remove();
    }

    const el = document.createElement('div');
    el.className = 'custom-pin-marker';
    el.innerHTML = `
      <div class="pin-ripple-ring"></div>
      <div class="pin-ripple-ring"></div>
      <div class="pin-core-dot"></div>
    `;

    state.pinMarker = new maplibregl.Marker({ element: el })
      .setLngLat([lon, lat])
      .addTo(state.map);
  }

  // --- Region Drawing, Handles & Layer Synchronizer ---
  function clearRegionHandles() {
    if (state.regionHandles && state.regionHandles.length > 0) {
      state.regionHandles.forEach((h) => h.marker.remove());
      state.regionHandles = [];
    }
  }

  function updateRegionGeoJson() {
    if (!state.map) return;
    const src = state.map.getSource('region-selection');
    if (!src) return;

    if (state.selectionMode !== 'region' || !state.regionBbox) {
      src.setData({ type: 'FeatureCollection', features: [] });
      clearRegionHandles();
      return;
    }

    const { s, n, w, e } = state.regionBbox;
    const coords = [
      [
        [w, s],
        [e, s],
        [e, n],
        [w, n],
        [w, s],
      ],
    ];

    src.setData({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: coords,
          },
        },
      ],
    });

    updateRegionHandles();
  }

  function updateRegionHandles() {
    if (!state.map || state.selectionMode !== 'region' || !state.regionBbox) {
      clearRegionHandles();
      return;
    }

    const { s, n, w, e } = state.regionBbox;
    const midLat = (s + n) / 2;
    const midLon = (w + e) / 2;

    const handlePositions = [
      { id: 'nw', lngLat: [w, n] },
      { id: 'n', lngLat: [midLon, n] },
      { id: 'ne', lngLat: [e, n] },
      { id: 'e', lngLat: [e, midLat] },
      { id: 'se', lngLat: [e, s] },
      { id: 's', lngLat: [midLon, s] },
      { id: 'sw', lngLat: [w, s] },
      { id: 'w', lngLat: [w, midLat] },
    ];

    if (state.regionHandles.length === 8) {
      state.regionHandles.forEach((h, idx) => {
        h.marker.setLngLat(handlePositions[idx].lngLat);
      });
      return;
    }

    clearRegionHandles();

    handlePositions.forEach((hp) => {
      const el = document.createElement('div');
      el.className = 'region-handle-marker';
      el.dataset.handle = hp.id;

      let isDraggingHandle = false;

      el.addEventListener('mousedown', (ev) => {
        ev.stopPropagation();
        isDraggingHandle = true;
        if (state.map) state.map.dragPan.disable();

        function onMouseMove(moveEv) {
          if (!isDraggingHandle || !state.map) return;
          const mapContainer = document.getElementById('map-container');
          const rect = mapContainer.getBoundingClientRect();
          const unproj = state.map.unproject([moveEv.clientX - rect.left, moveEv.clientY - rect.top]);
          const curLng = Math.max(-180, Math.min(180, unproj.lng));
          const curLat = Math.max(-60, Math.min(60, unproj.lat));

          let { s, n, w, e } = state.regionBbox;
          if (hp.id === 'n') n = curLat;
          else if (hp.id === 's') s = curLat;
          else if (hp.id === 'e') e = curLng;
          else if (hp.id === 'w') w = curLng;
          else if (hp.id === 'nw') { n = curLat; w = curLng; }
          else if (hp.id === 'ne') { n = curLat; e = curLng; }
          else if (hp.id === 'se') { s = curLat; e = curLng; }
          else if (hp.id === 'sw') { s = curLat; w = curLng; }

          state.regionBbox = {
            s: Math.min(s, n),
            n: Math.max(s, n),
            w: Math.min(w, e),
            e: Math.max(w, e),
          };
          updateRegionGeoJson();
          syncBboxInputs();
        }

        function onMouseUp() {
          if (isDraggingHandle) {
            isDraggingHandle = false;
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', onMouseUp);
            if (state.map) state.map.dragPan.enable();
            recordAnalysisChoice();
            updateInspector();
          }
        }

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
      });

      const marker = new maplibregl.Marker({ element: el, draggable: false })
        .setLngLat(hp.lngLat)
        .addTo(state.map);

      state.regionHandles.push({ id: hp.id, marker });
    });
  }

  function syncBboxInputs() {
    const { s, n, w, e } = state.regionBbox;
    const inpS = document.getElementById('bbox-s');
    const inpN = document.getElementById('bbox-n');
    const inpW = document.getElementById('bbox-w');
    const inpE = document.getElementById('bbox-e');
    if (inpS) inpS.value = s.toFixed(1);
    if (inpN) inpN.value = n.toFixed(1);
    if (inpW) inpW.value = w.toFixed(1);
    if (inpE) inpE.value = e.toFixed(1);
  }

  function setSelectionMode(mode) {
    state.selectionMode = mode;

    const group = document.getElementById('selection-mode-group');
    const btnPoint = document.getElementById('btn-mode-point');
    const btnRegion = document.getElementById('btn-mode-region');
    const regionCard = document.getElementById('region-info-card');

    if (group) group.dataset.mode = mode;
    if (btnPoint) {
      btnPoint.classList.toggle('active', mode === 'point');
      btnPoint.setAttribute('aria-checked', mode === 'point' ? 'true' : 'false');
    }
    if (btnRegion) {
      btnRegion.classList.toggle('active', mode === 'region');
      btnRegion.setAttribute('aria-checked', mode === 'region' ? 'true' : 'false');
    }

    if (mode === 'point') {
      if (regionCard) regionCard.classList.add('hidden');
      if (state.isDrawingRegion) toggleDrawRegion(false);
      updateRegionGeoJson();
      dropPinMarker(state.currentPin.lat, state.currentPin.lon);
    } else {
      if (regionCard) regionCard.classList.remove('hidden');
      if (state.pinMarker) {
        state.pinMarker.remove();
        state.pinMarker = null;
      }
      syncBboxInputs();
      updateRegionGeoJson();
    }

    recordAnalysisChoice();
    updateInspector();
  }

  function toggleDrawRegion(forceState) {
    const shouldDraw = forceState !== undefined ? forceState : !state.isDrawingRegion;
    state.isDrawingRegion = shouldDraw;
    state.isSpinningIntro = false;

    const banner = document.getElementById('draw-mode-banner');
    const btnDraw = document.getElementById('btn-draw-region');
    const mapContainer = document.getElementById('map-container');

    if (banner) banner.classList.toggle('hidden', !shouldDraw);
    if (btnDraw) btnDraw.classList.toggle('active', shouldDraw);
    if (mapContainer) mapContainer.classList.toggle('draw-mode', shouldDraw);

    if (shouldDraw) {
      if (state.selectionMode !== 'region') {
        setSelectionMode('region');
      }
      if (state.map) {
        if (state.map.dragPan) state.map.dragPan.disable();
        if (state.map.touchZoomRotate) state.map.touchZoomRotate.disable();
        if (state.map.boxZoom) state.map.boxZoom.disable();
        if (state.map.doubleClickZoom) state.map.doubleClickZoom.disable();
      }
    } else {
      state.drawStartLngLat = null;
      if (state.map) {
        if (state.map.dragPan) state.map.dragPan.enable();
        if (state.map.touchZoomRotate) state.map.touchZoomRotate.enable();
        if (state.map.boxZoom) state.map.boxZoom.enable();
        if (state.map.doubleClickZoom) state.map.doubleClickZoom.enable();
      }
    }
  }

  const REGION_PRESETS = {
    world: { name: 'Whole World (60°S to 60°N)', s: -60, n: 60, w: -180, e: 180 },
    visible: null,
    amazon: { name: 'Amazon Basin, South America', s: -15, n: 5, w: -75, e: -45 },
    sahel: { name: 'African Sahel Corridor', s: 10, n: 20, w: -18, e: 35 },
    canada: { name: 'Central Canada Boreal (Wildfire)', s: 50, n: 62, w: -125, e: -95 },
    great_plains: { name: 'North American Great Plains', s: 30, n: 48, w: -105, e: -90 },
    wisconsin: { name: 'Wisconsin Area (Upper Midwest)', s: 42, n: 47, w: -93, e: -87 },
    sahara: { name: 'Sahara Desert', s: 18, n: 30, w: -12, e: 30 },
    india: { name: 'Indian Subcontinent', s: 8, n: 35, w: 68, e: 90 },
    europe: { name: 'Western & Central Europe', s: 36, n: 60, w: -10, e: 30 },
    pacific: { name: 'Tropical Pacific (ENSO Zone)', s: -10, n: 10, w: 160, e: -90 },
    arctic: { name: 'Arctic Ocean (Above 60°N - Masked)', s: 65, n: 85, w: -180, e: 180 },
  };

  function applyPreset(presetKey) {
    let bbox;
    if (presetKey === 'visible') {
      if (!state.map) return;
      const b = state.map.getBounds();
      bbox = {
        s: Math.max(-60, Math.min(60, b.getSouth())),
        n: Math.max(-60, Math.min(60, b.getNorth())),
        w: Math.max(-180, Math.min(180, b.getWest())),
        e: Math.max(-180, Math.min(180, b.getEast())),
      };
    } else if (REGION_PRESETS[presetKey]) {
      bbox = { ...REGION_PRESETS[presetKey] };
    }
    if (!bbox) return;

    state.regionBbox = bbox;
    syncBboxInputs();

    if (state.selectionMode !== 'region') {
      setSelectionMode('region');
    } else {
      updateRegionGeoJson();
      recordAnalysisChoice();
      updateInspector();
    }

    if (presetKey !== 'visible' && presetKey !== 'world' && state.map) {
      const centerLon = (bbox.w + bbox.e) / 2;
      const centerLat = (bbox.s + bbox.n) / 2;
      state.map.easeTo({
        center: [centerLon, centerLat],
        zoom: 3.0,
        duration: 800,
      });
    }
  }

  // --- Statistical Functions Verified Against Python pymannkendall ---
  function normCdf(x) {
    const a1 = 0.254829592;
    const a2 = -0.284496736;
    const a3 = 1.421413741;
    const a4 = -1.453152027;
    const a5 = 1.061405429;
    const p = 0.3275911;

    const sign = x < 0 ? -1 : 1;
    const absX = Math.abs(x) / Math.SQRT2;

    const t = 1.0 / (1.0 + p * absX);
    const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-absX * absX);

    return 0.5 * (1.0 + sign * y);
  }

  function rankdata(arr) {
    const n = arr.length;
    const indexed = new Array(n);
    for (let i = 0; i < n; i++) {
      indexed[i] = { val: arr[i], idx: i };
    }
    indexed.sort((a, b) => a.val - b.val);

    const ranks = new Float64Array(n);
    let i = 0;
    while (i < n) {
      let j = i;
      while (j < n - 1 && indexed[j + 1].val === indexed[j].val) {
        j++;
      }
      const avgRank = (i + 1 + j + 1) / 2.0;
      for (let k = i; k <= j; k++) {
        ranks[indexed[k].idx] = avgRank;
      }
      i = j + 1;
    }
    return ranks;
  }

  function computeSensSlope(x) {
    const n = x.length;
    const slopes = [];
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        slopes.push((x[j] - x[i]) / (j - i));
      }
    }
    slopes.sort((a, b) => a - b);
    const mid = Math.floor(slopes.length / 2);
    return slopes.length % 2 !== 0 ? slopes[mid] : (slopes[mid - 1] + slopes[mid]) / 2.0;
  }

  function computeMannKendall(x, alpha = 0.05) {
    const n = x.length;
    if (n < 4) {
      return { slope: 0, p: 1.0, z: 0, s: 0, var_s: 1.0, trend: 'no trend' };
    }

    let s = 0;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const diff = x[j] - x[i];
        if (diff > 0) s += 1;
        else if (diff < 0) s -= 1;
      }
    }

    const counts = {};
    for (let i = 0; i < n; i++) {
      counts[x[i]] = (counts[x[i]] || 0) + 1;
    }

    let tieTerm = 0;
    for (const val in counts) {
      const tp = counts[val];
      if (tp > 1) {
        tieTerm += tp * (tp - 1) * (2 * tp + 5);
      }
    }

    const var_s = (n * (n - 1) * (2 * n + 5) - tieTerm) / 18.0;

    let z = 0;
    if (s > 0) {
      z = (s - 1) / Math.sqrt(var_s);
    } else if (s < 0) {
      z = (s + 1) / Math.sqrt(var_s);
    }

    const p = 2.0 * (1.0 - normCdf(Math.abs(z)));
    const slope = computeSensSlope(x);

    return {
      slope,
      p: Math.min(1.0, Math.max(0.0, p)),
      z,
      s,
      var_s,
      trend: z > 0 && p < alpha ? 'increasing' : z < 0 && p < alpha ? 'decreasing' : 'no trend',
    };
  }

  function computeHamedRao(x, alpha = 0.05) {
    const n = x.length;
    if (n < 4) {
      return computeMannKendall(x, alpha);
    }

    const base = computeMannKendall(x, alpha);
    const s = base.s;
    const base_var_s = base.var_s;
    const slope = base.slope;

    const x_detrend = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      x_detrend[i] = x[i] - (i + 1) * slope;
    }

    const ranks = rankdata(x_detrend);

    let sumR = 0;
    for (let i = 0; i < n; i++) sumR += ranks[i];
    const meanR = sumR / n;

    const y = new Float64Array(n);
    for (let i = 0; i < n; i++) y[i] = ranks[i] - meanR;

    let varY = 0;
    for (let i = 0; i < n; i++) varY += y[i] * y[i];

    if (varY === 0) {
      return base;
    }

    const z_crit = 1.959963984540054;
    const bound = z_crit / Math.sqrt(n);

    let sni = 0;
    for (let lag = 1; lag < n; lag++) {
      let cov = 0;
      for (let t = 0; t < n - lag; t++) {
        cov += y[t] * y[t + lag];
      }
      const r_lag = cov / varY;

      if (Math.abs(r_lag) > bound) {
        sni += (n - lag) * (n - lag - 1) * (n - lag - 2) * r_lag;
      }
    }

    const n_ns = 1.0 + (2.0 / (n * (n - 1) * (n - 2))) * sni;
    const var_s_mod = base_var_s * n_ns;

    let z_mod = 0;
    if (var_s_mod > 0) {
      if (s > 0) z_mod = (s - 1) / Math.sqrt(var_s_mod);
      else if (s < 0) z_mod = (s + 1) / Math.sqrt(var_s_mod);
    } else {
      z_mod = base.z;
    }

    const p_mod = 2.0 * (1.0 - normCdf(Math.abs(z_mod)));

    return {
      slope,
      p: Math.min(1.0, Math.max(0.0, p_mod)),
      p_plain: base.p,
      z: z_mod,
      s,
      var_s: var_s_mod,
      n_ns,
      trend: z_mod > 0 && p_mod < alpha ? 'increasing' : z_mod < 0 && p_mod < alpha ? 'decreasing' : 'no trend',
    };
  }

  function computeFullStats(values, timePoints, slopeMultiplier = 120.0) {
    const n = values.length;
    if (n < 4) {
      return {
        slopeDecade: 0,
        p_hr: 1.0,
        p_plain: 1.0,
        ci_lower: 0,
        ci_upper: 0,
        mean: 0,
        std: 1.0,
        isSig: false,
        isTrending: false,
      };
    }

    const slopes = [];
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        slopes.push((values[j] - values[i]) / (timePoints[j] - timePoints[i]));
      }
    }
    slopes.sort((a, b) => a - b);
    const mid = Math.floor(slopes.length / 2);
    const medianSlope = slopes.length % 2 !== 0 ? slopes[mid] : (slopes[mid - 1] + slopes[mid]) / 2.0;
    const slopeDecade = medianSlope * slopeMultiplier;

    const hr = computeHamedRao(values, 0.05);
    const p_hr = hr.p;
    const p_plain = hr.p_plain !== undefined ? hr.p_plain : hr.p;

    const z_alpha = 1.959963984540054;
    const c_alpha = z_alpha * Math.sqrt(hr.var_s || (n * (n - 1) * (2 * n + 5)) / 18.0);
    const m1 = Math.floor((slopes.length - c_alpha) / 2);
    const m2 = Math.floor((slopes.length + c_alpha) / 2);
    const ci_lower = (slopes[Math.max(0, m1)] || slopes[0]) * slopeMultiplier;
    const ci_upper = (slopes[Math.min(slopes.length - 1, m2)] || slopes[slopes.length - 1]) * slopeMultiplier;

    let sum = 0;
    for (let i = 0; i < n; i++) sum += values[i];
    const mean = sum / n;

    let sumSq = 0;
    for (let i = 0; i < n; i++) sumSq += (values[i] - mean) * (values[i] - mean);
    const std = n > 1 ? Math.sqrt(sumSq / (n - 1)) : 1.0;

    const isSig = p_hr < 0.05;
    const isTrending = !isSig && (p_hr < 0.1 || p_plain < 0.05);

    return {
      slopeDecade,
      p_hr,
      p_plain,
      ci_lower,
      ci_upper,
      mean,
      std,
      isSig,
      isTrending,
    };
  }

  // --- Area-Weighted Regional Series Computation ---
  function computeRegionalTimeSeries(varId, bbox) {
    const varData = state.cache[varId];
    if (!varData) return null;

    const { meta, trend, anomalies } = varData;
    const comp = meta.compression || {};
    const scale = comp.anom_scale_factor || comp.scale || 0.01;
    const offset = comp.anom_offset || comp.offset || 0.0;
    const nCells = N_LATS * N_LONS;

    const { s, n, w, e } = bbox;
    const minLat = Math.min(s, n);
    const maxLat = Math.max(s, n);

    const selectedCells = [];
    let totalCellsInBbox = 0;
    let totalAreaKm2 = 0;

    for (let i = 0; i < N_LATS; i++) {
      const lat = TARGET_LATS[i];
      if (lat < minLat - 1.25 || lat > maxLat + 1.25) continue;

      const cosLat = Math.cos((lat * Math.PI) / 180);
      const cellAreaKm2 = 77196.5 * cosLat;

      for (let j = 0; j < N_LONS; j++) {
        const lon = TARGET_LONS[j];
        let insideLon = false;
        if (w <= e) {
          insideLon = lon >= w - 1.25 && lon <= e + 1.25;
        } else {
          insideLon = lon >= w - 1.25 || lon <= e + 1.25;
        }

        if (insideLon) {
          totalCellsInBbox++;
          const isValid = trend.valid[i][j] === 1;
          if (isValid) {
            totalAreaKm2 += cellAreaKm2;
            selectedCells.push({
              latIdx: i,
              lonIdx: j,
              flatIdx: i * N_LONS + j,
              weight: cosLat,
            });
          }
        }
      }
    }

    const validCount = selectedCells.length;
    if (validCount === 0) {
      return {
        series: new Array(state.totalMonths).fill(null),
        validCount: 0,
        totalCount: totalCellsInBbox,
        areaKm2: 0,
        isMasked: true,
      };
    }

    let sumWeight = 0;
    for (let k = 0; k < validCount; k++) {
      sumWeight += selectedCells[k].weight;
    }

    const regionalSeries = [];
    for (let m = 0; m < state.totalMonths; m++) {
      const monthOffset = m * nCells;
      let weightedSum = 0;
      let monthWeight = 0;

      for (let k = 0; k < validCount; k++) {
        const cell = selectedCells[k];
        const rawInt = anomalies[monthOffset + cell.flatIdx];
        if (rawInt !== -32768) {
          const val = rawInt * scale + offset;
          weightedSum += val * cell.weight;
          monthWeight += cell.weight;
        }
      }

      if (monthWeight > 0) {
        regionalSeries.push(weightedSum / monthWeight);
      } else {
        regionalSeries.push(null);
      }
    }

    return {
      series: regionalSeries,
      validCount,
      totalCount: totalCellsInBbox,
      areaKm2: totalAreaKm2,
      isMasked: false,
    };
  }

  // --- Extract Time Period & Seasonal Series for Analysis ---
  function extractAnalysisSeries(fullMonthlySeries, startYear, endYear, seasonFilter, customMonths) {
    const baseYear = 2000;
    const baseMonth = 6;
    const dates = [];
    const values = [];
    const timePoints = [];

    const isSeasonal = seasonFilter !== 'ALL';

    if (!isSeasonal) {
      let tIdx = 0;
      for (let m = 0; m < fullMonthlySeries.length; m++) {
        const ymYear = baseYear + Math.floor((baseMonth - 1 + m) / 12);
        const ymM = ((baseMonth - 1 + m) % 12) + 1;
        if (ymYear >= startYear && ymYear <= endYear) {
          const val = fullMonthlySeries[m];
          if (val !== null && !isNaN(val) && isFinite(val)) {
            dates.push(`${ymYear}-${String(ymM).padStart(2, '0')}`);
            values.push(val);
            timePoints.push(tIdx);
          }
          tIdx++;
        }
      }
      return {
        dates,
        values,
        timePoints,
        isAnnual: false,
        slopeMultiplier: 120.0,
      };
    }

    let targetMonths = [];
    if (seasonFilter === 'DJF') targetMonths = [12, 1, 2];
    else if (seasonFilter === 'MAM') targetMonths = [3, 4, 5];
    else if (seasonFilter === 'JJA') targetMonths = [6, 7, 8];
    else if (seasonFilter === 'SON') targetMonths = [9, 10, 11];
    else if (seasonFilter === 'CUSTOM') targetMonths = customMonths || [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

    for (let y = startYear; y <= endYear; y++) {
      const yearVals = [];
      for (let m = 0; m < fullMonthlySeries.length; m++) {
        const ymYear = baseYear + Math.floor((baseMonth - 1 + m) / 12);
        const ymM = ((baseMonth - 1 + m) % 12) + 1;

        let match = false;
        if (seasonFilter === 'DJF') {
          if ((ymYear === y - 1 && ymM === 12) || (ymYear === y && (ymM === 1 || ymM === 2))) {
            match = true;
          }
        } else {
          if (ymYear === y && targetMonths.includes(ymM)) {
            match = true;
          }
        }

        if (match) {
          const val = fullMonthlySeries[m];
          if (val !== null && !isNaN(val) && isFinite(val)) {
            yearVals.push(val);
          }
        }
      }

      if (yearVals.length > 0) {
        let sum = 0;
        for (let k = 0; k < yearVals.length; k++) sum += yearVals[k];
        const avg = sum / yearVals.length;
        dates.push(String(y));
        values.push(avg);
        timePoints.push(y - startYear);
      }
    }

    return {
      dates,
      values,
      timePoints,
      isAnnual: true,
      slopeMultiplier: 10.0,
    };
  }

  // --- Utilities: Formatting & Multiple-Testing Counter ---
  function formatNumber(num) {
    return Math.round(num).toLocaleString('en-US');
  }

  const MILESTONE_LOOKS = [5, 10, 20];
  const triggeredMilestones = new Set();
  let milestoneToastTimer = null;
  let popoverHoverTimer = null;
  let idleInactivityTimer = null;
  const INACTIVITY_TIMEOUT_MS = 3 * 60 * 1000; // 3 minutes

  function getMultipleTestingNoticeText(count) {
    const pct = Math.min(99, Math.round((1 - Math.pow(0.95, count)) * 100));
    return `You have tested ${count} combinations. With this many looks, the chance of a false positive (p < 0.05) is up to about ${pct}% because looks overlap and are not fully independent. These p-values are not adjusted for multiple testing.`;
  }

  function updateLooksUI() {
    const pill = document.getElementById('looks-pill');
    const pillText = document.getElementById('looks-pill-text');
    const pillIcon = document.getElementById('looks-pill-icon');
    const noticeText = document.getElementById('counter-notice-text');
    const count = state.analysisChoicesCount || 0;

    if (pillText) {
      pillText.textContent = `${count} ${count === 1 ? 'look' : 'looks'}`;
    }
    if (pill) {
      if (count >= 5) {
        pill.classList.add('has-warning');
        if (pillIcon) pillIcon.textContent = '⚠️';
      } else {
        pill.classList.remove('has-warning');
        if (pillIcon) pillIcon.textContent = '🔍';
      }
    }
    if (noticeText) {
      noticeText.textContent = getMultipleTestingNoticeText(count);
    }
  }

  function showMilestoneToast(count) {
    const toast = document.getElementById('looks-milestone-toast');
    const textEl = document.getElementById('milestone-toast-text');
    if (!toast || !textEl) return;

    if (milestoneToastTimer) {
      clearTimeout(milestoneToastTimer);
      milestoneToastTimer = null;
    }

    textEl.textContent = getMultipleTestingNoticeText(count);
    toast.classList.remove('hidden');

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!prefersReduced && typeof gsap !== 'undefined') {
      gsap.fromTo(toast, { opacity: 0, y: -10 }, { opacity: 1, y: 0, duration: 0.3, ease: 'power2.out' });
    } else {
      toast.style.opacity = '1';
    }

    milestoneToastTimer = setTimeout(() => {
      hideMilestoneToast();
    }, 6000);
  }

  function hideMilestoneToast() {
    const toast = document.getElementById('looks-milestone-toast');
    if (!toast || toast.classList.contains('hidden')) return;

    if (milestoneToastTimer) {
      clearTimeout(milestoneToastTimer);
      milestoneToastTimer = null;
    }

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!prefersReduced && typeof gsap !== 'undefined') {
      gsap.to(toast, {
        opacity: 0,
        y: -10,
        duration: 0.2,
        ease: 'power2.in',
        onComplete: () => {
          toast.classList.add('hidden');
        },
      });
    } else {
      toast.classList.add('hidden');
    }
  }

  let isPopoverPinned = false;
  let lastPillMouseEnter = 0;

  function setPopoverExpanded(expanded) {
    const popover = document.getElementById('looks-popover');
    const pill = document.getElementById('looks-pill');
    if (!popover || !pill) return;

    if (popoverHoverTimer) {
      clearTimeout(popoverHoverTimer);
      popoverHoverTimer = null;
    }

    if (expanded) {
      updateLooksUI();
      popover.classList.remove('hidden');
      pill.setAttribute('aria-expanded', 'true');
      const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (!prefersReduced && typeof gsap !== 'undefined') {
        gsap.fromTo(popover, { opacity: 0, y: -6 }, { opacity: 1, y: 0, duration: 0.2, ease: 'power2.out' });
      }
    } else {
      isPopoverPinned = false;
      popover.classList.add('hidden');
      pill.setAttribute('aria-expanded', 'false');
    }
  }

  function recordAnalysisChoice() {
    state.analysisChoicesCount++;
    updateLooksUI();

    const count = state.analysisChoicesCount;
    if (MILESTONE_LOOKS.includes(count) && !triggeredMilestones.has(count)) {
      triggeredMilestones.add(count);
      showMilestoneToast(count);
    }
  }

  function resetAnalysisCounter() {
    state.analysisChoicesCount = 0;
    updateLooksUI();
  }

  function resetInactivityTimer() {
    if (idleInactivityTimer) clearTimeout(idleInactivityTimer);
    idleInactivityTimer = setTimeout(() => {
      resetAnalysisCounter();
    }, INACTIVITY_TIMEOUT_MS);
  }

  // --- ECharts Time-Series Graph ---
  function initCharts() {
    const tsEl = document.getElementById('chart-timeseries');
    const clkEl = document.getElementById('chart-detectability');

    if (tsEl) {
      state.charts.timeseries = echarts.init(tsEl);
    }
    if (clkEl) {
      state.charts.detectability = echarts.init(clkEl);
    }

    window.addEventListener('resize', () => {
      if (state.charts.timeseries) state.charts.timeseries.resize();
      if (state.charts.detectability) state.charts.detectability.resize();
    });
  }

  function updateTimeSeriesChart(dates, anomalies, rollingMean, slopeDecade, isAnnual = false) {
    if (!state.charts.timeseries) return;

    const n = anomalies.length;
    const stepSlope = isAnnual ? slopeDecade / 10.0 : slopeDecade / 120.0;
    let sumY = 0;
    for (let i = 0; i < n; i++) sumY += anomalies[i];
    const meanY = sumY / n;
    const meanX = (n - 1) / 2;
    const intercept = meanY - stepSlope * meanX;

    const trendLine = [];
    for (let i = 0; i < n; i++) {
      trendLine.push(intercept + stepSlope * i);
    }

    const markLineData = [];
    if (state.startYear <= 2014 && state.endYear >= 2014) {
      markLineData.push({ xAxis: isAnnual ? '2014' : '2014-01' });
    }

    const seriesConfig = [
      {
        name: isAnnual ? 'Seasonal Mean' : 'Monthly Anomaly',
        type: 'line',
        data: anomalies,
        symbol: isAnnual ? 'circle' : 'none',
        symbolSize: isAnnual ? 5 : 0,
        itemStyle: isAnnual ? { color: '#22D3EE' } : undefined,
        lineStyle: { width: isAnnual ? 1.8 : 1, color: isAnnual ? '#22D3EE' : '#475569' },
        areaStyle: { color: isAnnual ? 'rgba(34, 211, 238, 0.12)' : 'rgba(71, 85, 105, 0.15)' },
        animationDuration: 800,
        animationEasing: 'cubicOut',
      },
    ];

    if (!isAnnual && rollingMean && rollingMean.length > 0) {
      seriesConfig.push({
        name: '12-Mo Centered Mean',
        type: 'line',
        data: rollingMean,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2.2, color: '#22D3EE' },
        animationDuration: 1200,
        animationDelay: 200,
        animationEasing: 'cubicOut',
      });
    }

    seriesConfig.push({
      name: "Sen's Slope Trend",
      type: 'line',
      data: trendLine,
      symbol: 'none',
      lineStyle: { width: 1.8, type: 'dashed', color: '#FF6B35' },
      animationDuration: 1400,
      animationDelay: 400,
      animationEasing: 'cubicOut',
      markLine: {
        silent: true,
        symbol: 'none',
        label: {
          show: true,
          position: 'insideStartTop',
          formatter: '2014 Transition',
          color: '#F59E0B',
          fontSize: 9,
          fontFamily: 'IBM Plex Mono, monospace',
        },
        lineStyle: { color: '#F59E0B', type: 'dotted', width: 1.2 },
        data: markLineData,
      },
    });

    const option = {
      backgroundColor: 'transparent',
      animation: true,
      grid: { left: 48, right: 15, top: 15, bottom: 22 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(7, 14, 28, 0.96)',
        borderColor: 'rgba(34, 211, 238, 0.45)',
        borderWidth: 1,
        padding: [6, 10],
        textStyle: { color: '#F1F5F9', fontFamily: 'IBM Plex Mono, monospace', fontSize: 11 },
        formatter: (params) => {
          let res = `<div style="font-weight:700;margin-bottom:3px;letter-spacing:0.5px;">${params[0].axisValue}</div>`;
          params.forEach((p) => {
            res += `<div><span style="display:inline-block;width:6px;height:6px;border-radius:1px;background:${p.color};margin-right:5px;"></span>${p.seriesName}: <strong>${p.value != null ? Number(p.value).toFixed(2) : 'N/A'}</strong></div>`;
          });
          return res;
        },
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: 'rgba(34, 211, 238, 0.28)' } },
        axisLabel: {
          color: '#7E91A8',
          fontFamily: 'IBM Plex Mono, monospace',
          fontSize: 9,
          interval: Math.max(1, Math.floor(dates.length / 5)),
        },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: 'rgba(34, 211, 238, 0.10)' } },
        axisLabel: { color: '#7E91A8', fontFamily: 'IBM Plex Mono, monospace', fontSize: 9 },
      },
      series: seriesConfig,
    };

    state.chartDates = dates;
    state.chartSeries = anomalies;
    state.charts.timeseries.setOption(option, true);

    if (state.currentMonthIdx != null && !isAnnual) {
      updateTimeSeriesPlayhead(state.currentMonthIdx);
    }
  }

  // Synchronized Playhead Marker on 25-Year Trajectory
  function updateTimeSeriesPlayhead(m) {
    if (!state.charts.timeseries || !state.chartDates || !state.chartDates[m]) return;
    const dateStr = state.chartDates[m];
    const curVal = state.chartSeries && state.chartSeries[m] != null ? state.chartSeries[m] : null;
    const n = state.chartDates.length;
    const isLeftHalf = m < n / 2;

    state.charts.timeseries.setOption({
      series: [
        {
          name: 'Monthly Anomaly',
          markLine: {
            silent: true,
            symbol: ['none', 'none'],
            animation: false,
            label: {
              show: true,
              position: 'insideEndTop',
              rotate: 0,
              align: isLeftHalf ? 'left' : 'right',
              verticalAlign: 'top',
              offset: isLeftHalf ? [6, 4] : [-6, 4],
              formatter: () => dateStr,
              color: '#22D3EE',
              fontSize: 9,
              fontFamily: 'IBM Plex Mono, monospace',
              backgroundColor: 'rgba(7, 14, 28, 0.95)',
              borderColor: 'rgba(34, 211, 238, 0.6)',
              borderWidth: 1,
              borderRadius: 2,
              padding: [2, 5],
            },
            lineStyle: {
              color: '#22D3EE',
              width: 1.5,
              type: 'solid',
            },
            data: [{ xAxis: dateStr }],
          },
          markPoint: curVal != null ? {
            silent: true,
            symbol: 'circle',
            symbolSize: 8,
            animation: false,
            itemStyle: {
              color: '#22D3EE',
              borderColor: '#FFFFFF',
              borderWidth: 2,
              shadowColor: 'rgba(34, 211, 238, 0.8)',
              shadowBlur: 6,
            },
            data: [{ coord: [dateStr, curVal] }],
          } : { data: [] },
        },
      ],
    });
  }

  // --- ECharts Detectability Clock ---
  function updateDetectabilityChart(series) {
    if (!state.charts.detectability) return;

    const windows = [5, 8, 12, 16, 20, 25.3];
    const pVals = [];

    windows.forEach((w) => {
      const monthCutoff = Math.min(series.length, Math.round(w * 12));
      const sub = series.slice(0, monthCutoff).filter((v) => v !== null && !isNaN(v) && isFinite(v));
      if (sub.length < 4) {
        pVals.push(1.0);
      } else {
        const hr = computeHamedRao(sub, 0.05);
        pVals.push(hr.p != null ? Math.min(1.0, Math.max(0.0001, hr.p)) : 1.0);
      }
    });

    const clockStatus = document.getElementById('clock-status-pill');
    let sigYear = null;
    for (let k = 0; k < pVals.length; k++) {
      if (pVals[k] < 0.05) {
        sigYear = windows[k];
        break;
      }
    }
    if (clockStatus) {
      if (sigYear !== null) {
        clockStatus.textContent = `Significant after ~${sigYear.toFixed(1)} yrs`;
        clockStatus.style.color = '#34D399';
      } else {
        const lastP = pVals[pVals.length - 1];
        clockStatus.textContent = `Not yet sig (p = ${lastP.toFixed(3)})`;
        clockStatus.style.color = '#A0B2C6';
      }
    }

    const option = {
      backgroundColor: 'transparent',
      animationDuration: 1000,
      grid: { left: 45, right: 15, top: 12, bottom: 20 },
      xAxis: {
        type: 'category',
        data: ['5y', '8y', '12y', '16y', '20y', '25.3y'],
        axisLine: { lineStyle: { color: 'rgba(34, 211, 238, 0.28)' } },
        axisLabel: { color: '#7E91A8', fontFamily: 'IBM Plex Mono, monospace', fontSize: 9 },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 1.0,
        splitLine: { lineStyle: { color: 'rgba(34, 211, 238, 0.10)' } },
        axisLabel: { color: '#7E91A8', fontFamily: 'IBM Plex Mono, monospace', fontSize: 9 },
      },
      series: [
        {
          name: 'p-value (HR)',
          type: 'line',
          data: pVals,
          smooth: true,
          symbol: 'circle',
          symbolSize: 5,
          lineStyle: { width: 2, color: '#22D3EE' },
          itemStyle: { color: '#22D3EE' },
          markLine: {
            silent: true,
            symbol: 'none',
            label: {
              show: true,
              position: 'insideEndTop',
              formatter: 'α = 0.05',
              color: '#F59E0B',
              fontSize: 9,
              fontFamily: 'IBM Plex Mono, monospace',
            },
            lineStyle: { color: '#F59E0B', type: 'dashed', width: 1 },
            data: [{ yAxis: 0.05 }],
          },
        },
      ],
    };

    state.charts.detectability.setOption(option);
  }

  // --- Update Verdict Card, CI Range Bar & Inspector Telemetry ---
  function updateInspector(latIdx, lonIdx) {
    const varData = state.cache[state.currentVarId];
    if (!varData) return;

    if (latIdx === undefined) latIdx = state.cellIndex.latIdx;
    if (lonIdx === undefined) lonIdx = state.cellIndex.lonIdx;

    gsap.fromTo(
      ['#verdict-card', '.chart-card', '.lineup-card'],
      { opacity: 0.5, y: 6 },
      { opacity: 1, y: 0, duration: 0.35, stagger: 0.06, ease: 'power2.out' }
    );

    const isPointMode = state.selectionMode === 'point';
    const isFullRecord = state.startYear === 2000 && state.endYear === 2025;
    const isAllYear = state.seasonFilter === 'ALL';
    const isPrecomputedCell = isPointMode && isFullRecord && isAllYear;

    const { meta, trend, anomalies } = varData;
    const comp = meta.compression || {};
    const scale = comp.anom_scale_factor || comp.scale || 0.01;
    const offset = comp.anom_offset || comp.offset || 0.0;
    const nCells = N_LATS * N_LONS;

    const modeIcon = document.getElementById('inspector-mode-icon');
    const coordsEl = document.getElementById('inspector-coords');
    const nameEl = document.getElementById('inspector-name');

    let fullMonthlySeries = [];
    let isMasked = false;
    let locationDisplayName = '';

    if (isPointMode) {
      if (modeIcon) {
        modeIcon.innerHTML = '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>';
      }
      const curLat = TARGET_LATS[latIdx];
      const curLon = TARGET_LONS[lonIdx];
      if (coordsEl) {
        coordsEl.textContent = `LAT: ${curLat.toFixed(2)}°, LON: ${curLon.toFixed(2)}°`;
      }

      locationDisplayName = 'Ocean / Open Water';
      if (curLat >= -15 && curLat <= 5 && curLon >= -75 && curLon <= -45) locationDisplayName = 'Amazon Basin, South America';
      else if (curLat >= 10 && curLat <= 20 && curLon >= -18 && curLon <= 35) locationDisplayName = 'Sahel Corridor, Africa';
      else if (curLat >= 28 && curLat <= 38 && curLon >= 75 && curLon <= 102) locationDisplayName = 'Tibetan Plateau / Himalayas';
      else if (curLat >= 50 && curLat <= 62 && curLon >= -125 && curLon <= -95) locationDisplayName = 'Central Canada Boreal';
      else if (Math.abs(curLat) > 60) locationDisplayName = 'Polar Ice Zone (Masked)';
      else if (trend.valid[latIdx][lonIdx] === 1) locationDisplayName = 'Terrestrial Continental Grid Cell';

      if (nameEl) nameEl.textContent = locationDisplayName;

      const cellValid = trend.valid[latIdx][lonIdx] === 1;
      const rawSlope = trend.slopes[latIdx][lonIdx];
      isMasked = !cellValid || rawSlope === -32768;

      const cellOffset = latIdx * N_LONS + lonIdx;
      for (let m = 0; m < state.totalMonths; m++) {
        if (isMasked) {
          fullMonthlySeries.push(null);
        } else {
          const valIdx = m * nCells + cellOffset;
          const rawInt = anomalies[valIdx];
          fullMonthlySeries.push(rawInt === -32768 ? null : rawInt * scale + offset);
        }
      }
    } else {
      if (modeIcon) {
        modeIcon.innerHTML = '<rect x="3" y="3" width="18" height="18" rx="2" stroke-dasharray="2 2"/>';
      }
      const { s, n, w, e } = state.regionBbox;
      if (coordsEl) {
        coordsEl.textContent = `S: ${s.toFixed(1)}°, N: ${n.toFixed(1)}°, W: ${w.toFixed(1)}°, E: ${e.toFixed(1)}°`;
      }

      locationDisplayName = 'Custom Geographic Region';
      Object.keys(REGION_PRESETS).forEach((k) => {
        const p = REGION_PRESETS[k];
        if (p && Math.abs(p.s - s) < 1.5 && Math.abs(p.n - n) < 1.5 && Math.abs(p.w - w) < 1.5 && Math.abs(p.e - e) < 1.5) {
          locationDisplayName = p.name;
        }
      });
      if (nameEl) nameEl.textContent = locationDisplayName;

      const regRes = computeRegionalTimeSeries(state.currentVarId, state.regionBbox);
      if (regRes) {
        fullMonthlySeries = regRes.series;
        isMasked = regRes.isMasked;

        const cellCountEl = document.getElementById('region-cell-count');
        const areaValEl = document.getElementById('region-area-val');
        const warnSmall = document.getElementById('region-small-warn');
        const warnEmpty = document.getElementById('region-empty-warn');
        const warnMasked = document.getElementById('region-masked-info');

        if (cellCountEl) cellCountEl.textContent = `${regRes.validCount} VALID CELLS (OF ${regRes.totalCount})`;
        if (areaValEl) areaValEl.textContent = `${formatNumber(regRes.areaKm2)} km²`;

        if (warnSmall) warnSmall.classList.toggle('hidden', regRes.validCount >= 4 || regRes.validCount === 0);
        if (warnEmpty) warnEmpty.classList.toggle('hidden', regRes.validCount > 0);
        if (warnMasked) warnMasked.classList.toggle('hidden', regRes.totalCount === regRes.validCount || regRes.validCount === 0);
      }
    }

    const periodBadge = document.getElementById('period-badge');
    const periodYears = state.endYear - state.startYear + (isAllYear ? 0.3 : 1);
    if (periodBadge) {
      periodBadge.textContent = `${state.startYear} – ${state.endYear} (${periodYears.toFixed(1)} YRS)`;
    }

    const seasonBadge = document.getElementById('season-badge');
    const seasonNames = {
      ALL: 'ALL YEAR',
      DJF: 'DJF (WINTER)',
      MAM: 'MAM (SPRING)',
      JJA: 'JJA (SUMMER / SMOKE)',
      SON: 'SON (AUTUMN)',
      CUSTOM: 'CUSTOM MONTHS',
    };
    if (seasonBadge) {
      seasonBadge.textContent = seasonNames[state.seasonFilter] || state.seasonFilter;
    }

    const selTextEl = document.getElementById('verdict-selection-text');
    const calcBadgeEl = document.getElementById('verdict-calc-badge');

    const seasonLabel = seasonNames[state.seasonFilter] || state.seasonFilter;
    const periodLabel = `${state.startYear}–${state.endYear}`;

    if (selTextEl) {
      if (isPointMode) {
        selTextEl.textContent = `Point: ${TARGET_LATS[latIdx].toFixed(2)}°, ${TARGET_LONS[lonIdx].toFixed(2)}° | ${periodLabel} | ${seasonLabel}`;
      } else {
        const areaStr = document.getElementById('region-area-val')?.textContent || '';
        selTextEl.textContent = `Region: ${locationDisplayName} (${areaStr}) | ${periodLabel} | ${seasonLabel}`;
      }
    }

    if (calcBadgeEl) {
      if (isPrecomputedCell) {
        calcBadgeEl.textContent = 'Precomputed Telemetry';
        calcBadgeEl.className = 'verdict-calc-badge precomputed';
      } else {
        calcBadgeEl.textContent = '[ Estimate computed in your browser ]';
        calcBadgeEl.className = 'verdict-calc-badge estimated';
      }
    }

    const warnShort = document.getElementById('period-warn-short');
    const warnBlocked = document.getElementById('period-warn-blocked');
    const numYears = state.endYear - state.startYear;
    if (warnShort) warnShort.classList.toggle('hidden', numYears >= 10);
    if (warnBlocked) warnBlocked.classList.toggle('hidden', numYears >= 5);

    if (isMasked) {
      document.getElementById('val-rate').textContent = 'MASKED';
      document.getElementById('val-unit').textContent = '';
      document.getElementById('val-phr').textContent = 'N/A';
      document.getElementById('val-pplain').textContent = 'N/A';
      document.getElementById('verdict-status-text').textContent = 'REGION/CELL MASKED (ICE / OCEAN)';
      document.getElementById('verdict-card').className = 'verdict-card state-neutral';
      document.getElementById('verdict-caution-box').classList.add('hidden');

      state.inspectorData = {
        latIdx,
        lonIdx,
        series: [],
        dates: [],
        rollingMean: [],
        mean: 0,
        std: 1.0,
        unit: '',
        isMasked: true,
      };
      updateInspectorMonthlyTelemetry(state.currentMonthIdx);
      updatePlanetaryLineup(latIdx, lonIdx, state.currentMonthIdx);
      return;
    }

    const analysis = extractAnalysisSeries(
      fullMonthlySeries,
      state.startYear,
      state.endYear,
      state.seasonFilter,
      state.customMonths
    );

    let officialSlopeDecade = 0;
    let p_hr = 1.0;
    let p_plain = 1.0;
    let q_fdr = 0.05;
    let isSig = false;
    let isTrending = false;
    let ci_lower = 0;
    let ci_upper = 0;
    let mean = 0;
    let std = 1.0;

    if (isPrecomputedCell) {
      const slopeScale = trend.slope_scale || 1.0;
      const rawSlope = trend.slopes[latIdx][lonIdx];
      officialSlopeDecade = rawSlope * slopeScale;
      p_plain = trend.p_values ? trend.p_values[latIdx][lonIdx] / 10000.0 : 0.05;
      q_fdr = trend.q_values ? trend.q_values[latIdx][lonIdx] / 10000.0 : 0.05;
      isSig = trend.significant_fdr[latIdx][lonIdx] === 1;

      const stats = computeFullStats(analysis.values, analysis.timePoints, analysis.slopeMultiplier);
      p_hr = stats.p_hr !== null ? stats.p_hr : p_plain;
      ci_lower = stats.ci_lower;
      ci_upper = stats.ci_upper;
      mean = stats.mean;
      std = stats.std;
      isTrending = !isSig && (p_hr < 0.1 || p_plain < 0.05);
    } else {
      const stats = computeFullStats(analysis.values, analysis.timePoints, analysis.slopeMultiplier);
      officialSlopeDecade = stats.slopeDecade;
      p_hr = stats.p_hr;
      p_plain = stats.p_plain;
      q_fdr = p_hr;
      isSig = stats.isSig;
      isTrending = stats.isTrending;
      ci_lower = stats.ci_lower;
      ci_upper = stats.ci_upper;
      mean = stats.mean;
      std = stats.std;
    }

    const rateEl = document.getElementById('val-rate');
    const unitEl = document.getElementById('val-unit');
    const phrEl = document.getElementById('val-phr');
    const pplainEl = document.getElementById('val-pplain');
    const fdrBadge = document.getElementById('verdict-fdr-badge');

    const isHrNan = isPrecomputedCell
      ? (trend.hr_nan && trend.hr_nan[latIdx] && trend.hr_nan[latIdx][lonIdx] === 1) ||
        (trend.p_values && trend.p_values[latIdx][lonIdx] === null)
      : (p_hr === null || isNaN(p_hr) || p_hr === undefined);

    animateNumber(rateEl, officialSlopeDecade, 2, '+');
    unitEl.textContent = meta.trend_units || 'units/dec';
    if (isHrNan) {
      phrEl.textContent = 'N/A';
    } else {
      animateNumber(phrEl, p_hr, 4);
    }
    animateNumber(pplainEl, p_plain, 4);
    if (fdrBadge) {
      if (isPrecomputedCell) {
        fdrBadge.textContent = isHrNan ? `p(plain) = ${p_plain.toFixed(4)}` : `FDR q = ${q_fdr.toFixed(4)}`;
      } else {
        fdrBadge.textContent = isHrNan ? `p(plain) = ${p_plain.toFixed(4)}` : `p(HR) = ${p_hr.toFixed(4)}`;
      }
    }

    const verdictCard = document.getElementById('verdict-card');
    const statusText = document.getElementById('verdict-status-text');

    if (numYears < 5) {
      verdictCard.className = 'verdict-card state-neutral';
      statusText.textContent = 'RECORD TOO SHORT (< 5 YRS)';
    } else if (isSig) {
      verdictCard.className = 'verdict-card state-significant';
      statusText.textContent = isPrecomputedCell ? 'SIGNIFICANT TREND (q < 0.05)' : 'SIGNIFICANT TREND (p < 0.05)';
    } else if (isTrending) {
      verdictCard.className = 'verdict-card state-trending';
      statusText.textContent = 'TRENDING (NOT YET SIGNIFICANT)';
    } else {
      verdictCard.className = 'verdict-card state-neutral';
      statusText.textContent = 'NO CLEAR TREND';
    }

    const ciText = document.getElementById('ci-bounds-text');
    const ciSpan = document.getElementById('ci-range-span');
    const ciPoint = document.getElementById('ci-point-marker');

    ciText.textContent = `[${ci_lower.toFixed(2)}, ${ci_upper.toFixed(2)}]`;

    const scaleMax = Math.max(Math.abs(ci_lower), Math.abs(ci_upper), Math.abs(officialSlopeDecade), 1.0) * 1.5;
    const leftPct = Math.max(0, Math.min(100, 50 + (ci_lower / scaleMax) * 50));
    const rightPct = Math.max(0, Math.min(100, 50 + (ci_upper / scaleMax) * 50));
    const pointPct = Math.max(0, Math.min(100, 50 + (officialSlopeDecade / scaleMax) * 50));

    gsap.to(ciSpan, { left: `${leftPct}%`, width: `${Math.max(2, rightPct - leftPct)}%`, duration: 0.5, ease: 'power2.out' });
    gsap.to(ciPoint, { left: `${pointPct}%`, duration: 0.5, ease: 'power2.out' });

    const cautionBox = document.getElementById('verdict-caution-box');
    const cautionHeader = document.getElementById('caution-header-text');
    const cautionText = document.getElementById('verdict-caution-text');
    const eb = meta.era_break_2014_check || {};
    const hasEraCaution = isPrecomputedCell && (eb.caution === true || (eb.amazon_both_eras_sig_flip && locationDisplayName.includes('Amazon')));

    if (isHrNan && cautionBox && cautionText) {
      if (cautionHeader) cautionHeader.textContent = 'STATISTICAL METHOD NOTICE';
      const hrNote = 'autocorrelation adjustment unavailable here; plain Mann-Kendall p shown';
      if (hasEraCaution && eb.caution_note) {
        cautionText.textContent = `${eb.caution_note} (Note: ${hrNote})`;
      } else {
        cautionText.textContent = hrNote;
      }
      cautionBox.classList.remove('hidden');
    } else if (hasEraCaution && cautionBox && cautionText) {
      if (cautionHeader) cautionHeader.textContent = 'OBSERVING SYSTEM SHIFT NOTICE';
      cautionText.textContent =
        eb.caution_note ||
        'Notice: Trend-aware test indicates a surviving 2014 era-step discontinuity. Interpret full-record trend with caution.';
      cautionBox.classList.remove('hidden');
    } else if (cautionBox) {
      cautionBox.classList.add('hidden');
    }

    const rollingMean = [];
    if (!analysis.isAnnual) {
      for (let i = 0; i < analysis.values.length; i++) {
        if (i < 5 || i >= analysis.values.length - 6) {
          rollingMean.push(null);
        } else {
          let sum = 0, count = 0;
          for (let k = i - 5; k <= i + 6; k++) {
            if (analysis.values[k] != null) {
              sum += analysis.values[k];
              count++;
            }
          }
          rollingMean.push(count >= 10 ? sum / count : null);
        }
      }
    }

    state.inspectorData = {
      latIdx,
      lonIdx,
      series: fullMonthlySeries,
      dates: analysis.dates,
      analysisValues: analysis.values,
      rollingMean,
      mean,
      std,
      unit: meta.trend_units || meta.units || 'units/mo',
      isMasked: false,
      isAnnual: analysis.isAnnual,
    };

    updateTimeSeriesChart(analysis.dates, analysis.values, rollingMean, officialSlopeDecade, analysis.isAnnual);
    updateDetectabilityChart(fullMonthlySeries);
    updateInspectorMonthlyTelemetry(state.currentMonthIdx);
    updatePlanetaryLineup(latIdx, lonIdx, state.currentMonthIdx);
  }

  // --- Live Real-Time Monthly Observation Telemetry ---
  function updateInspectorMonthlyTelemetry(m) {
    if (!state.inspectorData) return;
    const { latIdx, lonIdx, series, dates, rollingMean, std, unit, isMasked } = state.inspectorData;

    const baseYear = 2000;
    const baseMonth = 6;
    const ymYear = baseYear + Math.floor((baseMonth - 1 + m) / 12);
    const ymM = ((baseMonth - 1 + m) % 12) + 1;
    const monthNames = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
    const dateStr = `${monthNames[ymM - 1]} ${ymYear}`;

    const dateBadge = document.getElementById('obs-date-badge');
    if (dateBadge) {
      dateBadge.textContent = `${dateStr} [M${String(m + 1).padStart(3, '0')}]`;
    }

    const valEl = document.getElementById('obs-anomaly-val');
    const unitEl = document.getElementById('obs-anomaly-unit');
    const zEl = document.getElementById('obs-zscore-val');
    const rollEl = document.getElementById('obs-rolling-val');
    const gaugeBar = document.getElementById('obs-gauge-bar');
    const gaugeMarker = document.getElementById('obs-gauge-marker');

    if (unitEl) {
      unitEl.textContent = (unit || '').replace('/dec', '');
    }

    if (isMasked || !series || series[m] === null || series[m] === undefined) {
      if (valEl) {
        valEl.textContent = isMasked ? 'MASKED' : 'N/A';
        valEl.style.color = 'var(--text-secondary)';
      }
      if (zEl) zEl.textContent = 'N/A';
      if (rollEl) rollEl.textContent = '--';
      if (gaugeBar) gaugeBar.style.width = '0%';
      if (gaugeMarker) gaugeMarker.style.left = '50%';
      return;
    }

    const val = series[m];
    const roll = rollingMean && rollingMean[m] != null ? rollingMean[m] : null;
    const zScore = std > 0 ? val / std : 0;

    if (valEl) {
      valEl.textContent = (val > 0 ? '+' : '') + val.toFixed(2);
      valEl.style.color = val >= 0 ? '#22D3EE' : '#F97316';
    }

    if (zEl) {
      zEl.textContent = (zScore > 0 ? '+' : '') + zScore.toFixed(1) + ' σ';
      zEl.style.color = Math.abs(zScore) >= 2.0 ? '#EF4444' : (val >= 0 ? '#22D3EE' : '#F97316');
    }

    if (rollEl) {
      rollEl.textContent = roll !== null ? (roll > 0 ? '+' : '') + roll.toFixed(2) : '--';
    }

    if (gaugeBar && gaugeMarker) {
      const clampedZ = Math.max(-3.0, Math.min(3.0, zScore));
      const pct = 50 + (clampedZ / 3.0) * 50;
      gaugeMarker.style.left = `${pct}%`;

      if (pct >= 50) {
        gaugeBar.style.left = '50%';
        gaugeBar.style.width = `${pct - 50}%`;
        gaugeBar.style.background = '#22D3EE';
      } else {
        gaugeBar.style.left = `${pct}%`;
        gaugeBar.style.width = `${50 - pct}%`;
        gaugeBar.style.background = '#F97316';
      }
    }

    // Synchronize playhead on 25-year trajectory chart
    updateTimeSeriesPlayhead(m);

    // Synchronize lineup if in monthly view
    updatePlanetaryLineup(latIdx, lonIdx, m);
  }

  // --- Local Planetary Lineup Ranking ---
  function updatePlanetaryLineup(latIdx, lonIdx, m = state.currentMonthIdx) {
    const lineupEl = document.getElementById('lineup-table');
    if (!lineupEl) return;

    const isMonthly = state.lineupMode === 'monthly';
    const subLabel = document.getElementById('lineup-sub-label');
    const btnMonthly = document.getElementById('btn-lineup-monthly');
    const btnTrend = document.getElementById('btn-lineup-trend');

    if (btnMonthly && btnTrend) {
      btnMonthly.classList.toggle('active', isMonthly);
      btnTrend.classList.toggle('active', !isMonthly);
    }

    const baseYear = 2000;
    const baseMonth = 6;
    const ymYear = baseYear + Math.floor((baseMonth - 1 + m) / 12);
    const ymM = ((baseMonth - 1 + m) % 12) + 1;
    const monthNames = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
    const dateStr = `${monthNames[ymM - 1]} ${ymYear}`;

    if (subLabel) {
      subLabel.textContent = isMonthly
        ? `Anomaly in ${dateStr} at Pinned Coordinates`
        : '25-Year Trend Rate (Sen\'s slope / decade) at Pinned Coordinates';
    }

    const cellFlatIdx = latIdx * N_LONS + lonIdx;
    const rankings = [];

    // Background prefetch uncached variables so all 12 lineup rows populate
    VARIABLES_LIST.forEach((v) => {
      if (!state.cache[v.id]) {
        loadVariable(v.id).then(() => {
          if (state.cellIndex) updatePlanetaryLineup(state.cellIndex.latIdx, state.cellIndex.lonIdx, state.currentMonthIdx);
        }).catch(() => {});
      }
    });

    VARIABLES_LIST.forEach((v) => {
      const data = state.cache[v.id];
      if (!data) {
        rankings.push({ ...v, strength: 0, text: 'Loading...', isMasked: false });
        return;
      }

      const valid = data.trend.valid[latIdx][lonIdx] === 1;
      if (!valid) {
        rankings.push({ ...v, strength: 0, text: 'No data', isMasked: true });
        return;
      }

      if (isMonthly && data.anomalies) {
        const comp = data.meta.compression || {};
        const scale = comp.anom_scale_factor || comp.scale || 0.01;
        const offset = comp.anom_offset || comp.offset || 0.0;
        const nCells = N_LATS * N_LONS;
        const valIdx = m * nCells + latIdx * N_LONS + lonIdx;
        const rawInt = data.anomalies[valIdx];
        if (rawInt === -32768) {
          rankings.push({ ...v, strength: 0, text: 'No data', isMasked: true });
          return;
        }
        const val = rawInt * scale + offset;
        const normScale = v.id.includes('temp') || v.id.includes('ts')
          ? 2.5
          : v.id.includes('precip')
          ? 40.0
          : v.id.includes('soil')
          ? 20.0
          : v.id.includes('aod')
          ? 0.15
          : v.id.includes('swe')
          ? 10.0
          : v.id.includes('wind')
          ? 2.0
          : 25.0;
        const strength = Math.min(1.0, Math.abs(val) / normScale);
        const unit = (v.unit || '').replace('/dec', '');
        rankings.push({
          ...v,
          strength,
          text: (val > 0 ? '+' : '') + val.toFixed(2) + (unit ? ' ' + unit : ''),
          isMasked: false,
          isPositive: val >= 0,
        });
      } else {
        const raw = data.trend.slopes[latIdx][lonIdx];
        if (raw === -32768) {
          rankings.push({ ...v, strength: 0, text: 'No data', isMasked: true });
          return;
        }
        const slope = raw * (data.trend.slope_scale || 1.0);
        const normSlope = v.id.includes('temp') || v.id.includes('ts')
          ? 0.5
          : v.id.includes('precip')
          ? 6.0
          : v.id.includes('soil')
          ? 3.0
          : v.id.includes('aod')
          ? 0.03
          : v.id.includes('swe')
          ? 2.0
          : v.id.includes('wind')
          ? 0.5
          : 5.0;
        const absNorm = Math.min(1.0, Math.abs(slope) / normSlope);
        const unit = (v.unit || '').replace('/decade', '/dec');
        rankings.push({
          ...v,
          strength: absNorm,
          text: (slope > 0 ? '+' : '') + slope.toFixed(2) + (unit ? ' ' + unit : ''),
          isMasked: false,
          isPositive: slope >= 0,
        });
      }
    });

    rankings.sort((a, b) => b.strength - a.strength);

    lineupEl.innerHTML = '';
    rankings.forEach((r, idx) => {
      const row = document.createElement('div');
      row.className = 'lineup-row';
      row.style.cursor = 'pointer';
      row.title = `Click to switch view to ${r.name}`;
      row.addEventListener('click', () => switchVariable(r.id));
      const barColor = r.isMasked ? 'transparent' : (r.isPositive ? 'var(--cyan-accent)' : 'var(--orange-accent)');
      row.innerHTML = `
        <span class="lineup-rank">#${idx + 1}</span>
        <span class="lineup-name" title="${r.name}">${r.name}</span>
        <div class="lineup-bar-track">
          <div class="lineup-bar-fill" style="width: ${r.isMasked ? 0 : Math.round(r.strength * 100)}%; background: ${barColor};"></div>
        </div>
        <span class="lineup-val font-mono">${r.text}</span>
      `;
      lineupEl.appendChild(row);
    });
  }

  // --- Switch Active Planetary Variable ---
  async function switchVariable(varId) {
    state.currentVarId = varId;

    document.querySelectorAll('.var-btn').forEach((b) => {
      b.classList.toggle('active', b.dataset.varid === varId);
    });

    const activeBadge = document.getElementById('active-var-badge');
    const matched = VARIABLES_LIST.find((v) => v.id === varId);
    if (activeBadge && matched) {
      activeBadge.textContent = matched.name.split(' ')[0].toUpperCase();
    }

    const varData = await loadVariable(varId);
    updateGridLayer(varData);
    updateInspector(state.cellIndex.latIdx, state.cellIndex.lonIdx);
  }

  // --- Time Scrubber & Filmstrip Playback Loop ---
  let playbackTimer = null;

  function updateScrubberUI(m) {
    state.currentMonthIdx = m;
    const slider = document.getElementById('scrubber-slider');
    const dateLabel = document.getElementById('scrubber-current-date');
    const eventTag = document.getElementById('scrubber-event-tag');

    if (slider) slider.value = m;

    const baseYear = 2000;
    const baseMonth = 6;
    const ymYear = baseYear + Math.floor((baseMonth - 1 + m) / 12);
    const ymM = ((baseMonth - 1 + m) % 12) + 1;
    const monthNames = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
    const dateStr = `${monthNames[ymM - 1]} ${ymYear}`;

    if (dateLabel) {
      dateLabel.textContent = `${dateStr} (Month ${m + 1} of ${state.totalMonths})`;
    }

    if (eventTag) {
      const matchKey = Object.keys(CLIMATE_EVENTS).find((k) => Math.abs(Number(k) - m) <= 2);
      if (matchKey) {
        eventTag.textContent = `★ ${CLIMATE_EVENTS[matchKey]}`;
        eventTag.style.color = '#FF6B35';
      } else {
        eventTag.textContent = m < 163 ? 'TRMM Era (2000–2013)' : 'GPM Era (2014–2025)';
        eventTag.style.color = '#94A3B8';
      }
    }

    const varData = state.cache[state.currentVarId];
    if (varData && state.viewMode === 'monthly') {
      updateGridLayer(varData);
    }

    // Live update inspector observation telemetry, trajectory playhead & lineup
    updateInspectorMonthlyTelemetry(m);
  }

  function togglePlayPause() {
    state.isPlaying = !state.isPlaying;
    const iconPlay = document.getElementById('icon-play');
    const iconPause = document.getElementById('icon-pause');

    if (state.isPlaying) {
      iconPlay.classList.add('hidden');
      iconPause.classList.remove('hidden');

      if (state.viewMode !== 'monthly') {
        document.getElementById('btn-view-monthly').click();
      }

      const delay = Math.round(140 / state.playbackSpeed);
      playbackTimer = setInterval(() => {
        let nextM = (state.currentMonthIdx + 1) % state.totalMonths;
        updateScrubberUI(nextM);
      }, delay);
    } else {
      iconPlay.classList.remove('hidden');
      iconPause.classList.add('hidden');
      if (playbackTimer) clearInterval(playbackTimer);
      playbackTimer = null;
    }
  }


  // --- Boot Sequence & Web Audio CRT Sound Engine ---
  const bootEngine = {
    audioCtx: null,
    isActive: false,
    isExiting: false,
    timerIds: [],

    getAudioContext() {
      if (!this.audioCtx) {
        try {
          const AudioContextClass = window.AudioContext || window.webkitAudioContext;
          if (AudioContextClass) {
            this.audioCtx = new AudioContextClass();
          }
        } catch (e) {}
      }
      if (this.audioCtx && this.audioCtx.state === 'suspended') {
        this.audioCtx.resume().catch(() => {});
      }
      return this.audioCtx;
    },

    async resumeAudio() {
      const ctx = this.getAudioContext();
      if (ctx && ctx.state === 'suspended') {
        try {
          await ctx.resume();
        } catch (e) {}
      }
      return ctx;
    },

    // 1. Authentic CRT degauss thump & high-voltage flyback charging whine
    playDegauss() {
      const ctx = this.getAudioContext();
      if (!ctx) return;
      if (ctx.state === 'suspended') {
        ctx.resume().catch(() => {});
      }
      try {
        const now = ctx.currentTime;
        
        // Deep sub-bass degauss coil surge (85Hz down to 24Hz)
        const oscLow = ctx.createOscillator();
        const gainLow = ctx.createGain();
        oscLow.type = 'sine';
        oscLow.frequency.setValueAtTime(85, now);
        oscLow.frequency.exponentialRampToValueAtTime(24, now + 0.45);
        gainLow.gain.setValueAtTime(0.42, now);
        gainLow.gain.exponentialRampToValueAtTime(0.0001, now + 0.45);
        oscLow.connect(gainLow);
        gainLow.connect(ctx.destination);
        oscLow.start(now);
        oscLow.stop(now + 0.46);

        // High-voltage flyback transformer charge whine (450Hz up to 9,500Hz)
        const oscHigh = ctx.createOscillator();
        const gainHigh = ctx.createGain();
        oscHigh.type = 'triangle';
        oscHigh.frequency.setValueAtTime(450, now);
        oscHigh.frequency.exponentialRampToValueAtTime(9500, now + 0.55);
        gainHigh.gain.setValueAtTime(0.001, now);
        gainHigh.gain.linearRampToValueAtTime(0.24, now + 0.18);
        gainHigh.gain.exponentialRampToValueAtTime(0.0001, now + 0.55);
        oscHigh.connect(gainHigh);
        gainHigh.connect(ctx.destination);
        oscHigh.start(now);
        oscHigh.stop(now + 0.56);
      } catch (e) {}
    },

    // 2. Analog Glitch & Static Burst
    playGlitchBurst() {
      const ctx = this.getAudioContext();
      if (!ctx) return;
      if (ctx.state === 'suspended') {
        ctx.resume().catch(() => {});
      }
      try {
        const now = ctx.currentTime;
        const dur = 0.16;
        const bufferSize = Math.floor(ctx.sampleRate * dur);
        const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < bufferSize; i++) {
          data[i] = (Math.random() * 2 - 1) * (Math.random() > 0.4 ? 1 : 0.25);
        }

        const noise = ctx.createBufferSource();
        noise.buffer = buffer;

        const filter = ctx.createBiquadFilter();
        filter.type = 'bandpass';
        filter.frequency.setValueAtTime(2400, now);
        filter.frequency.exponentialRampToValueAtTime(800, now + dur);
        filter.Q.value = 3.5;

        const gain = ctx.createGain();
        gain.gain.setValueAtTime(0.30, now);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + dur);

        noise.connect(filter);
        filter.connect(gain);
        gain.connect(ctx.destination);

        noise.start(now);
        noise.stop(now + dur);
      } catch (e) {}
    },

    // 3. Monospace BIOS Terminal typing blip
    playBlip(freq = 1400) {
      const ctx = this.getAudioContext();
      if (!ctx) return;
      if (ctx.state === 'suspended') {
        ctx.resume().catch(() => {});
      }
      try {
        const now = ctx.currentTime;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'square';
        osc.frequency.setValueAtTime(freq, now);
        gain.gain.setValueAtTime(0.20, now);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.04);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now);
        osc.stop(now + 0.042);
      } catch (e) {}
    },

    // 4. Futuristic sci-fi system unlock chime
    playChime() {
      const ctx = this.getAudioContext();
      if (!ctx) return;
      if (ctx.state === 'suspended') {
        ctx.resume().catch(() => {});
      }
      try {
        const now = ctx.currentTime;
        const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6 chord
        notes.forEach((freq, idx) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = 'sine';
          osc.frequency.setValueAtTime(freq, now + idx * 0.035);
          gain.gain.setValueAtTime(0.25 / (1 + idx * 0.35), now + idx * 0.035);
          gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.75 + idx * 0.05);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(now + idx * 0.035);
          osc.stop(now + 0.8 + idx * 0.05);
        });
      } catch (e) {}
    },

    start(force = false) {
      const overlay = document.getElementById('boot-overlay');
      if (!overlay) return;

      this.clearTimers();
      this.isExiting = false;

      const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      // Skip on automated initial load unless explicitly forced (e.g. key B or replayBoot)
      if (!force && (window.navigator.webdriver || prefersReducedMotion || window.location.hash.startsWith('#demo-'))) {
        this.finish(true);
        return;
      }

      this.isActive = true;
      this.getAudioContext();
      overlay.classList.remove('hidden', 'fade-out', 'phase-beam-ignite', 'phase-beam-open', 'glitching', 'phase-glitch-out');
      overlay.style.pointerEvents = 'auto';

      // Force browser reflow to reliably restart animations
      void overlay.offsetWidth;

      // Reset lines and terminal actions
      for (let i = 1; i <= 5; i++) {
        document.getElementById(`boot-line-${i}`)?.classList.remove('visible');
      }
      document.getElementById('boot-terminal-actions')?.classList.remove('visible');

      // Phase 1: High-voltage flyback charge & CRT beam ignition
      this.playDegauss();
      this.timerIds.push(setTimeout(() => {
        if (!this.isActive || this.isExiting) return;
        overlay.classList.add('phase-beam-ignite');
      }, 80));

      // Phase 2: Dwell on glowing beam for 700ms so user actually sees and enjoys the CRT electron beam,
      // then expand vertically into full monitor screen!
      this.timerIds.push(setTimeout(() => {
        if (!this.isActive || this.isExiting) return;
        this.playGlitchBurst();
        overlay.classList.add('glitching');
        overlay.classList.add('phase-beam-open');
      }, 750));

      this.timerIds.push(setTimeout(() => {
        if (!this.isActive || this.isExiting) return;
        overlay.classList.remove('glitching');
      }, 1250));

      // Phase 3: Telemetry lines typing sequentially with clear, deliberate pacing
      const lines = [
        { id: 'boot-line-1', delay: 1400, freq: 1100 },
        { id: 'boot-line-2', delay: 1850, freq: 1350 },
        { id: 'boot-line-3', delay: 2300, freq: 1600 },
        { id: 'boot-line-4', delay: 2750, freq: 1850 },
        { id: 'boot-line-5', delay: 3200, freq: 2200 },
      ];

      lines.forEach((l) => {
        this.timerIds.push(setTimeout(() => {
          if (!this.isActive || this.isExiting) return;
          const el = document.getElementById(l.id);
          if (el) el.classList.add('visible');
          this.playBlip(l.freq);
        }, l.delay));
      });

      // Phase 4: Ready status, unlock chime & reveal action button
      this.timerIds.push(setTimeout(() => {
        if (!this.isActive || this.isExiting) return;
        this.playChime();
        const actions = document.getElementById('boot-terminal-actions');
        if (actions) actions.classList.add('visible');
      }, 3450));

      // Terminal stays on screen and waits for user interaction [Space, Enter, Esc, or Enter Button]
    },

    async exitWithGlitch(source = 'action') {
      if (this.isExiting) return;
      this.isExiting = true;
      this.clearTimers();

      const overlay = document.getElementById('boot-overlay');
      if (!overlay) {
        this.finish(true);
        return;
      }

      await this.resumeAudio();
      this.playGlitchBurst();
      this.playChime();

      // Trigger chromatic aberration CRT glitch collapse
      overlay.classList.add('phase-glitch-out');

      this.timerIds.push(setTimeout(() => {
        this.finish(true);
      }, 420));
    },

    clearTimers() {
      this.timerIds.forEach((t) => clearTimeout(t));
      this.timerIds = [];
    },

    finish(immediate = false) {
      this.clearTimers();
      this.isActive = false;
      this.isExiting = false;
      const overlay = document.getElementById('boot-overlay');
      if (!overlay) return;

      if (immediate) {
        overlay.classList.add('hidden');
        overlay.classList.remove('phase-beam-ignite', 'phase-beam-open', 'glitching', 'phase-glitch-out', 'fade-out');
        overlay.style.pointerEvents = 'none';
        return;
      }

      overlay.classList.add('fade-out');
      setTimeout(() => {
        overlay.classList.add('hidden');
        overlay.classList.remove('phase-beam-ignite', 'phase-beam-open', 'glitching', 'phase-glitch-out', 'fade-out');
        overlay.style.pointerEvents = 'none';
      }, 400);
    }
  };

  // --- Manual Bounding Box, Period Range & Seasonal Filters ---
  function applyManualBbox() {
    const inpS = document.getElementById('bbox-s');
    const inpN = document.getElementById('bbox-n');
    const inpW = document.getElementById('bbox-w');
    const inpE = document.getElementById('bbox-e');

    const sVal = parseFloat(inpS ? inpS.value : '-15');
    const nVal = parseFloat(inpN ? inpN.value : '5');
    const wVal = parseFloat(inpW ? inpW.value : '-75');
    const eVal = parseFloat(inpE ? inpE.value : '-45');

    const s = Math.max(-60, Math.min(60, isNaN(sVal) ? -15 : sVal));
    const n = Math.max(-60, Math.min(60, isNaN(nVal) ? 5 : nVal));
    const w = Math.max(-180, Math.min(180, isNaN(wVal) ? -75 : wVal));
    const e = Math.max(-180, Math.min(180, isNaN(eVal) ? -45 : eVal));

    state.regionBbox = {
      s: Math.min(s, n),
      n: Math.max(s, n),
      w: Math.min(w, e),
      e: Math.max(w, e),
    };

    syncBboxInputs();
    updateRegionGeoJson();
    recordAnalysisChoice();
    updateInspector();
  }

  function handlePeriodPreset(periodKey) {
    let start = 2000, end = 2025;
    if (periodKey === '2000-2013') { start = 2000; end = 2013; }
    else if (periodKey === '2014-2025') { start = 2014; end = 2025; }
    else if (periodKey === '2015-2025') { start = 2015; end = 2025; }
    else { start = 2000; end = 2025; }

    setPeriodRange(start, end, periodKey);
  }

  function setPeriodRange(start, end, activePresetKey = null) {
    state.startYear = Math.min(start, end);
    state.endYear = Math.max(start, end);

    const sStart = document.getElementById('slider-period-start');
    const sEnd = document.getElementById('slider-period-end');
    const iStart = document.getElementById('input-period-start');
    const iEnd = document.getElementById('input-period-end');

    if (sStart) sStart.value = state.startYear;
    if (sEnd) sEnd.value = state.endYear;
    if (iStart) iStart.value = state.startYear;
    if (iEnd) iEnd.value = state.endYear;

    document.querySelectorAll('.period-chips .chip-btn').forEach((btn) => {
      if (activePresetKey) {
        btn.classList.toggle('active', btn.dataset.period === activePresetKey);
      } else {
        const isMatch = btn.dataset.period === `${state.startYear}-${state.endYear}`;
        btn.classList.toggle('active', isMatch);
      }
    });

    recordAnalysisChoice();
    updateInspector();
  }

  function handleSeasonPreset(seasonKey) {
    state.seasonFilter = seasonKey;

    document.querySelectorAll('.season-chips .chip-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.season === seasonKey);
    });

    const customBar = document.getElementById('custom-months-bar');
    if (customBar) {
      customBar.classList.toggle('hidden', seasonKey !== 'CUSTOM');
    }

    recordAnalysisChoice();
    updateInspector();
  }

  function toggleCustomMonth(monthNum) {
    if (!state.customMonths) state.customMonths = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
    const idx = state.customMonths.indexOf(monthNum);
    if (idx >= 0) {
      if (state.customMonths.length > 1) {
        state.customMonths.splice(idx, 1);
      }
    } else {
      state.customMonths.push(monthNum);
      state.customMonths.sort((a, b) => a - b);
    }

    document.querySelectorAll('.custom-months-bar .month-btn').forEach((btn) => {
      const m = Number(btn.dataset.month);
      btn.classList.toggle('active', state.customMonths.includes(m));
    });

    if (state.seasonFilter !== 'CUSTOM') {
      handleSeasonPreset('CUSTOM');
    } else {
      recordAnalysisChoice();
      updateInspector();
    }
  }

  function handleShareLink() {
    const hash = getShareableHash();
    history.replaceState(null, '', hash);

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(window.location.href).then(() => {
        showToast('Shareable URL copied to clipboard!');
      }).catch(() => {
        showToast(`Shareable URL: ${window.location.href}`);
      });
    } else {
      showToast(`Shareable URL: ${window.location.href}`);
    }
  }

  function getShareableHash() {
    const p = new URLSearchParams();
    p.set('v', state.currentVarId);
    p.set('mode', state.selectionMode);
    if (state.selectionMode === 'point') {
      p.set('lat', state.currentPin.lat.toFixed(2));
      p.set('lon', state.currentPin.lon.toFixed(2));
    } else {
      p.set('bbox', `${state.regionBbox.s.toFixed(1)},${state.regionBbox.n.toFixed(1)},${state.regionBbox.w.toFixed(1)},${state.regionBbox.e.toFixed(1)}`);
    }
    p.set('start', state.startYear);
    p.set('end', state.endYear);
    p.set('season', state.seasonFilter);
    if (state.seasonFilter === 'CUSTOM') {
      p.set('months', state.customMonths.join(','));
    }
    return '#' + p.toString();
  }

  function parseAndApplyHash(hash) {
    if (!hash || !hash.includes('=')) return false;
    const raw = hash.replace(/^#/, '');
    const p = new URLSearchParams(raw);

    const v = p.get('v');
    if (v && VARIABLES_LIST.some((item) => item.id === v)) {
      state.currentVarId = v;
    }

    const mode = p.get('mode');
    if (mode === 'point' || mode === 'region') {
      state.selectionMode = mode;
    }

    if (state.selectionMode === 'point') {
      const lat = parseFloat(p.get('lat'));
      const lon = parseFloat(p.get('lon'));
      if (!isNaN(lat) && !isNaN(lon)) {
        const snap = snapCoordsToGrid(lat, lon);
        state.cellIndex = snap;
        state.currentPin = { lat: snap.snappedLat, lon: snap.snappedLon };
      }
    } else {
      const bboxStr = p.get('bbox');
      if (bboxStr) {
        const parts = bboxStr.split(',').map(Number);
        if (parts.length === 4 && parts.every((n) => !isNaN(n))) {
          state.regionBbox = { s: parts[0], n: parts[1], w: parts[2], e: parts[3] };
        }
      }
    }

    const start = parseInt(p.get('start'), 10);
    const end = parseInt(p.get('end'), 10);
    if (!isNaN(start) && start >= 2000 && start <= 2025) state.startYear = start;
    if (!isNaN(end) && end >= 2000 && end <= 2025) state.endYear = end;

    const season = p.get('season');
    if (['ALL', 'DJF', 'MAM', 'JJA', 'SON', 'CUSTOM'].includes(season)) {
      state.seasonFilter = season;
    }

    const monthsStr = p.get('months');
    if (monthsStr) {
      const m = monthsStr.split(',').map(Number).filter((n) => n >= 1 && n <= 12);
      if (m.length > 0) state.customMonths = m;
    }

    return true;
  }

  // --- Build Variable Selection Menu ---
  function renderVariablePicker() {
    const nav = document.getElementById('variable-picker');
    if (!nav) return;
    nav.innerHTML = '';

    VARIABLES_LIST.forEach((v) => {
      const btn = document.createElement('button');
      btn.className = `var-btn ${v.id === state.currentVarId ? 'active' : ''}`;
      btn.dataset.varid = v.id;
      btn.innerHTML = `
        <div class="var-btn-left">
          <span class="var-btn-name">${v.name}</span>
          <span class="var-btn-meta">${v.agency}</span>
        </div>
        <span class="var-btn-indicator"></span>
      `;
      btn.addEventListener('click', () => switchVariable(v.id));
      nav.appendChild(btn);
    });
  }

  // --- Map Interaction & Pin Placement Engine ---
  function setupMapInteraction(map) {
    if (!map || map._kendallInteractionSetup) return;
    map._kendallInteractionSetup = true;

    const tooltip = document.getElementById('hover-tooltip');
    const crosshair = document.getElementById('map-crosshair');
    const canvas = map.getCanvas ? map.getCanvas() : null;

    let lastSelectionTime = 0;

    // Core point selector (places pin, eases camera, updates inspector)
    function handlePointerSelection(lat, lon) {
      const now = performance.now();
      if (now - lastSelectionTime < 120) return;
      lastSelectionTime = now;

      state.isSpinningIntro = false;
      if (state.isDrawingRegion || state.isMorphing) return;
      if (typeof lat !== 'number' || typeof lon !== 'number' || isNaN(lat) || isNaN(lon)) return;

      selectPoint(lat, lon);
      const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      map.easeTo({ center: [state.currentPin.lon, state.currentPin.lat], duration: prefersReduced ? 0 : 600 });
    }

    // Core region drawing helpers
    function startDrawing(lngLat) {
      if (!lngLat) return;
      state.isSpinningIntro = false;
      state.drawStartLngLat = {
        lat: Math.max(-60, Math.min(60, lngLat.lat)),
        lng: Math.max(-180, Math.min(180, lngLat.lng)),
      };
      state.regionBbox = {
        s: state.drawStartLngLat.lat,
        n: state.drawStartLngLat.lat,
        w: state.drawStartLngLat.lng,
        e: state.drawStartLngLat.lng,
      };
      updateRegionGeoJson();
    }

    function updateDrawing(lngLat) {
      if (!state.isDrawingRegion || !state.drawStartLngLat || !lngLat) return;
      const curLat = Math.max(-60, Math.min(60, lngLat.lat));
      const curLng = Math.max(-180, Math.min(180, lngLat.lng));
      state.regionBbox = {
        s: Math.min(state.drawStartLngLat.lat, curLat),
        n: Math.max(state.drawStartLngLat.lat, curLat),
        w: Math.min(state.drawStartLngLat.lng, curLng),
        e: Math.max(state.drawStartLngLat.lng, curLng),
      };
      updateRegionGeoJson();
      syncBboxInputs();
    }

    function finishDrawing(endLngLat) {
      if (!state.isDrawingRegion || !state.drawStartLngLat) return;
      let curLat = endLngLat ? Math.max(-60, Math.min(60, endLngLat.lat)) : (state.regionBbox ? state.regionBbox.n : state.drawStartLngLat.lat);
      let curLng = endLngLat ? Math.max(-180, Math.min(180, endLngLat.lng)) : (state.regionBbox ? state.regionBbox.e : state.drawStartLngLat.lng);

      let s = Math.min(state.drawStartLngLat.lat, curLat);
      let n = Math.max(state.drawStartLngLat.lat, curLat);
      let w = Math.min(state.drawStartLngLat.lng, curLng);
      let e = Math.max(state.drawStartLngLat.lng, curLng);

      // If drawn box is smaller than 1.0 degree in either dimension (single click or tiny tap),
      // snap to a 5x5 degree box centered around the click point so single-click drawing works intuitively
      if (Math.abs(n - s) < 1.0 || Math.abs(e - w) < 1.0) {
        const centerLat = (n + s) / 2;
        const centerLng = (e + w) / 2;
        s = Math.max(-60, centerLat - 2.5);
        n = Math.min(60, centerLat + 2.5);
        w = Math.max(-180, centerLng - 2.5);
        e = Math.min(180, centerLng + 2.5);
      }

      state.regionBbox = { s, n, w, e };
      state.drawStartLngLat = null;
      toggleDrawRegion(false);
      updateRegionGeoJson();
      syncBboxInputs();
      recordAnalysisChoice();
      updateInspector();
    }

    // Stop intro spin on any map interaction
    map.on('dragstart', () => { state.isSpinningIntro = false; });
    map.on('zoomstart', () => { state.isSpinningIntro = false; });
    map.on('pitchstart', () => { state.isSpinningIntro = false; });

    map.on('mousedown', (e) => {
      state.isSpinningIntro = false;
      if (state.isDrawingRegion && e.lngLat) {
        startDrawing(e.lngLat);
      }
    });

    map.on('touchstart', (e) => {
      state.isSpinningIntro = false;
      if (state.isDrawingRegion) {
        if (e.touches && e.touches.length === 1 && canvas) {
          const rect = canvas.getBoundingClientRect();
          const unproj = map.unproject([e.touches[0].clientX - rect.left, e.touches[0].clientY - rect.top]);
          if (unproj) startDrawing(unproj);
        }
      }
    });

    map.on('mousemove', (e) => {
      if (!e.lngLat) {
        if (tooltip) tooltip.classList.add('hidden');
        if (crosshair) crosshair.classList.add('crosshair-hidden');
        return;
      }

      if (state.isDrawingRegion && state.drawStartLngLat) {
        updateDrawing(e.lngLat);
        return;
      }

      const snap = snapCoordsToGrid(e.lngLat.lat, e.lngLat.lng);
      const varData = state.cache[state.currentVarId];
      if (!varData) return;

      const rawSlope = varData.trend.slopes[snap.latIdx][snap.lonIdx];
      const isValid = varData.trend.valid[snap.latIdx][snap.lonIdx] === 1;

      if (tooltip && isValid && rawSlope !== -32768) {
        const slope = rawSlope * (varData.trend.slope_scale || 1.0);
        const pVal = varData.trend.p_values ? varData.trend.p_values[snap.latIdx][snap.lonIdx] / 10000 : 0.05;
        const isSig = varData.trend.significant_fdr[snap.latIdx][snap.lonIdx] === 1;

        document.getElementById('tt-coords').textContent = `${snap.snappedLat.toFixed(2)}°, ${snap.snappedLon.toFixed(2)}°`;
        document.getElementById('tt-rate').textContent = (slope > 0 ? '+' : '') + slope.toFixed(2);
        document.getElementById('tt-phr').textContent = pVal.toFixed(3);
        const ttStatus = document.getElementById('tt-status');
        ttStatus.textContent = isSig ? 'SIGNIFICANT' : 'NO TREND';
        ttStatus.style.color = isSig ? 'var(--green-sig)' : 'var(--text-secondary)';
        ttStatus.style.background = isSig ? 'rgba(52, 211, 153, 0.15)' : 'rgba(160, 178, 198, 0.15)';

        tooltip.style.left = `${e.point.x + 14}px`;
        tooltip.style.top = `${e.point.y + 14}px`;
        tooltip.classList.remove('hidden');
      } else if (tooltip) {
        tooltip.classList.add('hidden');
      }

      if (crosshair) {
        crosshair.style.left = `${e.point.x}px`;
        crosshair.style.top = `${e.point.y}px`;
        crosshair.classList.remove('crosshair-hidden');
      }
    });

    map.on('touchmove', (e) => {
      if (state.isDrawingRegion && state.drawStartLngLat && e.touches && e.touches.length === 1 && canvas) {
        const rect = canvas.getBoundingClientRect();
        const unproj = map.unproject([e.touches[0].clientX - rect.left, e.touches[0].clientY - rect.top]);
        if (unproj) updateDrawing(unproj);
      }
    });

    map.on('mouseup', (e) => {
      if (state.isDrawingRegion && state.drawStartLngLat) {
        finishDrawing(e.lngLat);
      }
    });

    window.addEventListener('mouseup', (e) => {
      if (state.isDrawingRegion && state.drawStartLngLat) {
        const mapEl = document.getElementById('map');
        if (mapEl) {
          const rect = mapEl.getBoundingClientRect();
          const unproj = map.unproject([e.clientX - rect.left, e.clientY - rect.top]);
          finishDrawing(unproj);
        } else {
          finishDrawing(null);
        }
      }
    });

    window.addEventListener('touchend', () => {
      if (state.isDrawingRegion && state.drawStartLngLat) {
        finishDrawing(null);
      }
    });

    window.addEventListener('mousemove', (e) => {
      if (state.isDrawingRegion && state.drawStartLngLat) {
        const mapEl = document.getElementById('map');
        if (mapEl) {
          const rect = mapEl.getBoundingClientRect();
          const unproj = map.unproject([e.clientX - rect.left, e.clientY - rect.top]);
          if (unproj) updateDrawing(unproj);
        }
      }
    });

    map.on('mouseout', () => {
      if (tooltip) tooltip.classList.add('hidden');
      if (crosshair) crosshair.classList.add('crosshair-hidden');
    });

    // Native MapLibre Click handler
    map.on('click', (e) => {
      state.isSpinningIntro = false;
      if (state.isDrawingRegion || state.isMorphing) return;
      if (!e.lngLat) return;
      handlePointerSelection(e.lngLat.lat, e.lngLat.lng);
    });

    // --- Window-Level Capture Phase Point Selection & Click Engine ---
    let ptrDownX = 0;
    let ptrDownY = 0;
    let ptrDownTime = 0;
    let isDownOnMap = false;

    window.addEventListener('pointerdown', (e) => {
      const mapEl = document.getElementById('map');
      if (mapEl && (mapEl.contains(e.target) || e.target.closest('#map, #map-container'))) {
        state.isSpinningIntro = false;
        ptrDownX = e.clientX;
        ptrDownY = e.clientY;
        ptrDownTime = performance.now();
        isDownOnMap = true;
        if (state.isDrawingRegion) {
          const rect = mapEl.getBoundingClientRect();
          const unproj = map.unproject([e.clientX - rect.left, e.clientY - rect.top]);
          if (unproj) startDrawing(unproj);
        }
      } else {
        isDownOnMap = false;
      }
    }, { capture: true, passive: true });

    window.addEventListener('pointerup', (e) => {
      if (!isDownOnMap) return;
      isDownOnMap = false;
      state.isSpinningIntro = false;
      if (state.isDrawingRegion || state.isMorphing) return;

      if (e.target.closest('button, input, a, .region-handle-marker, .preset-item, .looks-popover, #intro-overlay, #boot-overlay, #modal-shortcuts, .header-hud, .inspector-panel, .scrubber-bar, #panel-left, #panel-right')) {
        return;
      }

      const mapEl = document.getElementById('map');
      if (!mapEl) return;

      const dist = Math.hypot(e.clientX - ptrDownX, e.clientY - ptrDownY);
      const elapsed = performance.now() - ptrDownTime;

      // Allow generous tolerance for trackpad tap (up to 25px travel, up to 900ms duration)
      if (dist <= 25 && elapsed < 900) {
        const rect = mapEl.getBoundingClientRect();
        const pt = [e.clientX - rect.left, e.clientY - rect.top];
        const unproj = map.unproject(pt);
        if (unproj && !isNaN(unproj.lat) && !isNaN(unproj.lng)) {
          handlePointerSelection(unproj.lat, unproj.lng);
        }
      }
    }, { capture: true });

    // Native DOM click listener (standard fallback for all pointing devices)
    window.addEventListener('click', (e) => {
      const mapEl = document.getElementById('map');
      if (!mapEl) return;
      if (e.target.closest('button, input, a, .region-handle-marker, .preset-item, .looks-popover, #intro-overlay, #boot-overlay, #modal-shortcuts, .header-hud, .inspector-panel, .scrubber-bar, #panel-left, #panel-right')) {
        return;
      }
      if (mapEl.contains(e.target) || e.target.closest('#map, #map-container')) {
        state.isSpinningIntro = false;
        if (state.isDrawingRegion || state.isMorphing) return;
        const rect = mapEl.getBoundingClientRect();
        const pt = [e.clientX - rect.left, e.clientY - rect.top];
        const unproj = map.unproject(pt);
        if (unproj && !isNaN(unproj.lat) && !isNaN(unproj.lng)) {
          handlePointerSelection(unproj.lat, unproj.lng);
        }
      }
    }, { capture: true });
  }

  // --- Setup Event Listeners ---
  function setupListeners() {
    // Global User Interaction Audio Activator (unblocks Web Audio across origin)
    const unlockAllAudio = () => {
      bootEngine.resumeAudio();
    };
    ['pointerdown', 'keydown', 'touchstart', 'mousedown'].forEach((evt) => {
      window.addEventListener(evt, unlockAllAudio, { passive: true });
    });

    // Boot sequence overlay handlers
    const bootOverlay = document.getElementById('boot-overlay');
    if (bootOverlay) {
      bootOverlay.addEventListener('click', () => {
        // Only allow clicking background backdrop to dismiss if boot has finished typing
        const actions = document.getElementById('boot-terminal-actions');
        const isDone = actions && actions.classList.contains('visible');
        if (isDone && bootEngine.isActive && !bootEngine.isExiting) {
          bootEngine.exitWithGlitch('backdrop_click');
        }
      });
    }
    const btnBootEnter = document.getElementById('btn-boot-enter');
    if (btnBootEnter) {
      btnBootEnter.addEventListener('click', (e) => {
        e.stopPropagation();
        if (bootEngine.isActive && !bootEngine.isExiting) {
          bootEngine.exitWithGlitch('btn_enter_click');
        }
      });
    }
    const btnBootSkip = document.getElementById('btn-boot-skip');
    if (btnBootSkip) {
      btnBootSkip.addEventListener('click', (e) => {
        e.stopPropagation();
        if (bootEngine.isActive && !bootEngine.isExiting) {
          bootEngine.exitWithGlitch('btn_skip_click');
        }
      });
    }

    const dismissIntro = () => {
      bootEngine.finish(true);
      state.isSpinningIntro = false;
      const intro = document.getElementById('intro-overlay');
      if (intro) {
        intro.style.pointerEvents = 'none';
        intro.classList.add('hidden');
      }
    };

    const btnStart = document.getElementById('btn-intro-start');
    if (btnStart) {
      btnStart.addEventListener('click', dismissIntro);
    }
    const introBackdrop = document.querySelector('.intro-backdrop');
    if (introBackdrop) {
      introBackdrop.addEventListener('click', dismissIntro);
    }

    // Projection Segmented Toggle Buttons
    const btnProjFlat = document.getElementById('btn-proj-flat');
    const btnProjGlobe = document.getElementById('btn-proj-globe');

    if (btnProjFlat) {
      btnProjFlat.addEventListener('click', () => setProjection('flat'));
      btnProjFlat.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          setProjection('flat');
        }
      });
    }

    if (btnProjGlobe) {
      btnProjGlobe.addEventListener('click', () => setProjection('globe'));
      btnProjGlobe.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          setProjection('globe');
        }
      });
    }

    // Reset North Compass Button
    const btnResetNorth = document.getElementById('btn-reset-north');
    if (btnResetNorth) {
      btnResetNorth.addEventListener('click', () => {
        const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (state.map) {
          state.map.easeTo({ bearing: 0, pitch: 0, duration: prefersReduced ? 0 : 600 });
        }
      });
    }

    // Tilt Button wiring
    const btnToggleTilt = document.getElementById('btn-toggle-tilt');
    if (btnToggleTilt) {
      btnToggleTilt.addEventListener('click', toggleTilt);
    }

    if (state.map) {
      setupMapInteraction(state.map);
    }

    // Selection Mode Toggle Buttons
    const btnModePoint = document.getElementById('btn-mode-point');
    const btnModeRegion = document.getElementById('btn-mode-region');
    if (btnModePoint) {
      btnModePoint.addEventListener('click', () => setSelectionMode('point'));
    }
    if (btnModeRegion) {
      btnModeRegion.addEventListener('click', () => setSelectionMode('region'));
    }

    // Draw Region Buttons
    const btnDrawRegion = document.getElementById('btn-draw-region');
    const btnExitDraw = document.getElementById('btn-exit-draw');
    if (btnDrawRegion) {
      btnDrawRegion.addEventListener('click', () => toggleDrawRegion());
    }
    if (btnExitDraw) {
      btnExitDraw.addEventListener('click', () => toggleDrawRegion(false));
    }

    // Presets Dropdown
    const btnRegionPresets = document.getElementById('btn-region-presets');
    const presetsMenu = document.getElementById('presets-menu');
    if (btnRegionPresets && presetsMenu) {
      btnRegionPresets.addEventListener('click', (e) => {
        e.stopPropagation();
        presetsMenu.classList.toggle('hidden');
      });
      window.addEventListener('click', () => {
        presetsMenu.classList.add('hidden');
      });
    }

    document.querySelectorAll('#presets-menu .preset-item').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (presetsMenu) presetsMenu.classList.add('hidden');
        applyPreset(btn.dataset.preset);
      });
    });

    // Manual Bbox Controls
    const btnApplyBbox = document.getElementById('btn-apply-bbox');
    if (btnApplyBbox) {
      btnApplyBbox.addEventListener('click', applyManualBbox);
    }
    ['bbox-s', 'bbox-n', 'bbox-w', 'bbox-e'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') applyManualBbox();
        });
      }
    });

    // Analysis Counter Pill & Popover Controls
    const looksPill = document.getElementById('looks-pill');
    const looksPopover = document.getElementById('looks-popover');
    const btnClosePopover = document.getElementById('btn-close-looks-popover');
    const btnCloseMilestoneToast = document.getElementById('btn-close-milestone-toast');
    const btnResetCounter = document.getElementById('btn-reset-counter');

    if (looksPill) {
      looksPill.addEventListener('mouseenter', () => {
        lastPillMouseEnter = Date.now();
        if (popoverHoverTimer) clearTimeout(popoverHoverTimer);
        setPopoverExpanded(true);
      });

      looksPill.addEventListener('mouseleave', () => {
        if (!isPopoverPinned) {
          popoverHoverTimer = setTimeout(() => {
            setPopoverExpanded(false);
          }, 250);
        }
      });

      looksPill.addEventListener('click', (e) => {
        e.stopPropagation();
        const now = Date.now();
        // If clicked within 600ms of hover or not currently pinned, pin it open
        if (!isPopoverPinned || (now - lastPillMouseEnter < 600)) {
          isPopoverPinned = true;
          setPopoverExpanded(true);
        } else {
          isPopoverPinned = false;
          setPopoverExpanded(false);
        }
      });
    }

    if (looksPopover) {
      looksPopover.addEventListener('mouseenter', () => {
        if (popoverHoverTimer) clearTimeout(popoverHoverTimer);
      });

      looksPopover.addEventListener('mouseleave', () => {
        if (!isPopoverPinned) {
          popoverHoverTimer = setTimeout(() => {
            setPopoverExpanded(false);
          }, 250);
        }
      });

      looksPopover.addEventListener('click', (e) => {
        e.stopPropagation();
      });
    }

    if (btnClosePopover) {
      btnClosePopover.addEventListener('click', (e) => {
        e.stopPropagation();
        isPopoverPinned = false;
        setPopoverExpanded(false);
      });
    }

    if (btnResetCounter) {
      btnResetCounter.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        resetAnalysisCounter();
      });
    }

    if (btnCloseMilestoneToast) {
      btnCloseMilestoneToast.addEventListener('click', (e) => {
        e.stopPropagation();
        hideMilestoneToast();
      });
    }

    // Click away to close popover
    document.addEventListener('click', (e) => {
      const widget = document.getElementById('analysis-looks-widget');
      if (widget && !widget.contains(e.target)) {
        setPopoverExpanded(false);
      }
    });

    // Inactivity listener tracking
    ['mousemove', 'mousedown', 'keydown', 'touchstart', 'pointerdown', 'wheel'].forEach((evt) => {
      window.addEventListener(evt, resetInactivityTimer, { passive: true });
    });
    resetInactivityTimer();

    // Period Selection Controls
    document.querySelectorAll('.period-chips .chip-btn').forEach((btn) => {
      btn.addEventListener('click', () => handlePeriodPreset(btn.dataset.period));
    });

    const sStart = document.getElementById('slider-period-start');
    const sEnd = document.getElementById('slider-period-end');
    const iStart = document.getElementById('input-period-start');
    const iEnd = document.getElementById('input-period-end');

    if (sStart && sEnd) {
      sStart.addEventListener('input', (e) => {
        const val = parseInt(e.target.value, 10);
        if (val > state.endYear) sStart.value = state.endYear;
        setPeriodRange(parseInt(sStart.value, 10), state.endYear);
      });
      sEnd.addEventListener('input', (e) => {
        const val = parseInt(e.target.value, 10);
        if (val < state.startYear) sEnd.value = state.startYear;
        setPeriodRange(state.startYear, parseInt(sEnd.value, 10));
      });
    }

    if (iStart && iEnd) {
      iStart.addEventListener('change', (e) => {
        const val = parseInt(e.target.value, 10);
        if (!isNaN(val) && val >= 2000 && val <= 2025) {
          setPeriodRange(val, Math.max(val, state.endYear));
        }
      });
      iEnd.addEventListener('change', (e) => {
        const val = parseInt(e.target.value, 10);
        if (!isNaN(val) && val >= 2000 && val <= 2025) {
          setPeriodRange(Math.min(val, state.startYear), val);
        }
      });
    }

    // Seasonal Filter Controls
    document.querySelectorAll('.season-chips .chip-btn').forEach((btn) => {
      btn.addEventListener('click', () => handleSeasonPreset(btn.dataset.season));
    });

    document.querySelectorAll('.custom-months-bar .month-btn').forEach((btn) => {
      btn.addEventListener('click', () => toggleCustomMonth(Number(btn.dataset.month)));
    });

    // Share Link Button
    const btnShareLink = document.getElementById('btn-share-link');
    if (btnShareLink) {
      btnShareLink.addEventListener('click', handleShareLink);
    }

    const toggleTwins = document.getElementById('toggle-opposite-twins');
    if (toggleTwins) {
      toggleTwins.addEventListener('change', (e) => {
        state.oppositeTwins = e.target.checked;
        const varData = state.cache[state.currentVarId];
        if (varData) updateGridLayer(varData);
      });
    }

    const toggleSpeckle = document.getElementById('toggle-speckle-filter');
    if (toggleSpeckle) {
      toggleSpeckle.addEventListener('change', (e) => {
        state.speckleFilter = e.target.checked;
        const varData = state.cache[state.currentVarId];
        if (varData) updateGridLayer(varData);
      });
    }

    const btnViewTrend = document.getElementById('btn-view-trend');
    const btnViewMonthly = document.getElementById('btn-view-monthly');

    if (btnViewTrend && btnViewMonthly) {
      btnViewTrend.addEventListener('click', () => {
        state.viewMode = 'trend';
        state.lineupMode = 'trend';
        btnViewTrend.classList.add('active');
        btnViewMonthly.classList.remove('active');
        const varData = state.cache[state.currentVarId];
        if (varData) updateGridLayer(varData);
        updatePlanetaryLineup(state.cellIndex.latIdx, state.cellIndex.lonIdx, state.currentMonthIdx);
      });

      btnViewMonthly.addEventListener('click', () => {
        state.viewMode = 'monthly';
        state.lineupMode = 'monthly';
        btnViewMonthly.classList.add('active');
        btnViewTrend.classList.remove('active');
        const varData = state.cache[state.currentVarId];
        if (varData) updateGridLayer(varData);
        updatePlanetaryLineup(state.cellIndex.latIdx, state.cellIndex.lonIdx, state.currentMonthIdx);
      });
    }

    const btnLineupMonthly = document.getElementById('btn-lineup-monthly');
    const btnLineupTrend = document.getElementById('btn-lineup-trend');
    if (btnLineupMonthly && btnLineupTrend) {
      btnLineupMonthly.addEventListener('click', () => {
        state.lineupMode = 'monthly';
        updatePlanetaryLineup(state.cellIndex.latIdx, state.cellIndex.lonIdx, state.currentMonthIdx);
      });
      btnLineupTrend.addEventListener('click', () => {
        state.lineupMode = 'trend';
        updatePlanetaryLineup(state.cellIndex.latIdx, state.cellIndex.lonIdx, state.currentMonthIdx);
      });
    }

    const btnPlay = document.getElementById('btn-play-pause');
    if (btnPlay) {
      btnPlay.addEventListener('click', togglePlayPause);
    }

    const slider = document.getElementById('scrubber-slider');
    if (slider) {
      slider.addEventListener('input', (e) => {
        updateScrubberUI(Number(e.target.value));
      });
    }

    document.querySelectorAll('.speed-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.speed-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        state.playbackSpeed = Number(btn.dataset.speed);
        if (state.isPlaying) {
          togglePlayPause();
          togglePlayPause();
        }
      });
    });

    const btnShortcuts = document.getElementById('btn-shortcuts');
    const modalShortcuts = document.getElementById('modal-shortcuts');
    const btnCloseShortcuts = document.getElementById('btn-close-shortcuts');

    if (btnShortcuts && modalShortcuts) {
      btnShortcuts.addEventListener('click', () => modalShortcuts.classList.remove('hidden'));
    }
    if (btnCloseShortcuts && modalShortcuts) {
      btnCloseShortcuts.addEventListener('click', () => modalShortcuts.classList.add('hidden'));
    }

    const btnToastClose = document.getElementById('btn-toast-close');
    if (btnToastClose) {
      btnToastClose.addEventListener('click', () => {
        document.getElementById('error-toast').classList.add('hidden');
      });
    }

    const btnMobileSheet = document.getElementById('btn-mobile-sheet');
    const panelRight = document.getElementById('panel-right');
    if (btnMobileSheet && panelRight) {
      btnMobileSheet.addEventListener('click', () => {
        panelRight.classList.toggle('sheet-expanded');
      });
    }

    window.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT') return;

      if (bootEngine.isActive) {
        if (e.code === 'Space' || e.code === 'Enter' || e.key === 'Escape') {
          e.preventDefault();
          bootEngine.exitWithGlitch('keydown_' + e.code);
          return;
        }
      }

      const introEl = document.getElementById('intro-overlay');
      const isIntroVisible = introEl && !introEl.classList.contains('hidden');
      if (isIntroVisible) {
        if (e.code === 'Enter' || e.code === 'Space' || e.key === 'Escape') {
          e.preventDefault();
          dismissIntro();
        } else if (e.code === 'KeyB' || e.key.toLowerCase() === 'b') {
          e.preventDefault();
          bootEngine.start(true);
        }
        return;
      }

      if (e.code === 'Space') {
        e.preventDefault();
        togglePlayPause();
      } else if (e.code === 'ArrowRight') {
        e.preventDefault();
        const curIdx = VARIABLES_LIST.findIndex((v) => v.id === state.currentVarId);
        const nextId = VARIABLES_LIST[(curIdx + 1) % VARIABLES_LIST.length].id;
        switchVariable(nextId);
      } else if (e.code === 'ArrowLeft') {
        e.preventDefault();
        const curIdx = VARIABLES_LIST.findIndex((v) => v.id === state.currentVarId);
        const prevId = VARIABLES_LIST[(curIdx - 1 + VARIABLES_LIST.length) % VARIABLES_LIST.length].id;
        switchVariable(prevId);
      } else if (e.key.toLowerCase() === 'd') {
        toggleDrawRegion();
      } else if (e.key.toLowerCase() === 'r') {
        setSelectionMode(state.selectionMode === 'point' ? 'region' : 'point');
      } else if (e.key.toLowerCase() === 'o') {
        const toggle = document.getElementById('toggle-opposite-twins');
        if (toggle) {
          toggle.checked = !toggle.checked;
          toggle.dispatchEvent(new Event('change'));
        }
      } else if (e.key.toLowerCase() === 's') {
        const toggle = document.getElementById('toggle-speckle-filter');
        if (toggle) {
          toggle.checked = !toggle.checked;
          toggle.dispatchEvent(new Event('change'));
        }
      } else if (e.key.toLowerCase() === 'g') {
        const nextProj = (state.projection === 'globe' ? 'flat' : 'globe');
        setProjection(nextProj);
      } else if (e.key.toLowerCase() === 'p') {
        toggleTilt();
      } else if (e.key.toLowerCase() === 'b') {
        bootEngine.start(true);
      } else if (e.key === 'Escape') {
        if (state.isDrawingRegion) toggleDrawRegion(false);
        setPopoverExpanded(false);
        hideMilestoneToast();
        document.getElementById('modal-shortcuts')?.classList.add('hidden');
        document.getElementById('presets-menu')?.classList.add('hidden');
      } else if (e.key === '?') {
        document.getElementById('modal-shortcuts')?.classList.remove('hidden');
      }
    });
  }

  // --- Main Application Lifecycle Entry ---
  async function init() {
    setupListeners();
    renderVariablePicker();
    bootEngine.start();
    initCharts();

    await initMap();
    updateLooksUI();

    // Initialize projection UI state
    setProjection(state.projection, false);

    const hash = window.location.hash;
    const hasAppliedCustomHash = parseAndApplyHash(hash);

    await loadVariable(state.currentVarId);
    const varData = state.cache[state.currentVarId];
    updateGridLayer(varData);

    if (hasAppliedCustomHash) {
      setSelectionMode(state.selectionMode);
      setPeriodRange(state.startYear, state.endYear);
      handleSeasonPreset(state.seasonFilter);
      if (state.selectionMode === 'point') {
        dropPinMarker(state.currentPin.lat, state.currentPin.lon);
      } else {
        updateRegionGeoJson();
      }
      updateInspector();
    } else {
      dropPinMarker(state.currentPin.lat, state.currentPin.lon);
      updateInspector(state.cellIndex.latIdx, state.cellIndex.lonIdx);
    }
  }

  function selectPoint(lat, lon) {
    const snap = snapCoordsToGrid(lat, lon);
    state.cellIndex = snap;
    state.currentPin = { lat: snap.snappedLat, lon: snap.snappedLon };
    if (state.selectionMode !== 'point') {
      setSelectionMode('point');
    }
    dropPinMarker(snap.snappedLat, snap.snappedLon);
    recordAnalysisChoice();
    updateInspector(snap.latIdx, snap.lonIdx);
  }

  // Expose for testing & telemetry inspection
  window.appState = state;
  window.kendall = {
    state,
    bootEngine,
    replayBoot: () => bootEngine.start(true),
    skipBoot: () => bootEngine.finish(true),
    setProjection,
    toggleTilt,
    dropPinMarker,
    selectPoint,
    updateInspector,
    snapCoordsToGrid,
    switchVariable,
    setSelectionMode,
    applyPreset,
    toggleDrawRegion,
    setPeriodRange,
    handleSeasonPreset,
    computeRegionalTimeSeries,
    computeFullStats,
    getShareableHash,
    parseAndApplyHash,
    recordAnalysisChoice,
    resetAnalysisCounter,
    updateLooksUI,
    setPopoverExpanded,
    showMilestoneToast,
    hideMilestoneToast,
    triggeredMilestones,
    getMultipleTestingNoticeText,
    resetInactivityTimer,
  };

  window.addEventListener('DOMContentLoaded', init);
})();
