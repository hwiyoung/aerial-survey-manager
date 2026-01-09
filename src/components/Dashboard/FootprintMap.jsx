import React, { useEffect, useRef, useMemo, useState } from 'react';
import { MapContainer, TileLayer, Rectangle, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Status colors for footprints
const STATUS_COLORS = {
    completed: { fill: '#10b981', stroke: '#059669', label: '처리 완료' },
    processing: { fill: '#3b82f6', stroke: '#2563eb', label: '진행 중' },
    pending: { fill: '#94a3b8', stroke: '#64748b', label: '대기' },
    error: { fill: '#ef4444', stroke: '#dc2626', label: '오류' },
    highlight: { fill: '#f59e0b', stroke: '#d97706', label: '하이라이트' },
};

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

/**
 * Footprint Map Component
 * Shows real map with project footprints as colored rectangles
 */
export function FootprintMap({ projects = [], height = 400, onProjectClick, highlightProjectId = null }) {
    const [highlightPulse, setHighlightPulse] = useState(false);

    // Pulse animation for highlight
    useEffect(() => {
        if (highlightProjectId) {
            const interval = setInterval(() => {
                setHighlightPulse(prev => !prev);
            }, 500);
            return () => clearInterval(interval);
        } else {
            setHighlightPulse(false);
        }
    }, [highlightProjectId]);

    // Generate mock footprints from projects
    const footprints = useMemo(() => {
        const baseLat = 36.5;
        const baseLng = 127.5;

        return projects.map((project, index) => {
            const seed = project.id ? parseInt(project.id.replace(/\D/g, '').slice(-4) || index) : index;
            const lat = baseLat + ((seed % 20) - 10) * 0.15;
            const lng = baseLng + ((seed % 15) - 7) * 0.2;
            const size = 0.05 + (seed % 5) * 0.02;

            let status = 'pending';
            if (project.status === '완료') status = 'completed';
            else if (project.status === '진행중') status = 'processing';
            else if (project.status === '오류') status = 'error';

            return {
                id: project.id,
                title: project.title,
                status,
                bounds: [
                    [lat - size, lng - size],
                    [lat + size, lng + size]
                ],
                center: { lat, lng },
                project
            };
        });
    }, [projects]);

    const highlightFootprint = highlightProjectId ? footprints.find(fp => fp.id === highlightProjectId) : null;

    // Get all bounds for auto-fit
    const allPoints = footprints.flatMap(f => [
        { lat: f.bounds[0][0], lng: f.bounds[0][1] },
        { lat: f.bounds[1][0], lng: f.bounds[1][1] }
    ]);

    const containerStyle = typeof height === 'number' ? { height } : { height, minHeight: '400px' };
    const isFlexHeight = height === '100%';

    return (
        <div className={`bg-white rounded-xl shadow-sm border border-slate-100 overflow-hidden ${isFlexHeight ? 'flex flex-col h-full' : ''}`}>
            <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between shrink-0">
                <div>
                    <h3 className="text-sm font-bold text-slate-700">대한민국 전역 처리 현황</h3>
                    <p className="text-xs text-slate-400 mt-0.5">배경지도 및 정사영상 오버레이</p>
                </div>
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

                    {allPoints.length > 0 && !highlightFootprint && <MapBoundsFitter bounds={allPoints} />}
                    {highlightFootprint && <HighlightFlyTo footprint={highlightFootprint} />}

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
                                    <div className="text-sm">
                                        <strong>{fp.title}</strong>
                                        <div className="text-xs text-slate-500 mt-1">
                                            상태: {STATUS_COLORS[fp.status].label}
                                        </div>
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
