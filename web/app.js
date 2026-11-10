/**
 * Plot Twist - Planetary Multi-Decadal Trend & Era Shift Detector (2000–2025)
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
  ];

  const TOUR_CASES = [
    {
      caseNum: 'CASE 1 OF 3',
      title: 'Amazon Basin: Genuine Drought or Sensor Break?',
      lat: -3.75,
      lon: -61.25,
      varId: 'gpm_precip',
      name: 'Amazon Basin, South America',
      body: 'A steep drying trend of −9.27 mm/month/decade dominates the Amazon. Yet the trend flips from positive (+5.38 mm) under TRMM to deeply negative (−23.29 mm) under GPM across the 2014 transition. Because neither sub-period is significant alone, this highlights the challenge of separating real physical droughts (2015/16, 2023/24) from sensor discontinuities.',
    },
    {
      caseNum: 'CASE 2 OF 3',
      title: 'Sahel Corridor: The Greening Recovery Debate',
      lat: 13.75,
      lon: 13.75,
      varId: 'gpm_precip',
      name: 'Sahel Corridor, North-Central Africa',
      body: 'Rainfall in the African Sahel shows a weakly positive trend (+0.26 mm/mo/decade in IMERG, +0.48 mm in GLDAS). While popular narratives hail a full "Sahel greening recovery," the autocorrelation-aware test shows p = 0.071 (not significant at α = 0.05). Trend over 2000–2025 remains modest.',
    },
    {
      caseNum: 'CASE 3 OF 3',
      title: 'Tibetan Plateau: Intense Alpine Thermal Amplification',
      lat: 33.75,
      lon: 81.25,
      varId: 'gldas_temp',
      name: 'Tibetan Plateau / Himalayas',
      body: 'The strongest Northern Hemisphere warming hotspot in the dataset occurs across the Tibetan Plateau (+2.75°C/decade). Autocorrelation-aware p-value is 3.45e-11 and FDR q is 2.48e-10. High-elevation amplification is verified with sustained, unmistakable warming.',
    },
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
    const sp = localStorage.getItem('plottwist_projection');
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
    tourActive: false,
    tourIndex: 0,
    isSpinningIntro: true,
    isFadingGrid: false,
    isMorphing: false,
    hasInitializedProjection: false,
    lineupMode: 'monthly', // 'monthly' or 'trend'
    inspectorData: null,
    chartDates: null,
    chartSeries: null,
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
      localStorage.setItem('plottwist_projection', normType);
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

  // --- Client-Side Statistical Calculations (Sen's Slope, MK, CI) ---
  function computeClientStats(series) {
    const validSeries = [];
    const timeIndices = [];
    for (let k = 0; k < series.length; k++) {
      if (series[k] !== null && !isNaN(series[k]) && isFinite(series[k])) {
        validSeries.push(series[k]);
        timeIndices.push(k);
      }
    }

    const n = validSeries.length;
    if (n < 10) {
      return { slope: 0, p_hr: 1.0, p_plain: 1.0, ci_lower: 0, ci_upper: 0 };
    }

    // Median pairwise slope
    const slopes = [];
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        slopes.push((validSeries[j] - validSeries[i]) / (timeIndices[j] - timeIndices[i]));
      }
    }
    slopes.sort((a, b) => a - b);
    const mid = Math.floor(slopes.length / 2);
    const medianMonthlySlope = slopes.length % 2 !== 0 ? slopes[mid] : (slopes[mid - 1] + slopes[mid]) / 2;
    const slopeDecade = medianMonthlySlope * 120.0;

    // Mann-Kendall S
    let s = 0;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const diff = validSeries[j] - validSeries[i];
        if (diff > 0) s += 1;
        else if (diff < 0) s -= 1;
      }
    }

    const v0 = (n * (n - 1) * (2 * n + 5)) / 18.0;
    let z = 0;
    if (s > 0) z = (s - 1) / Math.sqrt(v0);
    else if (s < 0) z = (s + 1) / Math.sqrt(v0);

    function normCdf(val) {
      const t = 1 / (1 + 0.2316419 * Math.abs(val));
      const d = 0.3989423 * Math.exp((-val * val) / 2);
      const prob = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
      return val > 0 ? 1 - prob : prob;
    }
    const p_plain = 2 * (1 - normCdf(Math.abs(z)));

    // Lag-1 Autocorrelation correction (Hamed-Rao)
    let mean = 0;
    for (let i = 0; i < n; i++) mean += validSeries[i];
    mean /= n;

    let num = 0, den = 0;
    for (let i = 0; i < n - 1; i++) {
      num += (validSeries[i] - mean) * (validSeries[i + 1] - mean);
    }
    for (let i = 0; i < n; i++) {
      den += (validSeries[i] - mean) * (validSeries[i] - mean);
    }
    const r1 = den > 0 ? num / den : 0;
    let varFactor = 1.0;
    if (r1 > 0.05) {
      varFactor = 1 + (2 * r1) / (1 - r1);
    }
    const v_adj = v0 * varFactor;
    let z_hr = 0;
    if (s > 0) z_hr = (s - 1) / Math.sqrt(v_adj);
    else if (s < 0) z_hr = (s + 1) / Math.sqrt(v_adj);
    const p_hr = 2 * (1 - normCdf(Math.abs(z_hr)));

    // 95% Confidence Interval
    const z_alpha = 1.96;
    const c_alpha = z_alpha * Math.sqrt(v0);
    const m1 = Math.floor((slopes.length - c_alpha) / 2);
    const m2 = Math.floor((slopes.length + c_alpha) / 2);
    const ci_lower = (slopes[Math.max(0, m1)] || slopes[0]) * 120.0;
    const ci_upper = (slopes[Math.min(slopes.length - 1, m2)] || slopes[slopes.length - 1]) * 120.0;
    const std = n > 1 && den > 0 ? Math.sqrt(den / n) : 1.0;

    return { slope: slopeDecade, p_hr, p_plain, ci_lower, ci_upper, mean, std };
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

  function updateTimeSeriesChart(dates, anomalies, rollingMean, slopeDecade) {
    if (!state.charts.timeseries) return;

    const n = anomalies.length;
    const monthlySlope = slopeDecade / 120.0;
    let sumY = 0;
    for (let i = 0; i < n; i++) sumY += anomalies[i];
    const meanY = sumY / n;
    const meanX = (n - 1) / 2;
    const intercept = meanY - monthlySlope * meanX;

    const trendLine = [];
    for (let i = 0; i < n; i++) {
      trendLine.push(intercept + monthlySlope * i);
    }

    const option = {
      backgroundColor: 'transparent',
      animation: true,
      grid: { left: 45, right: 15, top: 15, bottom: 22 },
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
          interval: 59,
        },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: 'rgba(34, 211, 238, 0.10)' } },
        axisLabel: { color: '#7E91A8', fontFamily: 'IBM Plex Mono, monospace', fontSize: 9 },
      },
      series: [
        {
          name: 'Monthly Anomaly',
          type: 'line',
          data: anomalies,
          symbol: 'none',
          lineStyle: { width: 1, color: '#475569' },
          areaStyle: { color: 'rgba(71, 85, 105, 0.15)' },
          animationDuration: 800,
          animationEasing: 'cubicOut',
        },
        {
          name: '12-Mo Centered Mean',
          type: 'line',
          data: rollingMean,
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 2.2, color: '#22D3EE' },
          animationDuration: 1200,
          animationDelay: 200,
          animationEasing: 'cubicOut',
        },
        {
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
            data: [{ xAxis: '2014-01' }],
          },
        },
      ],
    };

    state.chartDates = dates;
    state.chartSeries = anomalies;
    state.charts.timeseries.setOption(option);

    if (state.currentMonthIdx != null) {
      updateTimeSeriesPlayhead(state.currentMonthIdx);
    }
  }

  // Synchronized Playhead Marker on 25-Year Trajectory
  function updateTimeSeriesPlayhead(m) {
    if (!state.charts.timeseries || !state.chartDates || !state.chartDates[m]) return;
    const dateStr = state.chartDates[m];
    const curVal = state.chartSeries && state.chartSeries[m] != null ? state.chartSeries[m] : null;

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
              formatter: () => dateStr,
              color: '#22D3EE',
              fontSize: 9,
              fontFamily: 'IBM Plex Mono, monospace',
              backgroundColor: 'rgba(7, 14, 28, 0.92)',
              borderColor: 'rgba(34, 211, 238, 0.45)',
              borderWidth: 1,
              borderRadius: 2,
              padding: [2, 4],
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
      const sub = series.slice(0, monthCutoff);
      const st = computeClientStats(sub);
      pVals.push(st.p_hr != null ? Math.min(1.0, Math.max(0.0001, st.p_hr)) : 1.0);
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

    // Stagger animation on cards
    gsap.fromTo(
      ['#verdict-card', '.chart-card', '.lineup-card'],
      { opacity: 0.5, y: 6 },
      { opacity: 1, y: 0, duration: 0.35, stagger: 0.06, ease: 'power2.out' }
    );

    const { meta, trend, anomalies } = varData;
    const slopeScale = trend.slope_scale || 1.0;
    const rawSlope = trend.slopes[latIdx][lonIdx];
    const isMasked = trend.valid[latIdx][lonIdx] !== 1 || rawSlope === -32768;

    const coordsEl = document.getElementById('inspector-coords');
    const nameEl = document.getElementById('inspector-name');
    if (coordsEl) {
      coordsEl.textContent = `LAT: ${TARGET_LATS[latIdx].toFixed(2)}°, LON: ${TARGET_LONS[lonIdx].toFixed(2)}°`;
    }

    const curLat = TARGET_LATS[latIdx];
    const curLon = TARGET_LONS[lonIdx];
    let regionName = 'Ocean / Open Water';
    if (curLat >= -15 && curLat <= 5 && curLon >= -75 && curLon <= -45) regionName = 'Amazon Basin, South America';
    else if (curLat >= 10 && curLat <= 20 && curLon >= -18 && curLon <= 35) regionName = 'Sahel Corridor, Africa';
    else if (curLat >= 28 && curLat <= 38 && curLon >= 75 && curLon <= 102) regionName = 'Tibetan Plateau / Himalayas';
    else if (Math.abs(curLat) > 60) regionName = 'Polar Ice Zone (Masked)';
    else if (trend.valid[latIdx][lonIdx] === 1) regionName = 'Terrestrial Continental Grid Cell';
    if (nameEl) nameEl.textContent = regionName;

    const cellOffset = latIdx * N_LONS + lonIdx;
    const nCells = N_LATS * N_LONS;
    const series = [];
    const dates = [];
    const comp = meta.compression || {};
    const scale = comp.anom_scale_factor || comp.scale || 0.01;
    const offset = comp.anom_offset || comp.offset || 0.0;
    const baseYear = 2000;
    const baseMonth = 6;

    for (let m = 0; m < state.totalMonths; m++) {
      const ymYear = baseYear + Math.floor((baseMonth - 1 + m) / 12);
      const ymM = ((baseMonth - 1 + m) % 12) + 1;
      const dateStr = `${ymYear}-${String(ymM).padStart(2, '0')}`;
      dates.push(dateStr);

      if (isMasked) {
        series.push(null);
      } else {
        const valIdx = m * nCells + cellOffset;
        const rawInt = anomalies[valIdx];
        series.push(rawInt === -32768 ? null : rawInt * scale + offset);
      }
    }

    const rollingMean = [];
    for (let i = 0; i < series.length; i++) {
      if (i < 5 || i >= series.length - 6 || isMasked) {
        rollingMean.push(null);
      } else {
        let sum = 0, count = 0;
        for (let k = i - 5; k <= i + 6; k++) {
          if (series[k] != null) {
            sum += series[k];
            count++;
          }
        }
        rollingMean.push(count >= 10 ? sum / count : null);
      }
    }

    if (isMasked) {
      document.getElementById('val-rate').textContent = 'MASKED';
      document.getElementById('val-unit').textContent = '';
      document.getElementById('val-phr').textContent = 'N/A';
      document.getElementById('val-pplain').textContent = 'N/A';
      document.getElementById('verdict-status-text').textContent = 'CELL MASKED (ICE / OCEAN)';
      document.getElementById('verdict-card').className = 'verdict-card state-neutral';
      document.getElementById('verdict-caution-box').classList.add('hidden');

      state.inspectorData = {
        latIdx,
        lonIdx,
        series: [],
        dates,
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

    const officialSlopeDecade = rawSlope * slopeScale;
    const p_plain = trend.p_values ? trend.p_values[latIdx][lonIdx] / 10000.0 : 0.05;
    const q_fdr = trend.q_values ? trend.q_values[latIdx][lonIdx] / 10000.0 : 0.05;
    const isSigFdr = trend.significant_fdr[latIdx][lonIdx] === 1;

    const clientStats = computeClientStats(series);
    const p_hr = clientStats.p_hr !== null ? clientStats.p_hr : p_plain;
    const ci_lower = clientStats.ci_lower;
    const ci_upper = clientStats.ci_upper;

    const rateEl = document.getElementById('val-rate');
    const unitEl = document.getElementById('val-unit');
    const phrEl = document.getElementById('val-phr');
    const pplainEl = document.getElementById('val-pplain');
    const fdrBadge = document.getElementById('verdict-fdr-badge');

    animateNumber(rateEl, officialSlopeDecade, 2, '+');
    unitEl.textContent = meta.trend_units || 'units/dec';
    animateNumber(phrEl, p_hr, 4);
    animateNumber(pplainEl, p_plain, 4);
    fdrBadge.textContent = `FDR q = ${q_fdr.toFixed(4)}`;

    const verdictCard = document.getElementById('verdict-card');
    const statusText = document.getElementById('verdict-status-text');

    if (isSigFdr) {
      verdictCard.className = 'verdict-card state-significant';
      statusText.textContent = 'SIGNIFICANT TREND (q < 0.05)';
    } else if (p_hr < 0.1 || p_plain < 0.05) {
      verdictCard.className = 'verdict-card state-trending';
      statusText.textContent = 'TRENDING (NOT YET SIGNIFICANT)';
    } else {
      verdictCard.className = 'verdict-card state-neutral';
      statusText.textContent = 'NO CLEAR TREND';
    }

    // Update Confidence Interval Range Bar with smooth tweening
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

    // Caution Alert Callout
    const cautionBox = document.getElementById('verdict-caution-box');
    const cautionText = document.getElementById('verdict-caution-text');
    const eb = meta.era_break_2014_check || {};
    const hasCaution = eb.caution === true || (eb.amazon_both_eras_sig_flip && regionName.includes('Amazon'));

    if (hasCaution && cautionBox && cautionText) {
      cautionText.textContent =
        eb.caution_note ||
        'Notice: Trend-aware test indicates a surviving 2014 era-step discontinuity. Interpret full-record trend with caution.';
      cautionBox.classList.remove('hidden');
    } else if (cautionBox) {
      cautionBox.classList.add('hidden');
    }

    state.inspectorData = {
      latIdx,
      lonIdx,
      series,
      dates,
      rollingMean,
      mean: clientStats ? clientStats.mean : 0,
      std: clientStats ? clientStats.std : 1.0,
      unit: meta.trend_units || meta.units || 'units/mo',
      isMasked: false,
    };

    updateTimeSeriesChart(dates, series, rollingMean, officialSlopeDecade);
    updateDetectabilityChart(series);
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

    const isMonthly = state.lineupMode === 'monthly' || state.viewMode === 'monthly';
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
        : 'Ranked by normalized trend strength (|slope/yr| / σ)';
    }

    const cellFlatIdx = latIdx * N_LONS + lonIdx;
    const rankings = [];

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
        const normScale = v.id.includes('temp')
          ? 2.5
          : v.id.includes('precip')
          ? 40.0
          : v.id.includes('soil')
          ? 20.0
          : v.id.includes('aod')
          ? 0.15
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
        const absNorm = Math.min(1.0, Math.abs(slope) / 5.0);
        rankings.push({
          ...v,
          strength: absNorm,
          text: (slope > 0 ? '+' : '') + slope.toFixed(2),
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

  // --- Guided Tour Engine ---
  async function launchTourStep(idx) {
    state.tourIndex = idx;
    const step = TOUR_CASES[idx];
    const tourCard = document.getElementById('tour-card');
    const stepPill = document.getElementById('tour-step-pill');
    const titleEl = document.getElementById('tour-title');
    const bodyEl = document.getElementById('tour-body');
    const dots = document.querySelectorAll('.tour-dot');

    if (stepPill) stepPill.textContent = step.caseNum;
    if (titleEl) titleEl.textContent = step.title;
    if (bodyEl) bodyEl.textContent = step.body;

    dots.forEach((d, i) => d.classList.toggle('active', i === idx));

    tourCard.classList.remove('hidden');
    gsap.fromTo(tourCard, { opacity: 0, y: 15 }, { opacity: 1, y: 0, duration: 0.4, ease: 'power2.out' });

    await switchVariable(step.varId);
    const snap = snapCoordsToGrid(step.lat, step.lon);
    state.cellIndex = snap;
    state.currentPin = { lat: snap.snappedLat, lon: snap.snappedLon };

    dropPinMarker(snap.snappedLat, snap.snappedLon);
    updateInspector(snap.latIdx, snap.lonIdx);

    if (state.map) {
      state.map.flyTo({
        center: [snap.snappedLon, snap.snappedLat],
        zoom: 3.5,
        pitch: 25,
        duration: 2000,
        essential: true,
      });
    }
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

  // --- Setup Event Listeners ---
  function setupListeners() {
    const btnStart = document.getElementById('btn-intro-start');
    if (btnStart) {
      btnStart.addEventListener('click', () => {
        state.isSpinningIntro = false;
        const intro = document.getElementById('intro-overlay');
        gsap.to(intro, {
          opacity: 0,
          scale: 1.05,
          duration: 0.6,
          ease: 'power2.inOut',
          onComplete: () => intro.classList.add('hidden'),
        });
        launchTourStep(0);
      });
    }

    const btnIntroTour = document.getElementById('btn-intro-tour');
    if (btnIntroTour) {
      btnIntroTour.addEventListener('click', () => {
        state.isSpinningIntro = false;
        document.getElementById('intro-overlay').classList.add('hidden');
        launchTourStep(0);
      });
    }

    const btnTour = document.getElementById('btn-start-tour');
    if (btnTour) {
      btnTour.addEventListener('click', () => launchTourStep(0));
    }

    const btnTourNext = document.getElementById('btn-tour-next');
    const btnTourPrev = document.getElementById('btn-tour-prev');
    const btnTourClose = document.getElementById('btn-close-tour');

    if (btnTourNext) {
      btnTourNext.addEventListener('click', () => {
        const nextIdx = (state.tourIndex + 1) % TOUR_CASES.length;
        launchTourStep(nextIdx);
      });
    }
    if (btnTourPrev) {
      btnTourPrev.addEventListener('click', () => {
        const prevIdx = (state.tourIndex - 1 + TOUR_CASES.length) % TOUR_CASES.length;
        launchTourStep(prevIdx);
      });
    }
    if (btnTourClose) {
      btnTourClose.addEventListener('click', () => {
        document.getElementById('tour-card').classList.add('hidden');
      });
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

    let pointerDownTime = 0;
    let pointerDownPos = null;
    let maxPointerDist = 0;
    let maxTouchesInGesture = 0;
    let isGestureActive = false;
    let lastGestureEndTime = 0;

    if (state.map) {
      const tooltip = document.getElementById('hover-tooltip');
      const crosshair = document.getElementById('map-crosshair');

      // Pointer down tracking to differentiate pan/tilt/rotation/pinch gestures from stationary single tap
      state.map.on('mousedown', (e) => {
        pointerDownTime = performance.now();
        pointerDownPos = { x: e.point.x, y: e.point.y };
        maxPointerDist = 0;
        maxTouchesInGesture = 1;
        isGestureActive = false;
      });

      state.map.on('touchstart', (e) => {
        pointerDownTime = performance.now();
        maxTouchesInGesture = Math.max(maxTouchesInGesture, e.touches ? e.touches.length : 1);
        maxPointerDist = 0;
        if (e.touches && e.touches.length === 1) {
          pointerDownPos = { x: e.touches[0].clientX, y: e.touches[0].clientY };
          isGestureActive = false;
        } else {
          // Multitouch gesture immediately flags active gesture
          pointerDownPos = null;
          isGestureActive = true;
        }
      });

      state.map.on('mousemove', (e) => {
        if (pointerDownPos && e.originalEvent && e.originalEvent.buttons > 0) {
          const dist = Math.hypot(e.point.x - pointerDownPos.x, e.point.y - pointerDownPos.y);
          if (dist > maxPointerDist) maxPointerDist = dist;
          if (dist >= 6) isGestureActive = true;
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

      state.map.on('touchmove', (e) => {
        if (e.touches && e.touches.length > 1) {
          maxTouchesInGesture = Math.max(maxTouchesInGesture, e.touches.length);
          isGestureActive = true;
        } else if (pointerDownPos && e.touches && e.touches.length > 0) {
          const dist = Math.hypot(e.touches[0].clientX - pointerDownPos.x, e.touches[0].clientY - pointerDownPos.y);
          if (dist > maxPointerDist) maxPointerDist = dist;
          if (dist >= 6) isGestureActive = true;
        }
      });

      state.map.on('dragstart', () => { isGestureActive = true; });
      state.map.on('rotatestart', () => { isGestureActive = true; });
      state.map.on('pitchstart', () => { isGestureActive = true; });
      state.map.on('zoomstart', () => { isGestureActive = true; });

      state.map.on('dragend', () => { lastGestureEndTime = performance.now(); });
      state.map.on('rotateend', () => { lastGestureEndTime = performance.now(); });
      state.map.on('pitchend', () => { lastGestureEndTime = performance.now(); });
      state.map.on('zoomend', () => { lastGestureEndTime = performance.now(); });

      state.map.on('mouseout', () => {
        if (tooltip) tooltip.classList.add('hidden');
        if (crosshair) crosshair.classList.add('crosshair-hidden');
      });

      // Strict stationary single-tap pin placement (< 6px movement, < 400ms duration, no multi-touch/gesture)
      state.map.on('click', (e) => {
        const now = performance.now();
        const duration = now - pointerDownTime;
        const timeSinceGesture = now - lastGestureEndTime;

        if (
          state.isMorphing ||
          isGestureActive ||
          maxTouchesInGesture > 1 ||
          maxPointerDist >= 6 ||
          duration >= 400 ||
          timeSinceGesture < 250
        ) {
          // Suppress pin placement during/after pan, pinch, twist or tilt
          isGestureActive = false;
          maxTouchesInGesture = 0;
          maxPointerDist = 0;
          return;
        }

        const snap = snapCoordsToGrid(e.lngLat.lat, e.lngLat.lng);
        state.cellIndex = snap;
        state.currentPin = { lat: snap.snappedLat, lon: snap.snappedLon };
        dropPinMarker(snap.snappedLat, snap.snappedLon);
        const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        state.map.easeTo({ center: [snap.snappedLon, snap.snappedLat], duration: prefersReduced ? 0 : 600 });
        updateInspector(snap.latIdx, snap.lonIdx);

        // Reset tracking
        maxTouchesInGesture = 0;
        maxPointerDist = 0;
        isGestureActive = false;
      });
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
        btnViewTrend.classList.add('active');
        btnViewMonthly.classList.remove('active');
        const varData = state.cache[state.currentVarId];
        if (varData) updateGridLayer(varData);
        updatePlanetaryLineup(state.cellIndex.latIdx, state.cellIndex.lonIdx, state.currentMonthIdx);
      });

      btnViewMonthly.addEventListener('click', () => {
        state.viewMode = 'monthly';
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
      } else if (e.key === '1') {
        launchTourStep(0);
      } else if (e.key === '2') {
        launchTourStep(1);
      } else if (e.key === '3') {
        launchTourStep(2);
      } else if (e.key.toLowerCase() === 't') {
        launchTourStep(0);
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
      } else if (e.key === 'Escape') {
        document.getElementById('modal-shortcuts').classList.add('hidden');
        document.getElementById('tour-card').classList.add('hidden');
      } else if (e.key === '?') {
        document.getElementById('modal-shortcuts').classList.remove('hidden');
      }
    });
  }

  // --- Main Application Lifecycle Entry ---
  async function init() {
    renderVariablePicker();
    initCharts();

    await initMap();
    setupListeners();

    // Initialize projection UI state
    setProjection(state.projection, false);

    const hash = window.location.hash;
    if (hash === '#demo-sahel') {
      state.isSpinningIntro = false;
      document.getElementById('intro-overlay').classList.add('hidden');
      await launchTourStep(1);
    } else if (hash === '#demo-tibet') {
      state.isSpinningIntro = false;
      document.getElementById('intro-overlay').classList.add('hidden');
      await launchTourStep(2);
    } else if (hash === '#demo-amazon') {
      state.isSpinningIntro = false;
      document.getElementById('intro-overlay').classList.add('hidden');
      await launchTourStep(0);
    } else {
      await loadVariable(state.currentVarId);
      const varData = state.cache[state.currentVarId];
      updateGridLayer(varData);
      dropPinMarker(state.currentPin.lat, state.currentPin.lon);
      updateInspector(state.cellIndex.latIdx, state.cellIndex.lonIdx);
    }

    // Preload remaining variables in background for instant monthly lineup & switching
    setTimeout(() => {
      VARIABLES_LIST.forEach((v) => {
        if (v.id !== state.currentVarId) {
          loadVariable(v.id).then(() => {
            if (state.lineupMode === 'monthly' || state.viewMode === 'monthly') {
              updatePlanetaryLineup(state.cellIndex.latIdx, state.cellIndex.lonIdx, state.currentMonthIdx);
            }
          }).catch(() => {});
        }
      });
    }, 600);
  }

  // Expose for testing & telemetry inspection
  window.appState = state;
  window.plotTwist = {
    state,
    setProjection,
    toggleTilt,
    dropPinMarker,
    switchVariable,
    launchTourStep,
  };

  window.addEventListener('DOMContentLoaded', init);
})();
