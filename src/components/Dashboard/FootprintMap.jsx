import React, { useEffect, useRef, useMemo, useState, useCallback } from 'react';
import { MapContainer, TileLayer, Rectangle, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { api } from '../../api/client';
import { Layers, Eye, EyeOff } from 'lucide-react';
import proj4 from 'proj4';

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
    highlight: { fill: '#f59e0b', stroke: '#d97706', label: '하이라이트' },
};

// COG Layer component - loads orthoimages using georaster-layer-for-leaflet
export function CogLayer({ projectId, visible = true, opacity = 0.8 }) {
    const map = useMap();
    const layerRef = useRef(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

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

            try {
                // Get COG URL from backend
                const cogInfo = await api.getCogUrl(projectId);

                // Then import georaster libraries
                const [GeoRasterModule, GeoRasterLayerModule] = await Promise.all([
                    import('georaster'),
                    import('georaster-layer-for-leaflet')
                ]);

                const parseGeoraster = GeoRasterModule.default;
                const GeoRasterLayer = GeoRasterLayerModule.default;

                // Fetch the GeoTIFF and parse it
                const response = await fetch(cogInfo.url, {
                    headers: cogInfo.local ? {
                        'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                    } : {}
                });

                if (!response.ok) {
                    throw new Error(`Failed to fetch COG: ${response.status}`);
                }

                const arrayBuffer = await response.arrayBuffer();
                console.log('[COG] Downloaded', arrayBuffer.byteLength, 'bytes');

                // Disable web workers to use window.proj4 in main thread
                // (proj4 function cannot be cloned for web worker transfer)
                const georaster = await parseGeoraster(arrayBuffer, {
                    useWebWorker: false
                });
                console.log('[COG] Parsed georaster:', {
                    width: georaster.width,
                    height: georaster.height,
                    xmin: georaster.xmin,
                    ymin: georaster.ymin,
                    xmax: georaster.xmax,
                    ymax: georaster.ymax
                });

                // Create layer
                const layer = new GeoRasterLayer({
                    georaster,
                    opacity,
                    resolution: 256,
                });

                // Remove old layer if exists
                if (layerRef.current) {
                    map.removeLayer(layerRef.current);
                }

                // Add new layer
                layer.addTo(map);
                layerRef.current = layer;

                // Invalidate map size to fix gray area on resize
                setTimeout(() => map.invalidateSize(), 100);

            } catch (err) {
                console.error('Failed to load COG:', err);
                setError(err.message);
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
// Map resize handler - invalidates map size when container height changes
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
 * Footprint Map Component
 * Shows real map with project footprints as colored rectangles
 */
export function FootprintMap({ projects = [], height = 400, onProjectClick, highlightProjectId = null, selectedProjectId = null }) {
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

    // Selected project for COG overlay (highlighted or selected, if completed)
    const activeProjectId = highlightProjectId || selectedProjectId;
    const selectedCogProject = activeProjectId
        ? footprints.find(fp => fp.id === activeProjectId && fp.status === 'completed')
        : null;

    return (
        <div className={`bg-white rounded-xl shadow-sm border border-slate-100 overflow-hidden ${isFlexHeight ? 'flex flex-col h-full' : ''}`}>
            <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between shrink-0">
                <div>
                    <h3 className="text-sm font-bold text-slate-700">대한민국 전역 처리 현황</h3>
                    <p className="text-xs text-slate-400 mt-0.5">배경지도 및 정사영상 오버레이</p>
                </div>

                {/* Layer Controls */}
                <div className="flex items-center gap-4">
                    {/* COG Opacity Control - shown when a completed project is selected */}
                    {selectedCogProject && (
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-blue-600 font-medium">정사영상 로딩중</span>
                            <div className="flex items-center gap-1.5">
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
                        </div>
                    )}

                    {/* Legend */}
                    <div className="flex gap-3 text-xs">
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
                >
                    <TileLayer
                        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />

                    {/* Handle map resize when height changes */}
                    <MapResizeHandler height={height} />

                    {allPoints.length > 0 && !highlightFootprint && !selectedFootprint && <MapBoundsFitter bounds={allPoints} />}
                    {highlightFootprint && <HighlightFlyTo footprint={highlightFootprint} />}

                    {/* COG Overlay Layer - auto-loaded for selected completed project */}
                    {selectedCogProject && (
                        <CogLayer
                            projectId={selectedCogProject.id}
                            visible={true}
                            opacity={cogOpacity}
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

