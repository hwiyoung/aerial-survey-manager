import React, { useEffect, useRef, useMemo, useState, useCallback } from 'react';
import { MapContainer, TileLayer, Rectangle, Popup, Tooltip, useMap, GeoJSON, ImageOverlay } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { api } from '../../api/client';
import { Layers, Eye, EyeOff, ChevronRight, X, Map as MapIcon, Grid3X3, Search, Download } from 'lucide-react';
import proj4 from 'proj4';
import { getTileConfig, MAP_CONFIG } from '../../config/mapConfig';
import SheetGridOverlay from '../Project/SheetGridOverlay';

// Set proj4 globally for georaster-layer-for-leaflet
if (typeof window !== 'undefined') {
    window.proj4 = proj4;
}

// Status colors for footprints
const STATUS_COLORS = {
    completed: { fill: '#10b981', stroke: '#059669', label: '처리 완료' },
    processing: { fill: '#3b82f6', stroke: '#2563eb', label: '진행 중' },
    pending: { fill: '#94a3b8', stroke: '#64748b', label: '대기' },
    error: { fill: '#ef4444', stroke: '#dc2626', label: '오류' },
    cancelled: { fill: '#64748b', stroke: '#475569', label: '취소됨' },
    highlight: { fill: '#f59e0b', stroke: '#d97706', label: '하이라이트' },
};

const COG_INFO_CACHE_TTL_MS = 10 * 60 * 1000; // 10m
const COG_INFO_CACHE = new Map();

const TILER_TILE_ENDPOINT = '/titiler/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png';

function buildTiTilerTileUrl(sourceUrl) {
    return `${TILER_TILE_ENDPOINT}?url=${encodeURIComponent(sourceUrl)}`;
}

function normalizeProjectBounds(projectBounds) {
    if (!Array.isArray(projectBounds) || projectBounds.length !== 2) {
        return null;
    }

    const sw = projectBounds[0];
    const ne = projectBounds[1];

    if (
        !Array.isArray(sw) ||
        !Array.isArray(ne) ||
        sw.length !== 2 ||
        ne.length !== 2
    ) {
        return null;
    }

    const southWest = [Number(sw[0]), Number(sw[1])];
    const northEast = [Number(ne[0]), Number(ne[1])];

    if (southWest.some(v => Number.isNaN(v)) || northEast.some(v => Number.isNaN(v))) {
        return null;
    }

    return [southWest, northEast];
}

function normalizeCogBounds(bounds) {
    if (!Array.isArray(bounds) || bounds.length !== 4) return null;
    const [west, south, east, north] = bounds;
    if ([west, south, east, north].some(v => typeof v !== 'number' || Number.isNaN(v))) {
        return null;
    }
    return [[south, west], [north, east]];
}

/**
 * TiTiler-based Orthophoto Tile Layer
 * Streams COG files efficiently using XYZ tiles
 */
export function TiTilerOrthoLayer({
    projectId,
    visible = true,
    opacity = 0.8,
    onLoadComplete,
    onLoadError,
    projectBounds = null,
    showBasemap,
}) {
    const map = useMap();
    const layerRef = useRef(null);
    const currentProjectIdRef = useRef(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // 베이스맵 토글 시 정사영상을 항상 최상단으로
    useEffect(() => {
        if (layerRef.current) {
            layerRef.current.bringToFront();
        }
    }, [showBasemap]);
    const [tileUrl, setTileUrl] = useState(null);
    const [bounds, setBounds] = useState(null);
    const fittedBoundsRef = useRef(null);

    useEffect(() => {
        // 이전 레이어 정리
        if (layerRef.current) {
            map.removeLayer(layerRef.current);
            layerRef.current = null;
        }

        if (!projectId || !visible) {
            setTileUrl(null);
            setBounds(null);
            currentProjectIdRef.current = null;
            return;
        }

        const overrideBounds = normalizeProjectBounds(projectBounds);

        // 현재 요청 ID 저장 (경쟁 조건 방지)
        currentProjectIdRef.current = projectId;
        console.log('[TiTiler] Starting load for project:', projectId);

        const readFromCache = () => {
            const cached = COG_INFO_CACHE.get(projectId);
            if (!cached) return null;
            if (Date.now() - cached.fetchedAt > COG_INFO_CACHE_TTL_MS) {
                COG_INFO_CACHE.delete(projectId);
                return null;
            }
            if (cached.projectId !== projectId) return null;
            return cached;
        };

        const applyCachedInfo = (cached) => {
            const boundsFromCache = overrideBounds || normalizeCogBounds(cached.bounds);
            setTileUrl(cached.tileUrl || buildTiTilerTileUrl(cached.url));
            setError(null);
            setLoading(false);
            setBounds(boundsFromCache);
            onLoadComplete?.();
        };

        const initTiTiler = async () => {
            const cached = readFromCache();
            if (cached) {
                applyCachedInfo(cached);
                return;
            }

            setLoading(true);
            setError(null);
            setTileUrl(null);
            setBounds(overrideBounds);

            let cogInfo;
            try {
                // Get COG info from backend
                cogInfo = await api.getCogUrl(projectId);
                if (currentProjectIdRef.current !== projectId) {
                    return;
                }

                const tileSourceUrl = cogInfo?.url;
                if (!tileSourceUrl) {
                    throw new Error('COG URL 응답이 비어 있습니다.');
                }

                const tiTilerUrl = buildTiTilerTileUrl(tileSourceUrl);
                let nextBounds = overrideBounds || normalizeCogBounds(cogInfo.bounds);

                // Get bounds info from TiTiler only when project bounds are not known
                if (!overrideBounds && !nextBounds) {
                    try {
                        const boundsResponse = await fetch(`/titiler/cog/bounds?url=${encodeURIComponent(tileSourceUrl)}`);
                        if (boundsResponse.ok && currentProjectIdRef.current === projectId) {
                            const boundsData = await boundsResponse.json();
                            if (boundsData?.bounds) {
                                const backendBounds = normalizeCogBounds(boundsData.bounds);
                                if (backendBounds) {
                                    console.log('[TiTiler] Bounds from service:', boundsData);
                                    nextBounds = backendBounds;
                                }
                            }
                        }
                    } catch (e) {
                        console.warn('[TiTiler] Could not get bounds:', e);
                    }
                }

                COG_INFO_CACHE.set(projectId, {
                    projectId,
                    cacheKey: cogInfo.cache_key,
                    tileUrl: tiTilerUrl,
                    url: tileSourceUrl,
                    local: cogInfo.local,
                    fileSize: cogInfo.file_size,
                    bounds: cogInfo.bounds,
                    fetchedAt: Date.now(),
                });

                setTileUrl(tiTilerUrl);
                setBounds(nextBounds);
                setLoading(false);
                onLoadComplete?.();

            } catch (err) {
                if (currentProjectIdRef.current === projectId) {
                    console.error('[TiTiler] Failed to initialize:', err);
                    setError(err.message);
                    setLoading(false);
                    onLoadError?.(err.message);
                }
            }
        };

        initTiTiler();

        return () => {
            if (layerRef.current) {
                map.removeLayer(layerRef.current);
                layerRef.current = null;
            }
        };
    }, [map, projectId, visible, projectBounds]);

    // Fit to bounds when available
    useEffect(() => {
        if (!bounds || !map) return;

        const boundsKey = JSON.stringify(bounds);
        if (fittedBoundsRef.current === boundsKey) return;

        fittedBoundsRef.current = boundsKey;
        map.fitBounds(bounds, { padding: [50, 50], maxZoom: getTileConfig().maxZoom });
    }, [bounds, map]);

    useEffect(() => {
        if (!visible) {
            fittedBoundsRef.current = null;
        }
    }, [visible]);

    if (!tileUrl || !visible) return null;

    return (
        <TileLayer
            key={`titiler-${projectId}-${tileUrl}`}
            ref={layerRef}
            url={tileUrl}
            opacity={opacity}
            tileSize={256}
            zoomOffset={0}
            maxZoom={getTileConfig().maxZoom}
            updateWhenZooming={false}
            updateWhenIdle={true}
            keepBuffer={2}
            attribution="&copy; TiTiler"
        />
    );
}

// COG Layer component - loads orthoimages using georaster-layer-for-leaflet
export function CogLayer({ projectId, visible = true, opacity = 0.8, onLoadComplete, onLoadError }) {
    const map = useMap();
    const layerRef = useRef(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [loadProgress, setLoadProgress] = useState(null);

    useEffect(() => {
        if (!projectId || !visible) {
            // Remove layer if not visible
            if (layerRef.current) {
                map.removeLayer(layerRef.current);
                layerRef.current = null;
            }
            return;
        }

        const loadCog = async () => {
            setLoading(true);
            setError(null);
            setLoadProgress('COG URL 가져오는 중...');
            let cogUrl = null;

            try {
                // Get COG URL from backend
                const cogInfo = await api.getCogUrl(projectId);
                console.log('[COG] Got URL info:', cogInfo);

                setLoadProgress('GeoRaster 라이브러리 로딩...');

                // Import georaster libraries
                const [GeoRasterModule, GeoRasterLayerModule] = await Promise.all([
                    import('georaster'),
                    import('georaster-layer-for-leaflet')
                ]);

                const parseGeoraster = GeoRasterModule.default;
                const GeoRasterLayer = GeoRasterLayerModule.default;

                // Build full URL for georaster
                // URL is absolute (s3:// or file://) — pass directly to TiTiler
                cogUrl = cogInfo.url;
                console.log('[COG] Loading from URL:', cogUrl);

                setLoadProgress('정사영상 스트리밍 중... (Range Requests)');

                // Use URL-based parsing with Range Requests (streaming)
                // This only downloads the tiles needed for current view
                const georaster = await parseGeoraster(cogUrl, {
                    useWebWorker: true,  // Offload CPU intensive parse/render setup
                });
                setLoadProgress('레이어 생성 중...');

                const createLayer = (source) => new GeoRasterLayer({
                    georaster: source,
                    opacity,
                    resolution: 256,
                    debugLevel: 0,
                });

                const layer = createLayer(georaster);

                // Fallback: if worker-based parse fails, retry on main thread.
                // This keeps rendering available even on browsers/environments with restricted workers.
                if (!layer) {
                    throw new Error('GeoRaster 레이어 생성 실패');
                }

                // Remove old layer if exists
                if (layerRef.current) {
                    map.removeLayer(layerRef.current);
                }

                // Add new layer
                layer.addTo(map);
                layerRef.current = layer;

                console.log('[COG] Layer added to map');

                // Fit map to layer bounds
                const bounds = layer.getBounds();
                if (bounds && bounds.isValid()) {
                    map.fitBounds(bounds, { padding: [50, 50], maxZoom: getTileConfig().maxZoom });
                }

                // Invalidate map size to fix gray area on resize
                setTimeout(() => map.invalidateSize(), 100);

                setLoadProgress(null);
                onLoadComplete?.();

            } catch (err) {
                const message = String(err?.message || err);
                // Worker fallback for environments where web workers are blocked/limited.
                try {
                    if (!cogUrl) {
                        throw new Error('Cog URL is missing for fallback parsing');
                    }
                    console.warn('[COG] Retrying without worker');
                    const [GeoRasterModule, GeoRasterLayerModule] = await Promise.all([
                        import('georaster'),
                        import('georaster-layer-for-leaflet')
                    ]);

                    const parseGeoraster = GeoRasterModule.default;
                    const GeoRasterLayer = GeoRasterLayerModule.default;
                    const georaster = await parseGeoraster(cogUrl, {
                        useWebWorker: false,
                    });

                    const fallbackLayer = new GeoRasterLayer({
                        georaster,
                        opacity,
                        resolution: 256,
                        debugLevel: 0,
                    });

                    if (layerRef.current) {
                        map.removeLayer(layerRef.current);
                    }
                    fallbackLayer.addTo(map);
                    layerRef.current = fallbackLayer;

                    const bounds = fallbackLayer.getBounds();
                    if (bounds && bounds.isValid()) {
                        map.fitBounds(bounds, { padding: [50, 50], maxZoom: getTileConfig().maxZoom });
                    }
                    setTimeout(() => map.invalidateSize(), 100);
                    setLoadProgress(null);
                    onLoadComplete?.();
                    setError(null);
                    return;
                } catch (fallbackErr) {
                    console.error('[COG] Fallback parsing also failed:', fallbackErr);
                }

                console.error('[COG] Failed to load:', err);
                setError(message);
                setLoadProgress(null);
                onLoadError?.(message);
            } finally {
                setLoading(false);
            }
        };

        loadCog();

        return () => {
            if (layerRef.current) {
                map.removeLayer(layerRef.current);
                layerRef.current = null;
            }
        };
    }, [map, projectId, visible]);

    // Update opacity
    useEffect(() => {
        if (layerRef.current) {
            layerRef.current.setOpacity(opacity);
        }
    }, [opacity]);

    return null;
}

const REGION_PANE = 'region-boundary';
const PROJECT_PANE = 'project-footprint';
const SHEET_PANE = 'sheet-grid';

export function MapPanes() {
    const map = useMap();

    useEffect(() => {
        if (!map) return;
        const regionPane = map.getPane(REGION_PANE) || map.createPane(REGION_PANE);
        const projectPane = map.getPane(PROJECT_PANE) || map.createPane(PROJECT_PANE);
        const sheetPane = map.getPane(SHEET_PANE) || map.createPane(SHEET_PANE);

        regionPane.style.zIndex = '2';
        projectPane.style.zIndex = '3';
        sheetPane.style.zIndex = '4';
    }, [map]);

    return null;
}

// Map bounds fitter component
function MapBoundsFitter({ bounds }) {
    const map = useMap();

    useEffect(() => {
        if (bounds && bounds.length > 0) {
            const leafletBounds = L.latLngBounds(bounds.map(b => [b.lat, b.lng]));
            map.fitBounds(leafletBounds, { padding: [50, 50], maxZoom: getTileConfig().maxZoom });
        }
    }, [map, bounds]);

    return null;
}

// Highlight flyTo component
function HighlightFlyTo({ footprint }) {
    const map = useMap();

    useEffect(() => {
        if (footprint) {
            const bounds = L.latLngBounds(footprint.bounds);
            map.flyToBounds(bounds, { padding: [100, 100], duration: 1, maxZoom: getTileConfig().maxZoom });
        }
    }, [map, footprint]);

    return null;
}

// Map reset controller - resets to default Korea view when resetKey changes
function MapResetController({ resetKey }) {
    const map = useMap();
    const prevResetKeyRef = useRef(resetKey);

    useEffect(() => {
        if (resetKey !== prevResetKeyRef.current) {
            prevResetKeyRef.current = resetKey;
            map.setView(MAP_CONFIG.defaultCenter, MAP_CONFIG.defaultZoom, { animate: true, duration: 0.5 });
        }
    }, [map, resetKey]);

    return null;
}
function MapResizeHandler({ height }) {
    const map = useMap();

    useEffect(() => {
        // Invalidate size after a short delay to allow container to resize
        const timer = setTimeout(() => {
            map.invalidateSize();
        }, 100);
        return () => clearTimeout(timer);
    }, [map, height]);

    return null;
}

/**
 * Region Boundary Layer
 * Displays administrative region boundaries on the map from PostGIS
 * hoveredProjectId가 있으면 툴팁을 숨김 (프로젝트 바운딩박스 우선)
 */
export function RegionBoundaryLayer({ visible = true, onRegionClick, activeRegion = null, interactive = true, footprints = [], hoveredProjectId = null }) {
    const [geojsonData, setGeojsonData] = useState(null);
    const [loading, setLoading] = useState(false);
    const layersRef = useRef([]); // 모든 레이어 참조 저장

    // hoveredProjectId가 설정되면 모든 권역 툴팁 닫기
    useEffect(() => {
        if (hoveredProjectId && layersRef.current.length > 0) {
            layersRef.current.forEach(layer => {
                if (layer && layer.closeTooltip) {
                    layer.closeTooltip();
                }
            });
        }
    }, [hoveredProjectId]);

    // GeoJSON이 다시 생성될 때 레이어 참조 초기화
    useEffect(() => {
        layersRef.current = [];
    }, [geojsonData, footprints.length]);

    // 인접 권역끼리 색상 계열이 겹치지 않도록 배치
    // 수도권(파랑,초록) / 강원(연두) / 충청(노랑) / 전라(청록,빨강) / 경상(보라,주황)
    const LAYER_COLORS = {
        '수도권북부 권역': '#2563eb', // Blue 600
        '수도권남부 권역': '#059669', // Emerald 600
        '강원 권역': '#65a30d',      // Lime 600
        '충청 권역': '#d97706',      // Amber 600
        '전라동부 권역': '#0891b2',   // Cyan 600
        '전라서부 권역': '#dc2626',   // Red 600
        '경북 권역': '#7c3aed',      // Violet 600
        '경남 권역': '#ea580c',      // Orange 600
        'Unknown': '#64748b'
    };

    const getLayerColor = (layer) => {
        // Debug fallback: Bright magenta if color not found
        return LAYER_COLORS[layer] || '#ff00ff';
    };

    useEffect(() => {
        if (!visible || geojsonData) return;

        const fetchBoundaries = async () => {
            setLoading(true);
            try {
                const response = await api.request('/regions/boundaries');
                setGeojsonData(response);
            } catch (err) {
                console.error('Failed to fetch regional boundaries:', err);
            } finally {
                setLoading(false);
            }
        };

        fetchBoundaries();
    }, [visible, geojsonData]);

    if (!visible || !geojsonData) return null;

    const regionStyle = (feature) => {
        const isActive = activeRegion === feature.properties.layer || activeRegion === feature.id;
        const color = getLayerColor(feature.properties.layer);

        return {
            fillColor: color,
            fillOpacity: 0, // Fully transparent fill
            color: color,
            weight: isActive ? 3 : 2,
            opacity: 0.85,
            interactive: interactive,
            fill: false,
        };
    };

    const onEachFeature = (feature, layer) => {
        const label = feature.properties.layer || '알 수 없는 구역';

        // 레이어 참조 저장 (툴팁 제어용)
        layersRef.current.push(layer);

        // 권역 툴팁 바인딩 (프로젝트 호버 시 숨김)
        layer.bindTooltip(`${label}`, {
            permanent: false,
            direction: 'center',
            sticky: true,
            className: 'region-tooltip font-bold text-[10px]'
        });

        layer.on({
            click: (e) => {
                // 클릭 지점에 프로젝트가 있는지 확인 (프로젝트 우선)
                const clickPoint = e.latlng;
                const hasProjectAtPoint = footprints.some(f => {
                    if (!f.bounds) return false;
                    const bounds = L.latLngBounds(f.bounds);
                    return bounds.contains(clickPoint);
                });

                // 프로젝트가 있으면 권역 클릭 무시 (프로젝트 우선 선택)
                if (hasProjectAtPoint) {
                    return;
                }

                L.DomEvent.stopPropagation(e);
                if (onRegionClick) {
                    onRegionClick(feature.id, feature.properties.layer);
                }
            },
            mouseover: (e) => {
                // 마우스 위치에 프로젝트가 있으면 권역 툴팁 숨김
                const mousePoint = e.latlng;
                const hasProjectAtMouse = footprints.some(f => {
                    if (!f.bounds) return false;
                    const bounds = L.latLngBounds(f.bounds);
                    return bounds.contains(mousePoint);
                });

                if (hasProjectAtMouse) {
                    layer.closeTooltip();
                    return; // 스타일 변경도 하지 않음
                }

                const layer_target = e.target;
                layer_target.setStyle({
                    fillOpacity: 0,
                    weight: 3,
                    opacity: 0.9
                });
            },
            mouseout: (e) => {
                const layer_target = e.target;
                layer_target.setStyle(regionStyle(feature));
            },
            // 툴팁이 열리기 전에 체크
            tooltipopen: (e) => {
                // 마우스 위치에 프로젝트가 있으면 툴팁 즉시 닫기
                const map = e.target._map;
                if (map) {
                    const mousePoint = map.mouseEventToLatLng(e.originalEvent || { clientX: 0, clientY: 0 });
                    const hasProjectAtMouse = footprints.some(f => {
                        if (!f.bounds) return false;
                        const bounds = L.latLngBounds(f.bounds);
                        return bounds.contains(mousePoint);
                    });
                    if (hasProjectAtMouse) {
                        layer.closeTooltip();
                    }
                }
            }
        });
    };

    return (
        <GeoJSON
            key={`region-layer-${footprints.length}`}
            data={geojsonData}
            style={regionStyle}
            onEachFeature={onEachFeature}
            interactive={interactive}
            pane={REGION_PANE}
        />
    );
}

/**
 * Header bar with layer controls, legend, and COG status
 */
function FootprintMapHeader({
    showRegions, onRegionToggle,
    showFootprints, onFootprintToggle,
    selectedCogProject, cogLoadStatus, cogError,
    sheetState, onSheetToggle,
}) {
    return (
        <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between shrink-0">
            <div>
                <h3 className="text-sm font-bold text-slate-700">대한민국 전역 처리 현황</h3>
                <p className="text-xs text-slate-400 mt-0.5">배경지도 및 정사영상 오버레이</p>
            </div>

            <div className="flex items-center gap-4">
                <div className="flex gap-3 text-xs">
                    <button
                        onClick={onFootprintToggle}
                        className={`flex items-center gap-1.5 px-2 py-1 rounded transition-colors ${showFootprints ? 'bg-violet-100 text-violet-700' : 'bg-slate-100 text-slate-500'}`}
                        title="촬영 영역 표시 토글"
                    >
                        {showFootprints ? <Eye size={12} /> : <EyeOff size={12} />}
                        <span>촬영 영역</span>
                    </button>
                    <button
                        onClick={onRegionToggle}
                        className={`flex items-center gap-1.5 px-2 py-1 rounded transition-colors ${showRegions ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-500'}`}
                        title="권역 경계 표시 토글"
                    >
                        <Layers size={12} />
                        <span>권역</span>
                    </button>
                    <button
                        onClick={onSheetToggle}
                        className={`flex items-center gap-1.5 px-2 py-1 rounded transition-colors ${sheetState?.visible ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-500'}`}
                        title="도엽 격자 표시 토글"
                    >
                        <Grid3X3 size={12} />
                        <span>도엽</span>
                    </button>
                    <div className="flex items-center gap-1.5">
                        <div className="w-3 h-3 rounded" style={{ backgroundColor: STATUS_COLORS.completed.fill }}></div>
                        <span className="text-slate-600">{STATUS_COLORS.completed.label}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                        <div className="w-3 h-3 rounded" style={{ backgroundColor: STATUS_COLORS.processing.fill }}></div>
                        <span className="text-slate-600">{STATUS_COLORS.processing.label}</span>
                    </div>
                </div>
            </div>
        </div>
    );
}

/**
 * Popup for selecting among overlapping projects
 */
function OverlapSelectionPopup({ overlapProjects, selectedProjectId, onProjectClick, onClose }) {
    if (!overlapProjects) return null;
    return (
        <Popup
            position={overlapProjects.latlng}
            onClose={onClose}
            minWidth={200}
            closeOnClick={false}
        >
            <div className="p-1">
                <h4 className="text-xs font-bold text-slate-500 mb-2 uppercase tracking-wider border-b pb-1">프로젝트 선택 ({overlapProjects.projects.length})</h4>
                <div className="space-y-1 max-h-48 overflow-y-auto custom-scrollbar">
                    {overlapProjects.projects.map(p => (
                        <button
                            key={p.id}
                            onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                if (onProjectClick) onProjectClick(p);
                                onClose();
                            }}
                            onMouseDown={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                            }}
                            className={`w-full text-left px-3 py-2 rounded text-sm transition-colors flex items-center justify-between group ${p.id === selectedProjectId ? 'bg-blue-50 text-blue-700' : 'hover:bg-slate-50 text-slate-700'}`}
                        >
                            <span className="truncate font-medium">{p.title}</span>
                            <ChevronRight size={14} className="opacity-0 group-hover:opacity-100 text-slate-400" />
                        </button>
                    ))}
                </div>
            </div>
        </Popup>
    );
}

/**
 * 도엽 검색 결과로 지도 이동하는 헬퍼 컴포넌트
 */
function SheetSearchFitBounds({ searchResult }) {
    const map = useMap();
    const lastMapidRef = useRef(null);
    useEffect(() => {
        if (searchResult?.found && searchResult.mapid !== lastMapidRef.current) {
            lastMapidRef.current = searchResult.mapid;
            const b = searchResult.bounds_wgs84;
            map.fitBounds([[b[0][0], b[0][1]], [b[1][0], b[1][1]]], { padding: [50, 50], maxZoom: 19 });
        }
    }, [searchResult, map]);
    return null;
}

/**
 * 도엽 컨트롤 플로팅 패널 (지도 위에 표시)
 */
function SheetControlPanel({ sheetState, onSheetStateChange, selectedProject }) {
    const [searchInput, setSearchInput] = useState('');
    const [searchResult, setSearchResult] = useState(null);
    const [isClipping, setIsClipping] = useState(false);
    // 축척 버튼을 즉시 표시 (API 응답 대기 없음), 큰 축척(넓은 영역)부터 정렬
    const [availableScales, setAvailableScales] = useState([
        { scale: 50000, label: '1:50000' },
        { scale: 25000, label: '1:25000' },
        { scale: 5000, label: '1:5000' },
        { scale: 1000, label: '1:1000' },
    ]);

    useEffect(() => {
        api.getSheetScales().then(data => {
            const scales = data.scales || [];
            if (scales.length > 0) {
                // API 응답으로 업데이트 (큰 축척(넓은 영역)부터 정렬: 50K → 25K → 5K → 1K)
                const sorted = [...scales].sort((a, b) => Number(b.scale) - Number(a.scale));
                setAvailableScales(sorted);
            }
        }).catch(() => {});
    }, []);

    const handleSearch = () => {
        if (!searchInput.trim()) return;
        api.searchSheet(searchInput.trim()).then(r => {
            setSearchResult(r);
            if (r.found) {
                onSheetStateChange?.({
                    ...sheetState,
                    visible: true,
                    scale: r.scale,
                    searchResult: r,
                    selectedSheets: [...(sheetState?.selectedSheets || []).filter(s => s !== r.mapid), r.mapid],
                });
            }
        }).catch(() => setSearchResult({ found: false }));
    };

    const handleClip = async () => {
        if (!selectedProject?.id || !sheetState?.selectedSheets?.length) return;
        setIsClipping(true);
        try {
            const result = await api.clipExport([selectedProject.id], sheetState.selectedSheets, {
                scale: sheetState.scale || 5000,
                crs: 'EPSG:5186',
                gsd: selectedProject.result_gsd || null,
            });
            api.triggerDirectDownload(result.download_id);
        } catch (err) {
            alert('도엽 클립 실패: ' + err.message);
        } finally {
            setIsClipping(false);
        }
    };

    // 좌상단→우하단 정렬: 위도 내림차순(위→아래), 같은 행이면 경도 오름차순(왼→오른)
    const overlappingSheets = [...(sheetState?.overlappingSheets || [])].sort((a, b) => {
        const aLat = a.bounds_wgs84?.[1]?.[0] ?? 0; // maxlat (북쪽)
        const bLat = b.bounds_wgs84?.[1]?.[0] ?? 0;
        const aLon = a.bounds_wgs84?.[0]?.[1] ?? 0; // minlon (서쪽)
        const bLon = b.bounds_wgs84?.[0]?.[1] ?? 0;
        if (Math.abs(aLat - bLat) > 0.0001) return bLat - aLat; // 위도 내림차순
        return aLon - bLon; // 경도 오름차순
    });
    const selectedSheets = sheetState?.selectedSheets || [];
    const hasOrtho = selectedProject?.ortho_path;

    return (
        <div className="absolute top-3 left-3 z-[1000] bg-white/95 backdrop-blur-sm rounded-xl shadow-lg border border-slate-200 w-72 max-h-[calc(100%-24px)] overflow-y-auto">
            <div className="p-3 border-b border-slate-100">
                <div className="flex items-center justify-between mb-2">
                    <h4 className="text-xs font-bold text-slate-700 flex items-center gap-1.5">
                        <Grid3X3 size={14} className="text-amber-500" />
                        도엽 격자
                    </h4>
                    <button
                        onClick={() => onSheetStateChange?.({ ...sheetState, visible: false })}
                        className="p-0.5 hover:bg-slate-100 rounded text-slate-400"
                    >
                        <X size={14} />
                    </button>
                </div>

                {/* 축척 선택 */}
                {availableScales.length > 0 && (
                    <div className="flex gap-1">
                        {availableScales.map(s => (
                            <button
                                key={s.scale}
                                onClick={() => onSheetStateChange?.({ ...sheetState, scale: s.scale, selectedSheets: [], searchResult: null })}
                                className={`text-[10px] px-2.5 py-1 rounded font-bold transition-colors ${(sheetState?.scale || 5000) === s.scale ? 'bg-amber-500 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
                            >
                                {s.label}
                            </button>
                        ))}
                    </div>
                )}
            </div>

            {/* 도엽번호 검색 */}
            <div className="p-3 border-b border-slate-100">
                <label className="text-[10px] font-bold text-slate-400 block mb-1">도엽번호 검색</label>
                <div className="flex gap-1">
                    <input
                        type="text"
                        value={searchInput}
                        onChange={e => setSearchInput(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleSearch()}
                        placeholder="예: 37806043"
                        className="flex-1 text-xs border border-slate-200 rounded px-2 py-1.5 font-mono"
                    />
                    <button
                        onClick={handleSearch}
                        className="px-2 py-1.5 bg-slate-100 hover:bg-slate-200 border border-slate-200 rounded transition-colors"
                    >
                        <Search size={14} className="text-slate-500" />
                    </button>
                </div>
                {searchResult && !searchResult.found && (
                    <p className="text-[10px] text-red-500 mt-1">도엽을 찾을 수 없습니다.</p>
                )}
                {searchResult?.found && (
                    <p className="text-[10px] text-blue-600 mt-1">{searchResult.mapid} ({searchResult.name}) - 1:{searchResult.scale.toLocaleString()}</p>
                )}
            </div>

            {/* 겹치는 도엽 목록 */}
            {overlappingSheets.length > 0 && (
                <div className="p-3 border-b border-slate-100">
                    <div className="flex items-center justify-between mb-1">
                        <label className="text-[10px] font-bold text-slate-400">
                            겹치는 도엽 ({overlappingSheets.length}개)
                        </label>
                        {selectedSheets.length === 0 && (
                            <button
                                onClick={() => onSheetStateChange?.({
                                    ...sheetState,
                                    selectedSheets: overlappingSheets.map(s => s.mapid),
                                })}
                                className="text-[10px] text-blue-600 hover:text-blue-800 font-bold"
                            >
                                전체 선택
                            </button>
                        )}
                        {selectedSheets.length > 0 && (
                            <button
                                onClick={() => onSheetStateChange?.({ ...sheetState, selectedSheets: [] })}
                                className="text-[10px] text-red-500 hover:text-red-700 font-bold"
                            >
                                전체 해제
                            </button>
                        )}
                    </div>
                    <div className="flex flex-wrap gap-1 max-h-20 overflow-y-auto">
                        {overlappingSheets.map(sheet => {
                            const isSelected = selectedSheets.includes(sheet.mapid);
                            return (
                                <span
                                    key={sheet.mapid}
                                    onClick={() => {
                                        onSheetStateChange?.({
                                            ...sheetState,
                                            selectedSheets: isSelected
                                                ? selectedSheets.filter(s => s !== sheet.mapid)
                                                : [...selectedSheets, sheet.mapid],
                                        });
                                    }}
                                    className={`text-[10px] px-1.5 py-0.5 rounded font-mono cursor-pointer transition-colors select-none ${isSelected ? 'bg-blue-100 text-blue-700 border border-blue-300' : 'bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100'}`}
                                    title={isSelected ? '클릭하여 선택 해제' : '클릭하여 선택'}
                                >
                                    {sheet.mapid}
                                </span>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* 선택된 도엽 + 내보내기 버튼 */}
            {selectedSheets.length > 0 && (
                <div className="p-3">
                    <label className="text-[10px] font-bold text-slate-400 block mb-1">
                        선택된 도엽 ({selectedSheets.length}개)
                    </label>
                    <div className="flex flex-wrap gap-1 mb-3">
                        {selectedSheets.map(sid => (
                            <span
                                key={sid}
                                className="text-[10px] px-1.5 py-0.5 bg-blue-50 text-blue-700 border border-blue-200 rounded font-mono cursor-pointer hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-colors select-none"
                                onClick={() => onSheetStateChange?.({ ...sheetState, selectedSheets: selectedSheets.filter(s => s !== sid) })}
                                title="클릭하여 선택 해제"
                            >
                                {sid} ×
                            </span>
                        ))}
                    </div>

                    {!hasOrtho && (
                        <p className="text-[10px] text-amber-600 bg-amber-50 border border-amber-200 rounded px-2 py-1 mb-2">
                            정사영상(COG)이 없어 내보내기가 불가합니다.
                        </p>
                    )}

                    <button
                        onClick={handleClip}
                        disabled={isClipping || !hasOrtho}
                        className="w-full flex items-center justify-center gap-1.5 py-2 text-[11px] font-bold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-50"
                    >
                        <Download size={13} />
                        {isClipping ? '클립 중...' : `클립 (${selectedSheets.length})`}
                    </button>
                </div>
            )}
        </div>
    );
}

/**
 * Footprint Map Component
 * Shows real map with project footprints as colored rectangles
 */
export function FootprintMap({
    projects = [],
    height = 400,
    onProjectClick,
    highlightProjectId = null,
    selectedProjectId = null,
    onRegionClick,
    activeRegionName = 'ALL',
    resetKey = 0,
    sheetState = null,
    sheetProjectBounds = null,
    onSheetToggle = null,
    onSheetsLoaded = null,
    onSheetStateChange = null,
    selectedProject = null,
}) {
    const [highlightPulse, setHighlightPulse] = useState(false);
    const blinkCountRef = useRef(0);
    const [overlapProjects, setOverlapProjects] = useState(null); // { projects, latlng }
    const [hoveredProjectId, setHoveredProjectId] = useState(null); // 호버 중인 프로젝트 ID

    // Pulse animation for highlight - exactly 4 blinks
    useEffect(() => {
        if (highlightProjectId) {
            blinkCountRef.current = 0;
            const interval = setInterval(() => {
                setHighlightPulse(prev => !prev);
                blinkCountRef.current += 1;
                // 8 toggles = 4 full blinks
                if (blinkCountRef.current >= 8) {
                    clearInterval(interval);
                    setHighlightPulse(false);
                }
            }, 250); // 250ms for faster blinking
            return () => clearInterval(interval);
        } else {
            setHighlightPulse(false);
            blinkCountRef.current = 0;
        }
    }, [highlightProjectId]);

    // Generate footprints from projects - using real data from backend
    const footprints = useMemo(() => {
        return projects.map((project, index) => {
            let status = 'pending';
            const projectStatus = (project.status || '').toLowerCase();
            if (projectStatus === 'completed' || project.status === '완료') status = 'completed';
            else if (projectStatus === 'processing' || project.status === '진행중') status = 'processing';
            else if (projectStatus === 'error' || projectStatus === 'failed' || project.status === '오류') status = 'error';

            // Use real bounds from project if available
            // project.bounds is expected to be a list of [lat, lng] points
            if (project.bounds && project.bounds.length >= 2) {
                // Leaflet Rectangle needs [[lat, lng], [lat, lng]]
                // We'll calculate the envelope from the points
                const lats = project.bounds.map(p => p[0]);
                const lngs = project.bounds.map(p => p[1]);
                const bounds = [
                    [Math.min(...lats), Math.min(...lngs)],
                    [Math.max(...lats), Math.max(...lngs)]
                ];

                return {
                    id: project.id,
                    title: project.title,
                    status,
                    bounds: bounds,
                    center: { lat: (bounds[0][0] + bounds[1][0]) / 2, lng: (bounds[0][1] + bounds[1][1]) / 2 },
                    project
                };
            }

            // If no bounds, don't show on map
            return null;
        }).filter(Boolean);
    }, [projects]);

    // For flyTo: use highlightProjectId first (for animation), then selectedProjectId (for persistence)
    const highlightFootprint = highlightProjectId
        ? footprints.find(fp => fp.id === highlightProjectId)
        : null;

    // For persistent zoom: use selected project when no highlight animation
    const selectedFootprint = selectedProjectId
        ? footprints.find(fp => fp.id === selectedProjectId)
        : null;

    // Get all bounds for auto-fit
    const allPoints = footprints.flatMap(f => [
        { lat: f.bounds[0][0], lng: f.bounds[0][1] },
        { lat: f.bounds[1][0], lng: f.bounds[1][1] }
    ]);

    const containerStyle = typeof height === 'number' ? { height } : { height, minHeight: '400px' };
    const isFlexHeight = height === '100%';

    // COG overlay - show for highlighted OR selected completed project
    const [cogLoadStatus, setCogLoadStatus] = useState(null); // 'loading' | 'loaded' | 'error'
    const [cogError, setCogError] = useState(null);
    const [cogDismissedProjectId, setCogDismissedProjectId] = useState(null); // user explicitly closed overlay

    // Region layer visibility
    const [showRegions, setShowRegions] = useState(true);
    const [showFootprints, setShowFootprints] = useState(true);

    // Basemap visibility (persisted in localStorage)
    const [showBasemap, setShowBasemap] = useState(() => {
        const saved = localStorage.getItem('basemap_visible');
        return saved === null ? true : saved === 'true';
    });
    const toggleBasemap = useCallback(() => {
        setShowBasemap(prev => {
            const next = !prev;
            localStorage.setItem('basemap_visible', String(next));
            return next;
        });
    }, []);

    // Footprint (bounding box) opacity control
    const [footprintOpacity, setFootprintOpacity] = useState(0.5);

    // COG (orthophoto) opacity control
    const [cogOpacity, setCogOpacity] = useState(1.0);

    // Selected project for COG overlay (highlighted or selected, if completed)
    const activeProjectId = highlightProjectId || selectedProjectId;
    const selectedCogProject = (activeProjectId && activeProjectId !== cogDismissedProjectId)
        ? footprints.find(fp => fp.id === activeProjectId && fp.status === 'completed')
        : null;

    // Stabilize bounds reference to prevent TiTilerOrthoLayer useEffect re-fires
    // on every periodic refresh (projects re-fetch → footprints recompute → new bounds array)
    const cogBoundsKey = selectedCogProject ? JSON.stringify(selectedCogProject.bounds) : null;
    const stableCogBounds = useMemo(
        () => selectedCogProject?.bounds || null,
        [cogBoundsKey]
    );

    useEffect(() => {
        if (!showFootprints) {
            setHoveredProjectId(null);
            setOverlapProjects(null);
        }
    }, [showFootprints]);

    // Reset COG status when selected project changes
    useEffect(() => {
        if (selectedCogProject) {
            setCogLoadStatus('loading');
            setCogError(null);
        } else {
            setCogLoadStatus(null);
            setCogError(null);
        }
    }, [selectedCogProject?.id]);

    // Reset COG dismissal when the active project changes
    useEffect(() => {
        setCogDismissedProjectId(null);
    }, [activeProjectId]);

    // COG load handlers
    const handleCogLoadComplete = useCallback(() => {
        setCogLoadStatus('loaded');
    }, []);

    const handleCogLoadError = useCallback((error) => {
        setCogLoadStatus('error');
        setCogError(error);
    }, []);

    return (
        <div className={`bg-white rounded-xl shadow-sm border border-slate-100 overflow-hidden ${isFlexHeight ? 'flex flex-col h-full' : ''}`}>
            <FootprintMapHeader
                showRegions={showRegions}
                showFootprints={showFootprints}
                onFootprintToggle={() => {
                    const willShow = !showFootprints;
                    setShowFootprints(willShow);
                    if (willShow && onSheetStateChange) {
                        onSheetStateChange({ ...sheetState, visible: false });
                    }
                }}
                selectedCogProject={selectedCogProject}
                cogLoadStatus={cogLoadStatus} cogError={cogError}
                sheetState={sheetState}
                onRegionToggle={() => {
                    const willShow = !showRegions;
                    setShowRegions(willShow);
                    if (willShow && onSheetStateChange) {
                        onSheetStateChange({ ...sheetState, visible: false });
                    }
                }}
                onSheetToggle={() => {
                    if (onSheetStateChange) {
                        const willShow = !sheetState?.visible;
                        onSheetStateChange({ ...sheetState, visible: willShow });
                        if (willShow) setShowFootprints(false);
                    }
                }}
            />

            <div className={`${isFlexHeight ? 'flex-1' : ''} ${hoveredProjectId ? 'project-hovered' : ''}`} style={{ ...(isFlexHeight ? { minHeight: '300px' } : containerStyle), isolation: 'isolate', position: 'relative', zIndex: 0, overflow: 'hidden' }}>
                <MapContainer
                    center={MAP_CONFIG.defaultCenter}
                    zoom={MAP_CONFIG.defaultZoom}
                    maxZoom={getTileConfig().maxZoom}
                    minZoom={MAP_CONFIG.minZoom}
                    style={{ height: '100%', width: '100%' }}
                    zoomControl={true}
                    preferCanvas={true}
                >
                    <MapPanes />
                    <MapResetController resetKey={resetKey} />



                    {/* 베이스맵 타일 레이어 - 오프라인/온라인 설정 기반 */}
                    {showBasemap && (() => {
                        const tileConfig = getTileConfig();
                        return (
                            <TileLayer
                                attribution={tileConfig.attribution}
                                url={tileConfig.url}
                                {...(tileConfig.subdomains ? { subdomains: tileConfig.subdomains } : {})}
                                maxNativeZoom={tileConfig.maxNativeZoom}
                                maxZoom={tileConfig.maxZoom}
                                minZoom={MAP_CONFIG.minZoom}
                            />
                        );
                    })()}

                    {/* Handle map resize when height changes */}
                    <MapResizeHandler height={height} />

                    {/* Region Boundary Layer - 프로젝트 호버 시 툴팁 숨김 */}
                    <RegionBoundaryLayer
                        visible={showRegions}
                        onRegionClick={onRegionClick}
                        activeRegion={activeRegionName}
                        footprints={showFootprints ? footprints : []}
                        hoveredProjectId={showFootprints ? hoveredProjectId : null}
                    />

                    {allPoints.length > 0 && !highlightFootprint && !selectedFootprint && !activeRegionName && <MapBoundsFitter bounds={allPoints} />}
                    {highlightFootprint && <HighlightFlyTo footprint={highlightFootprint} />}

                    {/* Orthophoto Tile Layer - TiTiler or Thumbnail fallback */}
                    {selectedCogProject && selectedCogProject.project.ortho_path && (
                        <TiTilerOrthoLayer
                            projectId={selectedCogProject.id}
                            visible={true}
                            opacity={cogOpacity}
                            onLoadComplete={handleCogLoadComplete}
                            onLoadError={handleCogLoadError}
                            projectBounds={stableCogBounds}
                            showBasemap={showBasemap}
                        />
                    )}
                    {selectedCogProject && !selectedCogProject.project.ortho_path && selectedCogProject.project.ortho_thumbnail_path && (
                        <ImageOverlay
                            url={`/storage/${selectedCogProject.project.ortho_thumbnail_path}`}
                            bounds={stableCogBounds}
                            opacity={cogOpacity}
                        />
                    )}

                    {showFootprints && footprints.map((fp) => {
                        const isHighlighted = fp.id === highlightProjectId;
                        const isSelected = fp.id === selectedProjectId;
                        const isHovered = fp.id === hoveredProjectId;
                        const colors = isHighlighted ? STATUS_COLORS.highlight : STATUS_COLORS[fp.status];

                        const getStrokeColor = () => {
                            if (isHighlighted) return highlightPulse ? '#fbbf24' : '#d97706';
                            if (isSelected) return '#2563eb';
                            return colors.stroke;
                        };

                        return (
                            <Rectangle
                                key={fp.id}
                                bounds={fp.bounds}
                                pane={PROJECT_PANE}
                                pathOptions={{
                                    color: getStrokeColor(),
                                    fillOpacity: 0,
                                    weight: (isHighlighted || isSelected) ? 12 : 6,
                                    bubblingMouseEvents: false,
                                }}
                                eventHandlers={{
                                    click: (e) => {
                                        // 이벤트 전파 완전 차단 (권역 레이어보다 프로젝트 우선)
                                        L.DomEvent.stopPropagation(e);
                                        L.DomEvent.preventDefault(e);

                                        // Find all other projects at this location to handle overlaps
                                        const latlng = e.latlng;
                                        const overlapping = footprints.filter(f => isNearlySameBounds(f.bounds, fp.bounds));

                                        if (overlapping.length > 1) {
                                            setOverlapProjects({
                                                projects: overlapping.map(f => f.project),
                                                latlng: latlng
                                            });
                                        } else {
                                            setOverlapProjects(null);
                                            if (onProjectClick) onProjectClick(fp.project);
                                        }
                                    },
                                    mouseover: (e) => {
                                        e.target.bringToFront();
                                    },
                                }}
                            >
                                {/* 호버 시 겹치는 모든 프로젝트 표시 */}
                                <Tooltip direction="top" offset={[0, -5]} sticky>
                                    <div className="text-xs px-1 py-0.5">
                                        {(() => {
                                            // 현재 위치에서 겹치는 모든 프로젝트 찾기
                                            const overlapping = footprints.filter(f => {
                                                if (!f.bounds || !fp.bounds) return false;
                                                return isNearlySameBounds(f.bounds, fp.bounds);
                                            });

                                            if (overlapping.length > 1) {
                                                return (
                                                    <div>
                                                        <div className="font-bold text-purple-700 mb-1">📍 {overlapping.length}개 프로젝트 경계 거의 동일</div>
                                                        {overlapping.slice(0, 5).map((f, i) => (
                                                            <div key={f.id} className={`${f.id === fp.id ? 'font-bold text-purple-600' : 'text-slate-600'}`}>
                                                                {i + 1}. {f.project.title}
                                                            </div>
                                                        ))}
                                                        {overlapping.length > 5 && <div className="text-slate-400">...외 {overlapping.length - 5}개</div>}
                                                    </div>
                                                );
                                            }
                                            return (
                                                <div>
                                                    <div className="font-bold">📍 {fp.project.title}</div>
                                                    <div className="text-[10px] text-slate-500">{fp.project.region} · {STATUS_COLORS[fp.status]?.label || fp.status}</div>
                                                </div>
                                            );
                                        })()}
                                    </div>
                                </Tooltip>
                            </Rectangle>
                        );
                    })}

                    {/* Multiple Project Selection Popup */}
                    <OverlapSelectionPopup
                        overlapProjects={overlapProjects}
                        selectedProjectId={selectedProjectId}
                        onProjectClick={onProjectClick}
                        onClose={() => setOverlapProjects(null)}
                    />

                    {/* 도엽 격자 오버레이 - 프로젝트 없어도 뷰포트 기준으로 표시 */}
                    {sheetState?.visible && (
                        <SheetGridOverlay
                            visible={true}
                            scale={sheetState.scale || 5000}
                            projectBounds={sheetProjectBounds}
                            selectedSheets={sheetState.selectedSheets || []}
                            onToggleSheet={onSheetToggle}
                            onSheetsLoaded={onSheetsLoaded}
                            pane={SHEET_PANE}
                        />
                    )}
                    {sheetState?.searchResult?.found && <SheetSearchFitBounds searchResult={sheetState.searchResult} />}
                </MapContainer>

                {/* 배경지도 토글 버튼 */}
                <button
                    onClick={toggleBasemap}
                    className={`absolute top-3 right-3 z-[1000] p-2 rounded-lg shadow-md border transition-colors ${showBasemap ? 'bg-white border-slate-200 text-emerald-600 hover:bg-emerald-50' : 'bg-slate-100 border-slate-300 text-slate-400 hover:bg-slate-200'}`}
                    title={showBasemap ? '배경지도 숨기기' : '배경지도 표시'}
                >
                    <MapIcon size={40} />
                </button>

                {/* 도엽 컨트롤 플로팅 패널 */}
                {sheetState?.visible && (
                    <SheetControlPanel
                        sheetState={sheetState}
                        onSheetStateChange={onSheetStateChange}
                        selectedProject={selectedProject}
                    />
                )}
            </div >
        </div >
    );
}

// Helper functions for bounds comparison (moved outside component)
const boundsArea = (bounds) => {
    const minLat = Math.min(bounds[0][0], bounds[1][0]);
    const maxLat = Math.max(bounds[0][0], bounds[1][0]);
    const minLng = Math.min(bounds[0][1], bounds[1][1]);
    const maxLng = Math.max(bounds[0][1], bounds[1][1]);
    return Math.max(0, maxLat - minLat) * Math.max(0, maxLng - minLng);
};

const boundsIntersectionArea = (a, b) => {
    const minLat = Math.max(Math.min(a[0][0], a[1][0]), Math.min(b[0][0], b[1][0]));
    const maxLat = Math.min(Math.max(a[0][0], a[1][0]), Math.max(b[0][0], b[1][0]));
    const minLng = Math.max(Math.min(a[0][1], a[1][1]), Math.min(b[0][1], b[1][1]));
    const maxLng = Math.min(Math.max(a[0][1], a[1][1]), Math.max(b[0][1], b[1][1]));
    const h = Math.max(0, maxLat - minLat);
    const w = Math.max(0, maxLng - minLng);
    return h * w;
};

const isNearlySameBounds = (a, b) => {
    const areaA = boundsArea(a);
    const areaB = boundsArea(b);
    if (areaA === 0 || areaB === 0) return false;
    const inter = boundsIntersectionArea(a, b);
    const union = areaA + areaB - inter;
    const iou = union > 0 ? inter / union : 0;
    const areaRatio = Math.min(areaA, areaB) / Math.max(areaA, areaB);
    return iou >= 0.9 && areaRatio >= 0.95;
};

export default FootprintMap;
