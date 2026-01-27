import React, { useEffect, useRef, useMemo, useState, useCallback } from 'react';
import { MapContainer, TileLayer, Rectangle, Popup, useMap, GeoJSON } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { api } from '../../api/client';
import { Layers, Eye, EyeOff } from 'lucide-react';
import proj4 from 'proj4';
import KOREA_REGIONS from '../../data/koreaRegions';

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

/**
 * TiTiler-based Orthophoto Tile Layer
 * Streams COG files efficiently using XYZ tiles
 */
export function TiTilerOrthoLayer({ projectId, visible = true, opacity = 0.8, onLoadComplete, onLoadError }) {
    const map = useMap();
    const layerRef = useRef(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [tileUrl, setTileUrl] = useState(null);
    const [bounds, setBounds] = useState(null);

    useEffect(() => {
        if (!projectId || !visible) {
            if (layerRef.current) {
                map.removeLayer(layerRef.current);
                layerRef.current = null;
            }
            setTileUrl(null);
            return;
        }

        const initTiTiler = async () => {
            setLoading(true);
            setError(null);

            try {
                // Get COG info from backend
                const cogInfo = await api.getCogUrl(projectId);
                console.log('[TiTiler] COG info:', cogInfo);

                // Build TiTiler tile URL
                // For MinIO: use internal S3 URL via TiTiler
                let cogUrl = cogInfo.url;

                // If it's a local file, we need to use the full URL
                if (cogInfo.local) {
                    cogUrl = `${window.location.origin}${cogInfo.url}`;
                }

                // TiTiler XYZ tile endpoint
                const tiTilerUrl = `/titiler/cog/tiles/WebMercatorQuad/{z}/{x}/{y}@2x.png?url=${encodeURIComponent(cogUrl)}`;
                console.log('[TiTiler] Tile URL template:', tiTilerUrl);

                setTileUrl(tiTilerUrl);

                // Get bounds info from TiTiler
                try {
                    const boundsResponse = await fetch(`/titiler/cog/bounds?url=${encodeURIComponent(cogUrl)}`);
                    if (boundsResponse.ok) {
                        const boundsData = await boundsResponse.json();
                        console.log('[TiTiler] Bounds:', boundsData);
                        if (boundsData.bounds) {
                            const [west, south, east, north] = boundsData.bounds;
                            setBounds([[south, west], [north, east]]);
                        }
                    }
                } catch (e) {
                    console.warn('[TiTiler] Could not get bounds:', e);
                }

                setLoading(false);
                onLoadComplete?.();

            } catch (err) {
                console.error('[TiTiler] Failed to initialize:', err);
                setError(err.message);
                setLoading(false);
                onLoadError?.(err.message);
            }
        };

        initTiTiler();

        return () => {
            if (layerRef.current) {
                map.removeLayer(layerRef.current);
                layerRef.current = null;
            }
        };
    }, [map, projectId, visible]);

    // Fit to bounds when available
    useEffect(() => {
        if (bounds && map) {
            map.fitBounds(bounds, { padding: [50, 50] });
        }
    }, [bounds, map]);

    if (!tileUrl || !visible) return null;

    return (
        <TileLayer
            ref={layerRef}
            url={tileUrl}
            opacity={opacity}
            tileSize={512}
            zoomOffset={-1}
            maxZoom={22}
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
                let cogUrl = cogInfo.url;
                if (cogInfo.local) {
                    // For local files, build absolute URL with auth header support
                    cogUrl = `${window.location.origin}${cogInfo.url}`;
                }
                console.log('[COG] Loading from URL:', cogUrl);

                setLoadProgress('정사영상 스트리밍 중... (Range Requests)');

                // Use URL-based parsing with Range Requests (streaming)
                // This only downloads the tiles needed for current view
                const georaster = await parseGeoraster(cogUrl, {
                    useWebWorker: false,  // Use main thread with window.proj4
                });

                console.log('[COG] Parsed georaster:', {
                    width: georaster.width,
                    height: georaster.height,
                    xmin: georaster.xmin,
                    ymin: georaster.ymin,
                    xmax: georaster.xmax,
                    ymax: georaster.ymax,
                    projection: georaster.projection
                });

                setLoadProgress('레이어 생성 중...');

                // Create layer with optimized settings
                const layer = new GeoRasterLayer({
                    georaster,
                    opacity,
                    resolution: 512,  // Higher resolution for better quality
                    debugLevel: 0,
                });

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
                    map.fitBounds(bounds, { padding: [50, 50] });
                }

                // Invalidate map size to fix gray area on resize
                setTimeout(() => map.invalidateSize(), 100);

                setLoadProgress(null);
                onLoadComplete?.();

            } catch (err) {
                console.error('[COG] Failed to load:', err);
                setError(err.message);
                setLoadProgress(null);
                onLoadError?.(err.message);
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

// Map bounds fitter component
function MapBoundsFitter({ bounds }) {
    const map = useMap();

    useEffect(() => {
        if (bounds && bounds.length > 0) {
            const leafletBounds = L.latLngBounds(bounds.map(b => [b.lat, b.lng]));
            map.fitBounds(leafletBounds, { padding: [50, 50] });
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
            map.flyToBounds(bounds, { padding: [100, 100], duration: 1 });
        }
    }, [map, footprint]);

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
 * Displays administrative region boundaries on the map
 */
/**
 * Region Boundary Layer
 * Displays administrative region boundaries on the map from PostGIS
 */
export function RegionBoundaryLayer({ visible = true, onRegionClick, activeRegion = null }) {
    const [geojsonData, setGeojsonData] = useState(null);
    const [loading, setLoading] = useState(false);

    const LAYER_COLORS = {
        '강원 권역': '#2563eb',      // Blue 600
        '충청 권역': '#d97706',      // Amber 600
        '전라동부 권역': '#7c3aed',   // Violet 600
        '전라서부 권역': '#9333ea',   // Purple 600
        '경북 권역': '#dc2626',      // Red 600
        '경남 권역': '#e11d48',      // Rose 600
        '수도권남부 권역': '#0284c7', // Sky 600
        '수도권북부 권역': '#059669', // Emerald 600
        '제주 권역': '#db2777',      // Pink 600
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
        const isActive = activeRegion === feature.properties.name || activeRegion === feature.id;
        const color = getLayerColor(feature.properties.layer);

        return {
            fillColor: color,
            fillOpacity: isActive ? 0.1 : 0.03, // Further reduced from 0.05
            color: color,
            weight: isActive ? 2 : 0.5, // Thinner lines
            opacity: 0.2,
            interactive: false, // This is key for performance and avoiding click blockage
        };
    };

    const onEachFeature = (feature, layer) => {
        const label = feature.properties.name || '알 수 없는 구역';

        // Tooltip can still work if needed, but let's keep it simple
        layer.bindTooltip(`${label}`, {
            permanent: false,
            direction: 'center',
            sticky: true,
            className: 'region-tooltip font-bold text-[10px]'
        });

        layer.on({
            mouseover: (e) => {
                // Manually trigger style change on hover even if interactive is false? 
                // Wait, if interactive is false, mouse events won't fire.
                // Let's keep interactive: true but make sure it doesn't block.
            },
        });
    };

    return (
        <GeoJSON
            data={geojsonData}
            style={regionStyle}
            onEachFeature={onEachFeature}
            interactive={false} // Global override to ensure zero click interference
        />
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
    activeRegionName = 'ALL'
}) {
    const [highlightPulse, setHighlightPulse] = useState(false);
    const blinkCountRef = useRef(0);

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
    const [cogOpacity, setCogOpacity] = useState(0.8);
    const [cogLoadStatus, setCogLoadStatus] = useState(null); // 'loading' | 'loaded' | 'error'
    const [cogError, setCogError] = useState(null);

    // Region layer visibility
    const [showRegions, setShowRegions] = useState(true);

    // Selected project for COG overlay (highlighted or selected, if completed)
    const activeProjectId = highlightProjectId || selectedProjectId;
    const selectedCogProject = activeProjectId
        ? footprints.find(fp => fp.id === activeProjectId && fp.status === 'completed')
        : null;

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
            <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between shrink-0">
                <div>
                    <h3 className="text-sm font-bold text-slate-700">대한민국 전역 처리 현황</h3>
                    <p className="text-xs text-slate-400 mt-0.5">배경지도 및 정사영상 오버레이</p>
                </div>

                {/* Layer Controls */}
                <div className="flex items-center gap-4">
                    {/* COG Status and Opacity Control */}
                    {selectedCogProject && (
                        <div className="flex items-center gap-2">
                            {/* Status indicator */}
                            {cogLoadStatus === 'loading' && (
                                <span className="text-xs text-blue-600 font-medium flex items-center gap-1">
                                    <span className="animate-pulse">●</span> 정사영상 로딩중...
                                </span>
                            )}
                            {cogLoadStatus === 'loaded' && (
                                <span className="text-xs text-emerald-600 font-medium">✓ 정사영상 표시됨</span>
                            )}
                            {cogLoadStatus === 'error' && (
                                <span className="text-xs text-red-500 font-medium" title={cogError}>
                                    ✕ 로딩 실패
                                </span>
                            )}

                            {/* Opacity control - only show when loaded */}
                            {cogLoadStatus === 'loaded' && (
                                <div className="flex items-center gap-1.5 ml-2">
                                    <span className="text-xs text-slate-500">투명도</span>
                                    <input
                                        type="range"
                                        min="0"
                                        max="100"
                                        value={cogOpacity * 100}
                                        onChange={(e) => setCogOpacity(e.target.value / 100)}
                                        className="w-16 h-1 accent-blue-500"
                                    />
                                    <span className="text-xs text-slate-400 w-6">{Math.round(cogOpacity * 100)}%</span>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Legend */}
                    <div className="flex gap-3 text-xs">
                        <button
                            onClick={() => setShowRegions(!showRegions)}
                            className={`flex items-center gap-1.5 px-2 py-1 rounded transition-colors ${showRegions ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-500'}`}
                            title="권역 경계 표시 토글"
                        >
                            <Layers size={12} />
                            <span>권역</span>
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

            <div className={isFlexHeight ? 'flex-1' : ''} style={{ ...(isFlexHeight ? { minHeight: '300px' } : containerStyle), isolation: 'isolate', position: 'relative', zIndex: 0 }}>
                <MapContainer
                    center={[36.5, 127.5]}
                    zoom={7}
                    style={{ height: '100%', width: '100%' }}
                    zoomControl={true}
                    preferCanvas={true}
                >
                    {/* Central Loading Spinner */}
                    {cogLoadStatus === 'loading' && (
                        <div className="absolute inset-0 z-[1001] flex flex-col items-center justify-center bg-slate-900/10 backdrop-blur-[1px]">
                            <div className="bg-white p-6 rounded-2xl shadow-xl border border-slate-200 flex flex-col items-center gap-4 animate-in zoom-in-95 duration-200">
                                <div className="relative">
                                    <div className="w-12 h-12 border-4 border-blue-100 border-t-blue-600 rounded-full animate-spin"></div>
                                    <Layers className="absolute inset-0 m-auto text-blue-600" size={20} />
                                </div>
                                <div className="text-center">
                                    <div className="text-sm font-bold text-slate-800">정사영상 스트리밍 중</div>
                                    <div className="text-[10px] text-slate-500 mt-1">대용량 COG 데이터를 최적화하여 불러오고 있습니다.</div>
                                </div>
                            </div>
                        </div>
                    )}

                    <TileLayer
                        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />

                    {/* Handle map resize when height changes */}
                    <MapResizeHandler height={height} />

                    {/* Region Boundary Layer */}
                    <RegionBoundaryLayer
                        visible={showRegions}
                        onRegionClick={onRegionClick}
                        activeRegion={activeRegionName}
                    />

                    {allPoints.length > 0 && !highlightFootprint && !selectedFootprint && !activeRegionName && <MapBoundsFitter bounds={allPoints} />}
                    {highlightFootprint && <HighlightFlyTo footprint={highlightFootprint} />}

                    {/* Orthophoto Tile Layer - TiTiler-based for efficient streaming */}
                    {selectedCogProject && (
                        <TiTilerOrthoLayer
                            projectId={selectedCogProject.id}
                            visible={true}
                            opacity={cogOpacity}
                            onLoadComplete={handleCogLoadComplete}
                            onLoadError={handleCogLoadError}
                        />
                    )}

                    {footprints.map((fp) => {
                        const isHighlighted = fp.id === highlightProjectId;
                        const colors = isHighlighted ? STATUS_COLORS.highlight : STATUS_COLORS[fp.status];

                        return (
                            <Rectangle
                                key={fp.id}
                                bounds={fp.bounds}
                                pathOptions={{
                                    color: isHighlighted ? (highlightPulse ? '#fbbf24' : '#d97706') : colors.stroke,
                                    fillColor: isHighlighted ? (highlightPulse ? '#fde68a' : '#fbbf24') : colors.fill,
                                    fillOpacity: isHighlighted ? 0.7 : 0.5,
                                    weight: isHighlighted ? 4 : 2,
                                }}
                                eventHandlers={{
                                    click: () => onProjectClick && onProjectClick(fp.project),
                                }}
                            >
                                <Popup>
                                    <div className="text-sm min-w-[200px]">
                                        <div className="flex items-center gap-2 mb-1">
                                            <strong className="text-slate-800">{fp.title}</strong>
                                            <span className="text-[10px] px-1.5 py-0.5 bg-slate-100 text-slate-500 rounded font-mono uppercase tracking-tighter">ID: {fp.id?.slice(0, 8)}</span>
                                        </div>
                                        <div className="text-xs text-slate-500">
                                            상태: {STATUS_COLORS[fp.status].label}
                                        </div>
                                        {fp.status === 'completed' && (
                                            <div className="mt-2 px-2 py-1 bg-emerald-100 text-emerald-700 text-xs rounded text-center">
                                                정사영상 사용 가능
                                            </div>
                                        )}
                                    </div>
                                </Popup>
                            </Rectangle>
                        );
                    })}
                </MapContainer>
            </div>
        </div>
    );
}

export default FootprintMap;

