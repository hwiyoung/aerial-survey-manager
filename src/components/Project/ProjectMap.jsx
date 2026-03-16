import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip, useMap, ImageOverlay } from 'react-leaflet';
import L from 'leaflet';
import { Loader2, Camera, Layers, X, Map as MapIcon, Crosshair } from 'lucide-react';
import { TiTilerOrthoLayer, RegionBoundaryLayer, MapPanes } from '../Dashboard/FootprintMap';
import { getTileConfig, MAP_CONFIG } from '../../config/mapConfig';

function FitBounds({ images, projectBounds, projectId, maxZoom }) {
    const map = useMap();
    const fittedProjectRef = React.useRef(null);

    useEffect(() => {
        // projectId별 1회만 fitBounds 실행 (사용자 패닝 보호)
        if (fittedProjectRef.current === projectId) return;

        // 1순위: 이미지 EO 좌표로 줌인
        if (images && images.length > 0) {
            const bounds = L.latLngBounds(images.map(img => [img.wy, img.wx]));
            if (bounds.isValid()) {
                map.fitBounds(bounds, { padding: [50, 50], maxZoom: maxZoom || 18 });
                fittedProjectRef.current = projectId;
                return;
            }
        }
        // 2순위: 프로젝트 bounds(polygon 좌표)로 줌인
        if (projectBounds && projectBounds.length > 0) {
            const bounds = L.latLngBounds(projectBounds);
            if (bounds.isValid()) {
                map.fitBounds(bounds, { padding: [50, 50], maxZoom: maxZoom || 18 });
                fittedProjectRef.current = projectId;
            }
        }
    }, [images, projectBounds, map, projectId, maxZoom]);
    return null;
}

// MapContainer 내부에서 map 인스턴스를 ref에 저장
function MapRefSetter({ mapRef }) {
    const map = useMap();
    React.useEffect(() => { mapRef.current = map; }, [map, mapRef]);
    return null;
}

export default function ProjectMap({ project, isProcessingMode, selectedImageId, onSelectImage }) {
    const [isLoading, setIsLoading] = useState(false);
    const mapRef = React.useRef(null);

    // Basemap visibility (persisted in localStorage, shared with FootprintMap)
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

    useEffect(() => {
        if ((project?.status === '완료' || project?.status === 'completed') && project?.ortho_path) {
            setIsLoading(true);
        } else {
            setIsLoading(false);
        }
    }, [project?.id, project?.ortho_path]);

    const images = useMemo(() => {
        if (!project?.images) return [];
        return project.images.filter(img => img.hasEo);
    }, [project]);

    const selectedImage = useMemo(() => {
        if (!selectedImageId || !project?.images) return null;
        return project.images.find(img => img.id === selectedImageId);
    }, [selectedImageId, project]);

    if (!project) return (
        <div className="w-full h-full flex flex-col items-center justify-center bg-slate-100 map-grid text-slate-400">
            <div className="bg-white p-6 rounded-xl shadow-sm text-center">
                <Layers size={48} className="mx-auto mb-4 text-slate-300" />
                <p className="text-lg font-medium text-slate-600">프로젝트를 선택하세요</p>
            </div>
        </div>
    );

    const tileConfig = getTileConfig();

    return (
        <div className="w-full h-full relative bg-slate-200" style={{ isolation: 'isolate', zIndex: 0 }}>
            <MapContainer
                center={MAP_CONFIG.defaultCenter}
                zoom={MAP_CONFIG.defaultZoom}
                maxZoom={tileConfig.maxZoom}
                minZoom={MAP_CONFIG.minZoom}
                style={{ height: '100%', width: '100%', background: '#f1f5f9' }}
                zoomControl={false}
            >
                <MapPanes />
                <MapRefSetter mapRef={mapRef} />
                {showBasemap && (
                    <TileLayer
                        attribution={tileConfig.attribution}
                        url={tileConfig.url}
                        {...(tileConfig.subdomains ? { subdomains: tileConfig.subdomains } : {})}
                        maxZoom={tileConfig.maxZoom}
                        minZoom={MAP_CONFIG.minZoom}
                    />
                )}

                {(project?.status === '완료' || project?.status === 'completed') && project?.ortho_path && (
                    <TiTilerOrthoLayer
                        projectId={project.id}
                        visible={true}
                        opacity={1.0}
                        onLoadComplete={() => setIsLoading(false)}
                        onLoadError={() => setIsLoading(false)}
                        showBasemap={showBasemap}
                    />
                )}
                {(project?.status === '완료' || project?.status === 'completed') && !project?.ortho_path && project?.ortho_thumbnail_path && project?.bounds && (
                    <ImageOverlay
                        url={`/storage/${project.ortho_thumbnail_path}`}
                        bounds={project.bounds.length >= 2 ? [
                            [Math.min(...project.bounds.map(p => p[0])), Math.min(...project.bounds.map(p => p[1]))],
                            [Math.max(...project.bounds.map(p => p[0])), Math.max(...project.bounds.map(p => p[1]))]
                        ] : project.bounds}
                        opacity={1.0}
                    />
                )}

                <RegionBoundaryLayer visible={true} interactive={!isProcessingMode} />

                {(images.length > 0 || project?.bounds) && <FitBounds images={images} projectBounds={project?.bounds} projectId={project?.id} maxZoom={tileConfig.maxZoom} />}

                {images.map(img => (
                    <CircleMarker
                        key={img.id}
                        center={[img.wy, img.wx]}
                        radius={isProcessingMode ? 8 : (img.id === selectedImageId ? 16 : 12)}
                        pathOptions={{
                            color: img.id === selectedImageId ? '#7c3aed' : (isProcessingMode ? '#ea580c' : '#dc2626'),
                            fillColor: img.id === selectedImageId ? '#a78bfa' : (isProcessingMode ? '#fb923c' : '#ef4444'),
                            fillOpacity: 0.9,
                            weight: 4
                        }}
                        eventHandlers={{
                            click: (e) => {
                                L.DomEvent.stopPropagation(e);
                                onSelectImage(img.id);
                            }
                        }}
                    >
                        <Tooltip direction="top" offset={[0, -10]} opacity={0.95}>
                            <div className="text-xs">
                                <strong className="block mb-1">{img.name}</strong>
                                <div className="text-slate-500">
                                    {img.wy?.toFixed(4)}, {img.wx?.toFixed(4)}
                                    {img.z != null && ` · ${parseFloat(img.z).toFixed(0)}m`}
                                </div>
                            </div>
                        </Tooltip>
                        <Popup minWidth={260} maxWidth={320} closeOnClick={false}>
                            <div className="p-1">
                                <div className="w-full h-28 bg-slate-100 rounded-lg mb-2 flex items-center justify-center overflow-hidden border border-slate-200 relative">
                                    {img.thumbnail_url ? (
                                        <>
                                            <img
                                                src={img.thumbnail_url}
                                                alt={img.name}
                                                className="w-full h-full object-cover"
                                                onError={(e) => {
                                                    // 이미지 로드 실패 시 폴백 표시
                                                    e.target.style.display = 'none';
                                                    if (e.target.nextSibling) {
                                                        e.target.nextSibling.style.display = 'flex';
                                                    }
                                                }}
                                            />
                                            <div className="absolute inset-0 text-slate-400 text-xs flex-col items-center justify-center gap-1 hidden">
                                                <Camera size={24} className="text-slate-300" />
                                                <span>미리보기 로드 실패</span>
                                            </div>
                                        </>
                                    ) : (
                                        <div className="text-slate-400 text-xs flex flex-col items-center gap-1">
                                            <Camera size={24} className="text-slate-300" />
                                            <span>미리보기 없음</span>
                                        </div>
                                    )}
                                </div>
                                <strong className="block text-sm text-slate-800 mb-2 truncate" title={img.name}>{img.name}</strong>
                                <div className="grid grid-cols-3 gap-1.5 text-xs border-t border-slate-200 pt-2 mb-2">
                                    <div className="text-center bg-slate-50 rounded p-1.5">
                                        <span className="text-slate-400 block text-[10px]">Lat</span>
                                        <span className="font-mono font-medium text-slate-700">{img.wy?.toFixed(6) || '-'}</span>
                                    </div>
                                    <div className="text-center bg-slate-50 rounded p-1.5">
                                        <span className="text-slate-400 block text-[10px]">Lon</span>
                                        <span className="font-mono font-medium text-slate-700">{img.wx?.toFixed(6) || '-'}</span>
                                    </div>
                                    <div className="text-center bg-slate-50 rounded p-1.5">
                                        <span className="text-slate-400 block text-[10px]">Alt</span>
                                        <span className="font-mono font-medium text-slate-700">{img.z != null ? `${parseFloat(img.z).toFixed(1)}m` : '-'}</span>
                                    </div>
                                </div>
                                <div className="grid grid-cols-3 gap-1.5 text-xs border-t border-slate-200 pt-2">
                                    <div className="text-center bg-slate-50 rounded p-1.5">
                                        <span className="text-slate-400 block text-[10px]">Omega (ω)</span>
                                        <span className="font-mono font-medium text-slate-700">{img.omega != null ? parseFloat(img.omega).toFixed(4) : '0.0000'}</span>
                                    </div>
                                    <div className="text-center bg-slate-50 rounded p-1.5">
                                        <span className="text-slate-400 block text-[10px]">Phi (φ)</span>
                                        <span className="font-mono font-medium text-slate-700">{img.phi != null ? parseFloat(img.phi).toFixed(4) : '0.0000'}</span>
                                    </div>
                                    <div className="text-center bg-slate-50 rounded p-1.5">
                                        <span className="text-slate-400 block text-[10px]">Kappa (κ)</span>
                                        <span className="font-mono font-medium text-slate-700">{img.kappa != null ? parseFloat(img.kappa).toFixed(4) : '0.0000'}</span>
                                    </div>
                                </div>
                            </div>
                        </Popup>
                    </CircleMarker>
                ))}
            </MapContainer>

            {/* 우측 상단 플로팅 버튼 그룹 */}
            <div className="absolute top-3 right-3 z-[1000] flex flex-col gap-2">
                {/* 배경지도 토글 버튼 */}
                <button
                    onClick={toggleBasemap}
                    className={`p-2 rounded-lg shadow-md border transition-colors ${showBasemap ? 'bg-white border-slate-200 text-emerald-600 hover:bg-emerald-50' : 'bg-slate-100 border-slate-300 text-slate-400 hover:bg-slate-200'}`}
                    title={showBasemap ? '배경지도 숨기기' : '배경지도 표시'}
                >
                    <MapIcon size={40} />
                </button>
                {/* 원래 범위로 복귀 버튼 */}
                <button
                    onClick={() => {
                        const map = mapRef.current;
                        if (!map) return;
                        if (images && images.length > 0) {
                            const bounds = L.latLngBounds(images.map(img => [img.wy, img.wx]));
                            if (bounds.isValid()) {
                                map.fitBounds(bounds, { padding: [50, 50], maxZoom: tileConfig.maxZoom });
                                return;
                            }
                        }
                        if (project?.bounds && project.bounds.length > 0) {
                            const bounds = L.latLngBounds(project.bounds);
                            if (bounds.isValid()) {
                                map.fitBounds(bounds, { padding: [50, 50], maxZoom: tileConfig.maxZoom });
                            }
                        }
                    }}
                    className="p-2 rounded-lg shadow-md border bg-white border-slate-200 text-blue-600 hover:bg-blue-50 transition-colors"
                    title="원래 범위로 돌아가기"
                >
                    <Crosshair size={40} />
                </button>
            </div>

            {isLoading && (
                <div className="absolute inset-0 flex items-center justify-center bg-white/40 backdrop-blur-[1px] z-[1001] pointer-events-none">
                    <div className="bg-white/80 p-4 rounded-xl shadow-lg border border-slate-200 flex flex-col items-center gap-2 animate-in zoom-in-95">
                        <Loader2 size={24} className="animate-spin text-blue-600" />
                        <span className="text-xs font-bold text-slate-600">지도 로딩 중...</span>
                    </div>
                </div>
            )}

            {images.length === 0 && project.images?.length > 0 && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/50 z-[1000] pointer-events-none">
                    <div className="bg-white p-4 rounded shadow text-slate-700 font-bold">
                        EO 데이터가 없어 지도에 표시할 수 없습니다.
                    </div>
                </div>
            )}

            {selectedImageId && selectedImage && (
                <div className="absolute bottom-4 left-4 right-4 bg-white border-2 border-slate-300 shadow-xl rounded-xl z-[1000]">
                    <div className="flex items-stretch gap-4 p-3 max-h-40">
                        <div className="w-32 h-32 flex-shrink-0 rounded-lg overflow-hidden border border-slate-200 bg-slate-100 flex items-center justify-center">
                            {selectedImage.thumbnail_url ? (
                                <img src={selectedImage.thumbnail_url} alt={selectedImage.name} className="w-full h-full object-cover" />
                            ) : (
                                <div className="text-center text-slate-400 p-2">
                                    <Camera size={32} className="mx-auto mb-1 text-slate-300" />
                                    <span className="text-xs">미리보기 없음</span>
                                </div>
                            )}
                        </div>

                        <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between mb-2">
                                <h4 className="font-bold text-slate-800 truncate" title={selectedImage.name}>{selectedImage.name}</h4>
                                <button
                                    onClick={() => onSelectImage(null)}
                                    className="p-1 hover:bg-slate-100 rounded text-slate-400 hover:text-slate-600"
                                >
                                    <X size={16} />
                                </button>
                            </div>

                            <div className="grid grid-cols-4 lg:grid-cols-7 gap-2 text-xs">
                                <div className="flex flex-col min-w-0">
                                    <span className="text-[10px] text-slate-400 truncate">위도 (Lat)</span>
                                    <span className="font-mono text-slate-700 truncate text-[11px]">{selectedImage.wy?.toFixed(6) || '-'}</span>
                                </div>
                                <div className="flex flex-col min-w-0">
                                    <span className="text-[10px] text-slate-400 truncate">경도 (Lon)</span>
                                    <span className="font-mono text-slate-700 truncate text-[11px]">{selectedImage.wx?.toFixed(6) || '-'}</span>
                                </div>
                                <div className="flex flex-col min-w-0">
                                    <span className="text-[10px] text-slate-400 truncate">고도 (Alt)</span>
                                    <span className="font-mono text-slate-700 truncate text-[11px]">{selectedImage.z != null ? `${parseFloat(selectedImage.z).toFixed(1)}m` : '-'}</span>
                                </div>
                                <div className="flex flex-col min-w-0">
                                    <span className="text-[10px] text-slate-400 truncate">파일 크기</span>
                                    <span className="font-mono text-slate-700 truncate text-[11px]">{selectedImage.file_size ? `${(selectedImage.file_size / 1024 / 1024).toFixed(1)}MB` : '-'}</span>
                                </div>
                                <div className="flex flex-col min-w-0">
                                    <span className="text-[10px] text-slate-400 truncate">Omega (ω)</span>
                                    <span className="font-mono text-slate-700 truncate text-[11px]">{selectedImage.omega != null ? parseFloat(selectedImage.omega).toFixed(4) : '0.0000'}</span>
                                </div>
                                <div className="flex flex-col min-w-0">
                                    <span className="text-[10px] text-slate-400 truncate">Phi (φ)</span>
                                    <span className="font-mono text-slate-700 truncate text-[11px]">{selectedImage.phi != null ? parseFloat(selectedImage.phi).toFixed(4) : '0.0000'}</span>
                                </div>
                                <div className="flex flex-col min-w-0">
                                    <span className="text-[10px] text-slate-400 truncate">Kappa (κ)</span>
                                    <span className="font-mono text-slate-700 truncate text-[11px]">{selectedImage.kappa != null ? parseFloat(selectedImage.kappa).toFixed(4) : '0.0000'}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
