import React, { useEffect, useState, useRef, useCallback } from 'react';
import L from 'leaflet';
import { Rectangle, Tooltip, useMap } from 'react-leaflet';
import api from '../../api/client';

// 축척별 최소 줌 레벨 (이 줌 이상이어야 도엽 로드)
const MIN_ZOOM_FOR_SCALE = {
    1000: 14,
    5000: 12,
    25000: 9,
    50000: 7,
};

/**
 * 도엽 격자 오버레이 컴포넌트
 * - projectBounds가 있으면 프로젝트 범위 기준으로 도엽 로드
 * - projectBounds가 없으면 현재 지도 뷰포트 기준으로 도엽 로드 (pan/zoom 시 갱신)
 * - 줌 레벨이 부족하면 로드하지 않고 메시지 표시
 * - 지도 클릭 이벤트를 직접 캐치하여 도엽 선택/해제
 */
export default function SheetGridOverlay({ visible, scale, projectBounds, selectedSheets, onToggleSheet, onSheetsLoaded, pane }) {
    const map = useMap();
    const [sheets, setSheets] = useState([]);
    const [loading, setLoading] = useState(false);
    const [truncated, setTruncated] = useState(false);
    const [needsZoom, setNeedsZoom] = useState(false);
    const debounceRef = useRef(null);
    const lastBoundsKeyRef = useRef(null);
    const sheetsRef = useRef([]);

    // sheetsRef를 최신 상태로 유지
    useEffect(() => {
        sheetsRef.current = sheets;
    }, [sheets]);

    const fetchSheets = useCallback((bounds) => {
        const boundsKey = `${scale}-${bounds.minlat.toFixed(4)}-${bounds.minlon.toFixed(4)}-${bounds.maxlat.toFixed(4)}-${bounds.maxlon.toFixed(4)}`;
        if (lastBoundsKeyRef.current === boundsKey) return;
        lastBoundsKeyRef.current = boundsKey;

        setLoading(true);
        setTruncated(false);
        api.getSheets(scale, bounds)
            .then(data => {
                setSheets(data.sheets || []);
                setTruncated(data.truncated || false);
                if (onSheetsLoaded) onSheetsLoaded(data.sheets || []);
            })
            .catch(err => {
                console.error('Failed to load sheets:', err);
                setSheets([]);
            })
            .finally(() => setLoading(false));
    }, [scale, onSheetsLoaded]);

    // 프로젝트 bounds가 있으면 그걸로 도엽 조회 (줌 제한 없음)
    useEffect(() => {
        if (!visible || !projectBounds || projectBounds.length < 2) return;
        setNeedsZoom(false);

        const lats = projectBounds.map(p => p[0]);
        const lons = projectBounds.map(p => p[1]);
        fetchSheets({
            minlat: Math.min(...lats),
            minlon: Math.min(...lons),
            maxlat: Math.max(...lats),
            maxlon: Math.max(...lons),
        });
    }, [visible, scale, projectBounds, fetchSheets]);

    // 프로젝트 bounds가 없으면 지도 뷰포트 기준으로 도엽 조회 (줌 제한 적용)
    useEffect(() => {
        if (!visible || (projectBounds && projectBounds.length >= 2)) return;

        const minZoom = MIN_ZOOM_FOR_SCALE[scale] || 10;

        const loadFromViewport = () => {
            const currentZoom = map.getZoom();
            if (currentZoom < minZoom) {
                setNeedsZoom(true);
                setSheets([]);
                lastBoundsKeyRef.current = null;
                if (onSheetsLoaded) onSheetsLoaded([]);
                return;
            }
            setNeedsZoom(false);

            const b = map.getBounds();
            fetchSheets({
                minlat: b.getSouth(),
                minlon: b.getWest(),
                maxlat: b.getNorth(),
                maxlon: b.getEast(),
            });
        };

        // 초기 로드
        loadFromViewport();

        // pan/zoom 시 디바운스하여 갱신
        const onMoveEnd = () => {
            if (debounceRef.current) clearTimeout(debounceRef.current);
            debounceRef.current = setTimeout(loadFromViewport, 500);
        };

        map.on('moveend', onMoveEnd);
        return () => {
            map.off('moveend', onMoveEnd);
            if (debounceRef.current) clearTimeout(debounceRef.current);
        };
    }, [visible, scale, projectBounds, map, fetchSheets, onSheetsLoaded]);

    // 지도 클릭 이벤트로 도엽 선택 (Canvas 렌더러 우회)
    useEffect(() => {
        if (!visible || !onToggleSheet) return;

        const handleMapClick = (e) => {
            const latlng = e.latlng;
            const currentSheets = sheetsRef.current;
            if (!currentSheets.length) return;

            // 클릭 지점이 어떤 도엽 bounds 안에 있는지 확인
            for (const sheet of currentSheets) {
                const sw = L.latLng(sheet.bounds_wgs84[0][0], sheet.bounds_wgs84[0][1]);
                const ne = L.latLng(sheet.bounds_wgs84[1][0], sheet.bounds_wgs84[1][1]);
                const sheetBounds = L.latLngBounds(sw, ne);

                if (sheetBounds.contains(latlng)) {
                    onToggleSheet(sheet.mapid);
                    return;
                }
            }
        };

        map.on('click', handleMapClick);
        return () => {
            map.off('click', handleMapClick);
        };
    }, [visible, map, onToggleSheet]);

    // visible이 꺼지면 초기화
    useEffect(() => {
        if (!visible) {
            setSheets([]);
            setNeedsZoom(false);
            setTruncated(false);
            lastBoundsKeyRef.current = null;
        }
    }, [visible]);

    if (!visible) return null;

    // 줌인 필요 메시지
    if (needsZoom) {
        const minZoom = MIN_ZOOM_FOR_SCALE[scale] || 10;
        return (
            <div className="leaflet-top leaflet-left" style={{ top: '50px', left: '50%', transform: 'translateX(-50%)', position: 'absolute', zIndex: 1000 }}>
                <div className="bg-amber-50 border border-amber-300 text-amber-800 px-3 py-2 rounded-lg shadow-md text-xs font-medium pointer-events-none">
                    1:{scale.toLocaleString()} 도엽을 보려면 줌 레벨 {minZoom} 이상으로 확대하세요
                </div>
            </div>
        );
    }

    if (sheets.length === 0) return null;

    return (
        <>
            {truncated && (
                <div className="leaflet-top leaflet-left" style={{ top: '50px', left: '50%', transform: 'translateX(-50%)', position: 'absolute', zIndex: 1000 }}>
                    <div className="bg-amber-50 border border-amber-300 text-amber-800 px-3 py-2 rounded-lg shadow-md text-xs font-medium pointer-events-none">
                        도엽이 너무 많습니다 (200개 제한). 더 확대하세요.
                    </div>
                </div>
            )}
            {sheets.map(sheet => {
                const isSelected = selectedSheets.includes(sheet.mapid);
                const bounds = [
                    [sheet.bounds_wgs84[0][0], sheet.bounds_wgs84[0][1]],
                    [sheet.bounds_wgs84[1][0], sheet.bounds_wgs84[1][1]],
                ];
                return (
                    <Rectangle
                        key={sheet.mapid}
                        bounds={bounds}
                        pane={pane}
                        pathOptions={{
                            color: isSelected ? '#2563eb' : '#f59e0b',
                            weight: isSelected ? 3 : 1.5,
                            fillColor: isSelected ? '#3b82f6' : '#f59e0b',
                            fillOpacity: isSelected ? 0.15 : 0.01,
                            dashArray: isSelected ? null : '6 4',
                            interactive: false,
                        }}
                    >
                        <Tooltip sticky direction="center" className="sheet-label">
                            <span className="text-[10px] font-mono font-bold">{sheet.mapid}</span>
                            {sheet.name && <span className="text-[10px] text-slate-500 ml-1">({sheet.name})</span>}
                        </Tooltip>
                    </Rectangle>
                );
            })}
        </>
    );
}
