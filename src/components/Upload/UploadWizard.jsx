import React, { useState, useEffect, useMemo } from 'react';
import { UploadCloud, FileText, CheckCircle2, ChevronRight, ChevronLeft, AlertCircle, X, Camera, FolderOpen, Info, Trash2, Image as ImageIcon, FilePlus, ArrowRight, ArrowLeft, Table as TableIcon, RefreshCw, AlertTriangle, Pencil } from 'lucide-react';
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip, Rectangle, useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import proj4 from 'proj4';

import api from '../../api/client';
import ServerFileBrowser from './ServerFileBrowser';
import { getTileConfig, MAP_CONFIG } from '../../config/mapConfig';

const createDefaultEoConfig = () => ({
    delimiter: 'space',
    hasHeader: false,
    crs: 'TM중부 (EPSG:5186)',
    columns: { image_name: 0, x: 1, y: 2, z: 3, omega: 4, phi: 5, kappa: 6 },
});

const createDefaultCameraModel = () => ({
    name: '',
    focal_length: 80,
    sensor_width: 53.4,
    sensor_height: 40,
    pixel_size: 5.2,
    sensor_width_px: 17310,
    sensor_height_px: 11310,
    ppa_x: 0,
    ppa_y: 0,
    is_custom: true,
});

const CRS_LABEL_BY_CODE = {
    'EPSG:4326': 'WGS84 (EPSG:4326)',
    'EPSG:5179': 'UTM-K (EPSG:5179)',
    'EPSG:5185': 'TM서부 (EPSG:5185)',
    'EPSG:5186': 'TM중부 (EPSG:5186)',
    'EPSG:5187': 'TM동부 (EPSG:5187)',
    'EPSG:5188': 'TM동해 (EPSG:5188)',
};

const EO_CRS_DEFINITIONS = {
    'EPSG:4326': '+proj=longlat +datum=WGS84 +no_defs +type=crs',
    'EPSG:5179': '+proj=tmerc +lat_0=38 +lon_0=127.5 +k=0.9996 +x_0=1000000 +y_0=2000000 +ellps=GRS80 +units=m +no_defs +type=crs',
    'EPSG:5185': '+proj=tmerc +lat_0=38 +lon_0=125 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs +type=crs',
    'EPSG:5186': '+proj=tmerc +lat_0=38 +lon_0=127 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs +type=crs',
    'EPSG:5187': '+proj=tmerc +lat_0=38 +lon_0=129 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs +type=crs',
    'EPSG:5188': '+proj=tmerc +lat_0=38 +lon_0=131 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs +type=crs',
};

Object.entries(EO_CRS_DEFINITIONS).forEach(([code, definition]) => {
    if (!proj4.defs(code)) {
        proj4.defs(code, definition);
    }
});

const splitEoLine = (line, delimiter) => {
    if (delimiter === 'tab') return line.split('\t');
    if (delimiter === 'space') return line.split(/\s+/);
    return line.split(delimiter);
};

const KNOWN_EO_CRS_CODES = new Set(['4326', '5179', '5185', '5186', '5187', '5188']);

const normalizeEoCrs = (value) => {
    if (!value) return null;
    const text = String(value);
    const pattern = /(?:EPSG[:\s]*)?(\d{4,5})/gi;
    let match;
    while ((match = pattern.exec(text)) !== null) {
        const code = match[1];
        if (match[0].toLowerCase().includes('epsg') || KNOWN_EO_CRS_CODES.has(code)) {
            return `EPSG:${code}`;
        }
    }
    return null;
};

const extractRowCrs = (parts, columns) => {
    const crsColumn = columns?.crs;
    if (Number.isInteger(crsColumn) && parts[crsColumn]) {
        const normalized = normalizeEoCrs(parts[crsColumn]);
        if (normalized) return normalized;
    }

    const usedIndices = new Set(
        Object.values(columns || {}).filter((idx) => Number.isInteger(idx))
    );
    for (let idx = 0; idx < parts.length; idx += 1) {
        if (usedIndices.has(idx)) continue;
        const normalized = normalizeEoCrs(parts[idx]);
        if (normalized) return normalized;
    }
    return null;
};

const collectEffectiveEoCrs = (contents, config) => {
    const fallbackCrs = normalizeEoCrs(config?.crs) || config?.crs || 'EPSG:5186';
    const values = new Set();

    contents.forEach((item) => {
        let skipNextDataLine = Boolean(config?.hasHeader);
        let currentCrs = null;

        String(item.content || '').split('\n').forEach((rawLine) => {
            const line = rawLine.trim();
            if (!line) return;

            const lineCrs = normalizeEoCrs(line);
            if (line.startsWith('#') || line.startsWith('//')) {
                if (lineCrs) currentCrs = lineCrs;
                return;
            }

            if (skipNextDataLine) {
                skipNextDataLine = false;
                return;
            }

            let parts = splitEoLine(line, config?.delimiter || 'space');
            parts = parts.map((part) => part.trim()).filter(Boolean);
            const maxColumn = Math.max(...Object.values(config?.columns || {}).filter((idx) => Number.isInteger(idx)), 0);
            if (parts.length <= maxColumn) return;

            values.add(extractRowCrs(parts, config?.columns) || currentCrs || fallbackCrs);
        });
    });

    return Array.from(values).filter(Boolean).sort();
};

const normalizeEoImageKey = (imageName) => {
    const basename = String(imageName || '').trim().split(/[\\/]/).pop() || '';
    return basename.replace(/\.[^.]+$/, '').toLowerCase();
};

const buildImageKeySetFromPaths = (filePaths = []) => (
    new Set(
        (filePaths || [])
            .map((filePath) => normalizeEoImageKey(filePath))
            .filter(Boolean)
    )
);

const filterRowsBySelectedImages = (rows, selectedImageKeys) => {
    if (!selectedImageKeys || selectedImageKeys.size === 0) return rows;
    return rows.filter((row) => row.imageKey && selectedImageKeys.has(row.imageKey));
};

const parseEoRowsForContent = (item, config) => {
    const rows = [];
    const columns = config?.columns || {};
    const fallbackCrs = normalizeEoCrs(config?.crs) || config?.crs || 'EPSG:5186';
    const sourceKey = item.path || item.filename || 'manual';
    const sourceName = item.filename || sourceKey;
    let skipNextDataLine = Boolean(config?.hasHeader);
    let currentCrs = null;

    String(item.content || '').split('\n').forEach((rawLine) => {
        const line = rawLine.trim();
        if (!line) return;

        const lineCrs = normalizeEoCrs(line);
        if (line.startsWith('#') || line.startsWith('//')) {
            if (lineCrs) currentCrs = lineCrs;
            return;
        }

        if (skipNextDataLine) {
            skipNextDataLine = false;
            return;
        }

        let parts = splitEoLine(line, config?.delimiter || 'space');
        parts = parts.map((part) => part.trim()).filter((part) => part !== '');
        const columnValues = Object.values(columns).filter((idx) => Number.isInteger(idx));
        const maxColumn = Math.max(...columnValues, 0);
        if (parts.length <= maxColumn) return;

        const imageName = parts[columns.image_name] || '';
        if (!imageName) return;

        rows.push({
            sourceKey,
            sourceName,
            sourcePath: item.path || '',
            imageName,
            imageKey: normalizeEoImageKey(imageName),
            crs: extractRowCrs(parts, columns) || currentCrs || fallbackCrs,
            parts,
        });
    });

    return rows;
};

const findDuplicateEoImages = (rows) => {
    const byImage = new Map();
    rows.forEach((row) => {
        if (!row.imageKey) return;
        if (!byImage.has(row.imageKey)) byImage.set(row.imageKey, []);
        byImage.get(row.imageKey).push(row);
    });

    return Array.from(byImage.values())
        .filter((items) => items.length > 1)
        .map((items) => ({
            imageName: items[0].imageName,
            count: items.length,
            files: Array.from(new Set(items.map((item) => item.sourceName))).sort(),
        }))
        .sort((a, b) => a.imageName.localeCompare(b.imageName));
};

const getEoNumber = (row, columns, field) => {
    const columnIndex = columns?.[field];
    if (!Number.isInteger(columnIndex)) return NaN;
    return Number(String(row.parts?.[columnIndex] ?? '').replace(/,/g, ''));
};

const inferEoCrsFromRows = (rows, columns) => {
    const samples = rows
        .slice(0, 500)
        .map((row) => ({
            x: getEoNumber(row, columns, 'x'),
            y: getEoNumber(row, columns, 'y'),
        }))
        .filter(({ x, y }) => Number.isFinite(x) && Number.isFinite(y));

    if (samples.length === 0) return null;

    const lonLatLike = samples.filter(({ x, y }) => (
        x >= 120 && x <= 135 && y >= 30 && y <= 45
    )).length;

    return lonLatLike / samples.length >= 0.8 ? 'EPSG:4326' : null;
};

const hasExplicitEoCrsInContents = (contents, config) => {
    return contents.some((item) => {
        let skipNextDataLine = Boolean(config?.hasHeader);
        return String(item.content || '').split('\n').some((rawLine) => {
            const line = rawLine.trim();
            if (!line) return false;
            if (line.startsWith('#') || line.startsWith('//')) {
                return Boolean(normalizeEoCrs(line));
            }
            if (skipNextDataLine) {
                skipNextDataLine = false;
                return false;
            }
            let parts = splitEoLine(line, config?.delimiter || 'space');
            parts = parts.map((part) => part.trim()).filter(Boolean);
            return Boolean(extractRowCrs(parts, config?.columns));
        });
    });
};

const transformEoPointToWgs84 = (row, config) => {
    const columns = config?.columns || {};
    const x = getEoNumber(row, columns, 'x');
    const y = getEoNumber(row, columns, 'y');
    const sourceCrs = normalizeEoCrs(row.crs) || normalizeEoCrs(config?.crs) || 'EPSG:5186';

    if (!Number.isFinite(x) || !Number.isFinite(y)) {
        return { valid: false, sourceCrs, reason: '좌표값을 숫자로 해석할 수 없습니다.' };
    }

    try {
        const [lng, lat] = sourceCrs === 'EPSG:4326'
            ? [x, y]
            : proj4(sourceCrs, 'EPSG:4326', [x, y]);

        const valid = Number.isFinite(lat)
            && Number.isFinite(lng)
            && lat >= -90
            && lat <= 90
            && lng >= -180
            && lng <= 180;

        return {
            lat,
            lng,
            sourceCrs,
            valid,
            reason: valid ? null : '변환된 위경도가 유효 범위를 벗어났습니다.',
        };
    } catch (error) {
        return {
            valid: false,
            sourceCrs,
            reason: `좌표 변환 실패: ${error.message}`,
        };
    }
};

const buildPrimaryEoRows = (rows, excludedKeys = new Set()) => {
    const primaryRows = [];
    const seen = new Set();

    rows.forEach((row) => {
        if (!row.imageKey || excludedKeys.has(row.imageKey) || seen.has(row.imageKey)) return;
        seen.add(row.imageKey);
        primaryRows.push(row);
    });

    return primaryRows;
};

const buildEoMapPoints = (rows, config, excludedKeys = new Set()) => {
    const seen = new Set();
    const points = [];

    rows.forEach((row, index) => {
        if (!row.imageKey || seen.has(row.imageKey)) return;
        seen.add(row.imageKey);
        const transformed = transformEoPointToWgs84(row, config);
        points.push({
            id: `${row.imageKey}-${index}`,
            imageKey: row.imageKey,
            imageName: row.imageName,
            sourceName: row.sourceName,
            excluded: excludedKeys.has(row.imageKey),
            ...transformed,
        });
    });

    return points;
};

const buildEoUploadFiles = (contents) => (
    contents.map((item) => {
        const blob = new Blob([item.content], { type: 'text/plain' });
        return new File([blob], item.filename, { type: 'text/plain' });
    })
);

const getEoItemKey = (item) => item.path || item.filename;

function EoMapFit({ points }) {
    const map = useMap();
    const fittedSignatureRef = React.useRef(null);
    const fitSignature = points
        .filter((point) => point.valid)
        .map((point) => `${point.imageKey}:${point.lat.toFixed(6)}:${point.lng.toFixed(6)}`)
        .join('|');

    useEffect(() => {
        window.setTimeout(() => map.invalidateSize(), 0);
        const validPoints = points.filter((point) => point.valid);
        if (validPoints.length === 0) return;
        if (fittedSignatureRef.current === fitSignature) return;

        const bounds = L.latLngBounds(validPoints.map((point) => [point.lat, point.lng]));
        if (bounds.isValid()) {
            map.fitBounds(bounds, { padding: [24, 24], maxZoom: 17 });
            fittedSignatureRef.current = fitSignature;
        }
    }, [map, points, fitSignature]);

    return null;
}

function EoBoxSelection({ enabled, points, onSelectionChange, onContextMenu }) {
    const map = useMap();
    const [startLatLng, setStartLatLng] = useState(null);
    const [dragBounds, setDragBounds] = useState(null);

    useEffect(() => {
        if (enabled) {
            map.dragging.disable();
            map.getContainer().style.cursor = 'crosshair';
        } else {
            map.dragging.enable();
            map.getContainer().style.cursor = '';
            setStartLatLng(null);
            setDragBounds(null);
        }

        return () => {
            map.dragging.enable();
            map.getContainer().style.cursor = '';
        };
    }, [enabled, map]);

    useMapEvents({
        mousedown(event) {
            if (!enabled || event.originalEvent.button !== 0) return;
            event.originalEvent.preventDefault();
            setStartLatLng(event.latlng);
            setDragBounds(L.latLngBounds(event.latlng, event.latlng));
        },
        mousemove(event) {
            if (!enabled || !startLatLng) return;
            setDragBounds(L.latLngBounds(startLatLng, event.latlng));
        },
        mouseup(event) {
            if (!enabled || !startLatLng) return;
            const bounds = L.latLngBounds(startLatLng, event.latlng);
            setStartLatLng(null);
            setDragBounds(null);

            const selected = points
                .filter((point) => point.valid && bounds.contains([point.lat, point.lng]))
                .map((point) => point.imageKey);
            onSelectionChange(new Set(selected));
        },
        contextmenu(event) {
            if (!enabled) return;
            event.originalEvent.preventDefault();
            onContextMenu({
                x: event.originalEvent.clientX,
                y: event.originalEvent.clientY,
            });
        },
    });

    if (!enabled || !dragBounds) return null;

    return (
        <Rectangle
            bounds={dragBounds}
            pathOptions={{
                color: '#f59e0b',
                weight: 2,
                fillColor: '#fbbf24',
                fillOpacity: 0.12,
                dashArray: '4 4',
            }}
        />
    );
}

function EoLocationPreview({ points, excludedCount, onToggleExcluded, onBulkSetExcluded, onClearExcluded }) {
    const tileConfig = getTileConfig();
    const [selectionEnabled, setSelectionEnabled] = useState(false);
    const [selectedKeys, setSelectedKeys] = useState(() => new Set());
    const [contextMenu, setContextMenu] = useState(null);
    const validPoints = points.filter((point) => point.valid);
    const invalidCount = points.length - validPoints.length;
    const includedCount = validPoints.filter((point) => !point.excluded).length;
    const selectedCount = selectedKeys.size;

    useEffect(() => {
        setSelectedKeys((prev) => {
            if (prev.size === 0) return prev;
            const validKeys = new Set(points.map((point) => point.imageKey));
            const next = new Set([...prev].filter((key) => validKeys.has(key)));
            return next.size === prev.size ? prev : next;
        });
    }, [points]);

    useEffect(() => {
        if (!contextMenu) return undefined;
        const closeMenu = () => setContextMenu(null);
        document.addEventListener('click', closeMenu);
        return () => document.removeEventListener('click', closeMenu);
    }, [contextMenu]);

    const applySelection = (excluded) => {
        if (selectedKeys.size === 0) return;
        onBulkSetExcluded(Array.from(selectedKeys), excluded);
        setContextMenu(null);
    };

    if (points.length === 0) {
        return (
            <div className="h-full flex flex-col items-center justify-center text-slate-300 text-center">
                <Info size={36} className="mb-2 opacity-40" />
                <p className="text-sm font-medium">EO 좌표가 있으면 위치 preview가 표시됩니다.</p>
            </div>
        );
    }

    return (
        <div className="h-full flex flex-col relative">
            <div className="px-3 py-2 border-b border-slate-100 bg-slate-50 flex items-center justify-between gap-2 shrink-0">
                <div className="min-w-0">
                    <div className="text-sm font-bold text-slate-700">EO 위치 preview</div>
                    <div className="text-[11px] text-slate-500">
                        포함 {includedCount}개 · 제외 {excludedCount}개{selectedCount > 0 ? ` · 선택 ${selectedCount}개` : ''}{invalidCount > 0 ? ` · 변환 실패 ${invalidCount}개` : ''}
                    </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                    <button
                        onClick={() => {
                            setSelectionEnabled((prev) => !prev);
                            setContextMenu(null);
                        }}
                        className={`px-2 py-1 text-[11px] font-bold border rounded ${selectionEnabled ? 'bg-amber-100 border-amber-300 text-amber-800' : 'bg-white border-slate-200 text-slate-600 hover:text-blue-600'}`}
                    >
                        박스 선택
                    </button>
                    {selectedCount > 0 && (
                        <>
                            <button
                                onClick={() => applySelection(true)}
                                className="px-2 py-1 text-[11px] font-bold border border-red-200 bg-white text-red-600 rounded hover:bg-red-50"
                            >
                                선택 제외
                            </button>
                            <button
                                onClick={() => applySelection(false)}
                                className="px-2 py-1 text-[11px] font-bold border border-blue-200 bg-white text-blue-700 rounded hover:bg-blue-50"
                            >
                                선택 포함
                            </button>
                        </>
                    )}
                    {selectedCount > 0 && (
                        <button
                            onClick={() => setSelectedKeys(new Set())}
                            className="px-2 py-1 text-[11px] font-bold text-slate-500 border border-slate-200 bg-white rounded hover:text-slate-700"
                        >
                            선택 해제
                        </button>
                    )}
                    {excludedCount > 0 && (
                        <button
                            onClick={onClearExcluded}
                            className="shrink-0 px-2 py-1 text-[11px] font-bold text-slate-500 border border-slate-200 bg-white rounded hover:text-blue-600"
                        >
                            제외 초기화
                        </button>
                    )}
                </div>
            </div>
            <div className="px-3 py-1.5 border-b border-slate-100 bg-white flex items-center gap-3 text-[11px] text-slate-500 shrink-0">
                <span className="inline-flex items-center gap-1">
                    <span className="w-2.5 h-2.5 rounded-full bg-sky-400 border border-blue-600" />
                    처리 포함
                </span>
                <span className="inline-flex items-center gap-1">
                    <span className="w-2.5 h-2.5 rounded-full bg-slate-400 border-2 border-slate-700" />
                    처리 제외
                </span>
                <span className="inline-flex items-center gap-1">
                    <span className="w-2.5 h-2.5 rounded-full bg-violet-300 border-2 border-violet-700" />
                    선택됨
                </span>
            </div>
            {selectionEnabled && (
                <div className="px-3 py-1.5 bg-amber-50 border-b border-amber-100 text-[11px] text-amber-700 shrink-0">
                    왼쪽 드래그로 범위를 선택한 뒤 지도에서 우클릭하면 포함/제외 메뉴가 열립니다.
                </div>
            )}
            {validPoints.length === 0 ? (
                <div className="flex-1 flex items-center justify-center text-xs text-slate-400 text-center px-4">
                    현재 CRS와 열 매핑으로 표시 가능한 좌표가 없습니다.
                </div>
            ) : (
                <MapContainer
                    center={MAP_CONFIG.defaultCenter}
                    zoom={MAP_CONFIG.defaultZoom}
                    maxZoom={tileConfig.maxZoom}
                    minZoom={MAP_CONFIG.minZoom}
                    style={{ height: '100%', width: '100%', background: '#f8fafc' }}
                    zoomControl={true}
                    scrollWheelZoom={true}
                    preferCanvas={true}
                    boxZoom={false}
                >
                    <TileLayer
                        attribution={tileConfig.attribution}
                        url={tileConfig.url}
                        {...(tileConfig.subdomains ? { subdomains: tileConfig.subdomains } : {})}
                        maxNativeZoom={tileConfig.maxNativeZoom}
                        maxZoom={tileConfig.maxZoom}
                        minZoom={MAP_CONFIG.minZoom}
                    />
                    <EoMapFit points={validPoints} />
                    <EoBoxSelection
                        enabled={selectionEnabled}
                        points={validPoints}
                        onSelectionChange={(keys) => {
                            setSelectedKeys(keys);
                            setContextMenu(null);
                        }}
                        onContextMenu={setContextMenu}
                    />
                    {validPoints.map((point) => {
                        const selected = selectedKeys.has(point.imageKey);
                        const markerColor = selected ? '#7c3aed' : (point.excluded ? '#475569' : '#2563eb');
                        const markerFill = selected ? '#c4b5fd' : (point.excluded ? '#94a3b8' : '#38bdf8');
                        return (
                            <CircleMarker
                                key={point.id}
                                center={[point.lat, point.lng]}
                                radius={selected ? 8 : (point.excluded ? 7 : 7)}
                                pathOptions={{
                                    color: markerColor,
                                    fillColor: markerFill,
                                    fillOpacity: point.excluded ? 0.9 : 0.8,
                                    weight: selected ? 3 : (point.excluded ? 3 : 1.5),
                                    dashArray: point.excluded ? '4 3' : null,
                                }}
                                eventHandlers={{
                                    click: () => {
                                        if (selectionEnabled) {
                                            setSelectedKeys((prev) => {
                                                const next = new Set(prev);
                                                if (next.has(point.imageKey)) next.delete(point.imageKey);
                                                else next.add(point.imageKey);
                                                return next;
                                            });
                                            return;
                                        }
                                        onToggleExcluded(point.imageKey);
                                    },
                                    contextmenu: (event) => {
                                        if (!selectionEnabled) return;
                                        event.originalEvent.preventDefault();
                                        setContextMenu({
                                            x: event.originalEvent.clientX,
                                            y: event.originalEvent.clientY,
                                        });
                                    },
                                }}
                            >
                                <Tooltip direction="top" offset={[0, -8]} opacity={0.95}>
                                    <div className="text-xs">
                                        <div className="font-bold">{point.imageName}</div>
                                        <div>{point.excluded ? '처리 제외됨' : '처리 포함'} · {point.sourceCrs}</div>
                                    </div>
                                </Tooltip>
                                <Popup>
                                    <div className="text-xs space-y-1 min-w-[170px]">
                                        <div className="font-bold text-slate-800 break-all">{point.imageName}</div>
                                        <div className="text-slate-500 break-all">{point.sourceName}</div>
                                        <div className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-bold ${point.excluded ? 'bg-slate-100 text-slate-700 border border-slate-200' : 'bg-blue-50 text-blue-700'}`}>
                                            {point.excluded ? '처리 제외됨' : '처리 포함'}
                                        </div>
                                        <div className="font-mono text-slate-500">
                                            {point.lat.toFixed(6)}, {point.lng.toFixed(6)}
                                        </div>
                                        <button
                                            onClick={() => onToggleExcluded(point.imageKey)}
                                            className={`mt-1 w-full px-2 py-1 rounded font-bold ${point.excluded ? 'bg-blue-50 text-blue-700' : 'bg-slate-100 text-slate-700'}`}
                                        >
                                            {point.excluded ? '다시 포함' : '처리 제외'}
                                        </button>
                                    </div>
                                </Popup>
                            </CircleMarker>
                        );
                    })}
                </MapContainer>
            )}
            {contextMenu && (
                <div
                    className="fixed z-[1300] w-40 bg-white border border-slate-200 rounded-lg shadow-xl overflow-hidden"
                    style={{ left: contextMenu.x, top: contextMenu.y }}
                    onClick={(event) => event.stopPropagation()}
                >
                    <div className="px-3 py-2 bg-slate-50 border-b border-slate-100 text-[11px] font-bold text-slate-600">
                        선택 {selectedCount}개
                    </div>
                    <button
                        disabled={selectedCount === 0}
                        onClick={() => applySelection(true)}
                        className="w-full text-left px-3 py-2 text-xs font-bold text-red-600 hover:bg-red-50 disabled:opacity-40"
                    >
                        선택 제외
                    </button>
                    <button
                        disabled={selectedCount === 0}
                        onClick={() => applySelection(false)}
                        className="w-full text-left px-3 py-2 text-xs font-bold text-blue-700 hover:bg-blue-50 disabled:opacity-40"
                    >
                        선택 포함
                    </button>
                    <button
                        onClick={() => {
                            setSelectedKeys(new Set());
                            setContextMenu(null);
                        }}
                        className="w-full text-left px-3 py-2 text-xs text-slate-500 hover:bg-slate-50"
                    >
                        선택 해제
                    </button>
                </div>
            )}
            {invalidCount > 0 && (
                <div className="px-3 py-1.5 bg-amber-50 text-[11px] text-amber-700 border-t border-amber-100 shrink-0">
                    좌표 변환 실패 행은 CRS/열 매핑을 확인해야 합니다.
                </div>
            )}
        </div>
    );
}

export default function UploadWizard({ isOpen, onClose, onComplete }) {
    const [step, setStep] = useState(1);
    const [imageCount, setImageCount] = useState(0);
    const [eoFileName, setEoFileName] = useState(null);
    const [cameraModel, setCameraModel] = useState("");
    const [cameraModels, setCameraModels] = useState([]);
    const [isAddingCamera, setIsAddingCamera] = useState(false);
    const [editingCameraId, setEditingCameraId] = useState(null);
    const [newCamera, setNewCamera] = useState(createDefaultCameraModel);
    const [projectName, setProjectName] = useState('');
    const [showMismatchWarning, setShowMismatchWarning] = useState(false);
    const [autoProcess, setAutoProcess] = useState(true);
    const [processMode, setProcessMode] = useState('Normal');
    const [isFinishing, setIsFinishing] = useState(false);

    useEffect(() => {
        if (isOpen) {
            api.getCameraModels().then(models => {
                setCameraModels(models);
                // Set default to first camera model if not already set
                if (models.length > 0) {
                    setCameraModel(current => current || models[0].name);
                }
            }).catch(console.error);
        }
    }, [isOpen]);

    const selectedCamera = useMemo(() => {
        return cameraModels.find(c => c.name === cameraModel) || { focal_length: 0, sensor_width: 0, sensor_height: 0, pixel_size: 0 };
    }, [cameraModel, cameraModels]);

    const cameraModelCounts = useMemo(() => {
        const standard = cameraModels.filter(c => !c.is_custom).length;
        return {
            standard,
            custom: cameraModels.length - standard
        };
    }, [cameraModels]);

    const closeCameraForm = () => {
        setIsAddingCamera(false);
        setEditingCameraId(null);
        setNewCamera(createDefaultCameraModel());
    };

    const openAddCameraForm = () => {
        setEditingCameraId(null);
        setNewCamera(createDefaultCameraModel());
        setIsAddingCamera(true);
    };

    const openEditCameraForm = () => {
        if (!selectedCamera?.id) return;
        setEditingCameraId(selectedCamera.id);
        setNewCamera({
            name: selectedCamera.name || '',
            focal_length: selectedCamera.focal_length ?? 0,
            sensor_width: selectedCamera.sensor_width ?? 0,
            sensor_height: selectedCamera.sensor_height ?? 0,
            pixel_size: selectedCamera.pixel_size ?? 0,
            sensor_width_px: selectedCamera.sensor_width_px ?? 0,
            sensor_height_px: selectedCamera.sensor_height_px ?? 0,
            ppa_x: selectedCamera.ppa_x ?? 0,
            ppa_y: selectedCamera.ppa_y ?? 0,
            is_custom: Boolean(selectedCamera.is_custom),
        });
        setIsAddingCamera(true);
    };

    const handleSaveCamera = async () => {
        try {
            const payload = {
                ...newCamera,
                name: newCamera.name || 'Custom Camera',
                is_custom: editingCameraId ? true : newCamera.is_custom,
            };
            if (editingCameraId) {
                const updated = await api.updateCameraModel(editingCameraId, payload);
                setCameraModels(prev => prev.map(item => item.id === updated.id ? updated : item));
                setCameraModel(updated.name);
            } else {
                const created = await api.createCameraModel(payload);
                setCameraModels(prev => [...prev, created]);
                setCameraModel(created.name);
            }
            closeCameraForm();
        } catch (err) {
            alert(err?.message || "카메라 모델 저장에 실패했습니다.");
        }
    };

    const handleDeleteCamera = async () => {
        if (!selectedCamera?.id) return;
        if (!window.confirm(`${selectedCamera.name} 카메라 모델을 삭제하시겠습니까?`)) return;

        try {
            await api.deleteCameraModel(selectedCamera.id);
            setCameraModels(prev => {
                const next = prev.filter(item => item.id !== selectedCamera.id);
                setCameraModel(next[0]?.name || '');
                return next;
            });
            if (editingCameraId === selectedCamera.id) {
                closeCameraForm();
            }
        } catch (err) {
            alert(err?.message || "카메라 모델 삭제에 실패했습니다.");
        }
    };
    const [selectedEoFile, setSelectedEoFile] = useState(null);
    const [eoConfig, setEoConfig] = useState(createDefaultEoConfig);
    const [eoCrsTouched, setEoCrsTouched] = useState(false);

    const [selectionMode, setSelectionMode] = useState(null); // 'folder' or 'files'
    const [showFileBrowser, setShowFileBrowser] = useState(false);
    const [fileBrowserMode, setFileBrowserMode] = useState('folder');
    const [sourceDir, setSourceDir] = useState(null);
    const [serverFilePaths, setServerFilePaths] = useState(null);
    const [selectedImageKeys, setSelectedImageKeys] = useState(() => new Set());
    const [showEoFileBrowser, setShowEoFileBrowser] = useState(false);
    const [eoFilePath, setEoFilePath] = useState(null);
    const [eoFileContents, setEoFileContents] = useState([]);
    const [excludedEoImageKeys, setExcludedEoImageKeys] = useState(() => new Set());

    const [rawEoData, setRawEoData] = useState(`ImageID,Lat,Lon,Alt,Omega,Phi,Kappa
IMG_001,37.1234,127.5543,150.2,0.1,-0.2,1.5
IMG_002,37.1235,127.5544,150.3,0.1,-0.2,1.5
IMG_003,37.1236,127.5545,150.2,0.0,-0.2,1.4
IMG_004,37.1237,127.5546,150.1,0.2,-0.1,1.3`);

    const parsedPreview = useMemo(() => {
        if (!eoFileName) return [];
        const contents = eoFileContents.length > 0 ? eoFileContents : [{ content: rawEoData }];
        const rows = contents.flatMap(item => parseEoRowsForContent(item, eoConfig));
        const matchedRows = filterRowsBySelectedImages(rows, selectedImageKeys);
        const showUnmatchedPreview = selectedImageKeys.size > 0 && rows.length > 0 && matchedRows.length === 0;
        const previewRows = (showUnmatchedPreview ? rows : matchedRows)
            .slice(0, 300)
            .map((row) => ({ ...row, unmatched: showUnmatchedPreview }));
        return previewRows.map((row, idx) => {
            const parts = row.parts;
            const getVal = (colIdx) => parts[colIdx] || '-';
            return {
                key: idx,
                imageKey: row.imageKey,
                unmatched: row.unmatched,
                excluded: !row.unmatched && excludedEoImageKeys.has(row.imageKey),
                source_file: row.sourceName,
                image_name: getVal(eoConfig.columns.image_name),
                x: getVal(eoConfig.columns.x),
                y: getVal(eoConfig.columns.y),
                z: getVal(eoConfig.columns.z),
                omega: getVal(eoConfig.columns.omega),
                phi: getVal(eoConfig.columns.phi),
                kappa: getVal(eoConfig.columns.kappa),
            };
        });
    }, [eoConfig, eoFileName, rawEoData, eoFileContents, selectedImageKeys, excludedEoImageKeys]);

    useEffect(() => {
        if (isOpen) {
            setStep(1);
            setImageCount(0);
            setEoFileName(null);
            setEoConfig(createDefaultEoConfig());
            setProjectName('');
            setShowMismatchWarning(false);
            setSelectedEoFile(null);
            setEoFileContents([]);
            setSourceDir(null);
            setServerFilePaths(null);
            setSelectedImageKeys(new Set());
            setShowFileBrowser(false);
            setShowEoFileBrowser(false);
            setEoFilePath(null);
            setExcludedEoImageKeys(new Set());
            setAutoProcess(true);
            setIsFinishing(false);
            setEoCrsTouched(false);
            setIsAddingCamera(false);
            setEditingCameraId(null);
            setNewCamera(createDefaultCameraModel());
        }
    }, [isOpen]);

    // ESC key handler to close modal
    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.key === 'Escape' && !isFinishing && !showMismatchWarning && !showFileBrowser && !showEoFileBrowser) {
                if (imageCount > 0 || eoFileName) {
                    if (window.confirm('업로드를 취소하시겠습니까? 모든 선택이 초기화됩니다.')) {
                        onClose();
                    }
                } else {
                    onClose();
                }
            }
        };
        if (isOpen) {
            document.addEventListener('keydown', handleKeyDown);
        }
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, imageCount, eoFileName, isFinishing, showMismatchWarning, showFileBrowser, showEoFileBrowser, onClose]);

    const handleServerSelect = (result) => {
        const imageFilePaths = result.filePaths || [];
        setSelectedImageKeys(buildImageKeySetFromPaths(imageFilePaths));
        if (fileBrowserMode === 'folder') {
            setSourceDir(result.path);
            setImageCount(result.imageCount);
            setSelectionMode('folder');
            setServerFilePaths(imageFilePaths);
            if (!projectName) {
                const folderName = result.path.split('/').pop();
                if (folderName) setProjectName(folderName);
            }
        } else {
            setSourceDir(result.path);
            setServerFilePaths(result.filePaths);
            setImageCount(result.filePaths.length);
            setSelectionMode('files');
        }
    };

    const handleEoServerSelect = async (result) => {
        const filePaths = result.filePaths?.length ? result.filePaths : (result.filePath ? [result.filePath] : []);
        if (filePaths.length === 0) return;
        try {
            const dataList = await Promise.all(
                filePaths.map(async (path) => ({ ...(await api.readTextFile(path)), path }))
            );
            const merged = [...eoFileContents];
            const seen = new Set(merged.map(getEoItemKey));
            dataList.forEach((item) => {
                const key = getEoItemKey(item);
                if (!seen.has(key)) {
                    merged.push(item);
                    seen.add(key);
                }
            });
            applyEoContents(merged);
        } catch (err) {
            alert(`EO 파일 읽기 실패: ${err.message}`);
        }
    };

    const applyEoContents = (contents) => {
        if (!eoCrsTouched && contents.length > 0) {
            const rows = contents.flatMap((item) => parseEoRowsForContent(item, eoConfig));
            const inferredCrs = !hasExplicitEoCrsInContents(contents, eoConfig)
                ? inferEoCrsFromRows(rows, eoConfig.columns)
                : null;
            if (inferredCrs && CRS_LABEL_BY_CODE[inferredCrs]) {
                setEoConfig((prev) => ({
                    ...prev,
                    crs: CRS_LABEL_BY_CODE[inferredCrs],
                }));
            }
        }
        setEoFileContents(contents);
        setRawEoData(contents.map(data => data.content).join('\n'));
        setEoFilePath(contents.length === 1 ? contents[0].path : (contents.length > 1 ? `${contents.length}개 위치` : null));
        setEoFileName(contents.length === 0 ? null : (contents.length === 1 ? contents[0].filename : `${contents.length}개 EO 파일`));
        const uploadFiles = buildEoUploadFiles(contents);
        setSelectedEoFile(uploadFiles.length === 0 ? null : (uploadFiles.length === 1 ? uploadFiles[0] : uploadFiles));
    };

    const handleRemoveEoFile = (key) => {
        applyEoContents(eoFileContents.filter((item) => getEoItemKey(item) !== key));
    };

    const handleClearEoFiles = () => {
        applyEoContents([]);
    };

    const eoParsedRows = useMemo(() => {
        if (!eoFileName) return [];
        const contents = eoFileContents.length > 0 ? eoFileContents : [{ content: rawEoData, filename: '직접 입력' }];
        return contents.flatMap((item) => parseEoRowsForContent(item, eoConfig));
    }, [eoConfig, eoFileName, rawEoData, eoFileContents]);

    const matchedEoRows = useMemo(
        () => filterRowsBySelectedImages(eoParsedRows, selectedImageKeys),
        [eoParsedRows, selectedImageKeys]
    );

    useEffect(() => {
        if (
            selectionMode !== 'folder'
            || !sourceDir
            || !eoFileName
            || eoParsedRows.length === 0
            || matchedEoRows.length > 0
        ) {
            return undefined;
        }

        let cancelled = false;
        api.browseFilesystem(sourceDir, 'images')
            .then((data) => {
                if (cancelled) return;
                const folderImagePaths = (data.entries || [])
                    .filter((entry) => !entry.is_dir)
                    .map((entry) => entry.path);
                const folderImageKeys = buildImageKeySetFromPaths(folderImagePaths);
                const hasRecoveredMatch = eoParsedRows.some(
                    (row) => row.imageKey && folderImageKeys.has(row.imageKey)
                );
                if (hasRecoveredMatch) {
                    setSelectedImageKeys(folderImageKeys);
                    setImageCount(data.image_count || folderImageKeys.size);
                }
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, [selectionMode, sourceDir, eoFileName, eoParsedRows, matchedEoRows.length]);

    useEffect(() => {
        setExcludedEoImageKeys((prev) => {
            if (prev.size === 0) return prev;
            const availableKeys = new Set(matchedEoRows.map((row) => row.imageKey).filter(Boolean));
            const next = new Set([...prev].filter((key) => availableKeys.has(key)));
            return next.size === prev.size ? prev : next;
        });
    }, [matchedEoRows]);

    const rawEoLineCount = eoParsedRows.length;
    const eoLineCount = matchedEoRows.length;
    const unmatchedEoLineCount = Math.max(0, rawEoLineCount - eoLineCount);
    const hasEoMatchWarning = Boolean(
        eoFileName
        && rawEoLineCount > 0
        && selectedImageKeys.size > 0
        && eoLineCount === 0
    );
    const eoRowsAfterUserExclusions = useMemo(
        () => matchedEoRows.filter((row) => row.imageKey && !excludedEoImageKeys.has(row.imageKey)),
        [matchedEoRows, excludedEoImageKeys]
    );
    const primaryIncludedEoRows = useMemo(
        () => buildPrimaryEoRows(matchedEoRows, excludedEoImageKeys),
        [matchedEoRows, excludedEoImageKeys]
    );
    const effectiveEoLineCount = useMemo(() => {
        return primaryIncludedEoRows.length;
    }, [primaryIncludedEoRows]);
    const eoMapSourceRows = hasEoMatchWarning ? eoParsedRows : matchedEoRows;
    const eoMapPoints = useMemo(
        () => buildEoMapPoints(eoMapSourceRows, eoConfig, excludedEoImageKeys),
        [eoMapSourceRows, eoConfig, excludedEoImageKeys]
    );

    const eoFileSummaries = useMemo(() => {
        return eoFileContents.map((item) => {
            const rows = parseEoRowsForContent(item, eoConfig);
            const matchedRows = filterRowsBySelectedImages(rows, selectedImageKeys);
            const crsValues = Array.from(new Set(rows.map((row) => row.crs).filter(Boolean))).sort();
            return {
                key: getEoItemKey(item),
                rowCount: matchedRows.length,
                totalRowCount: rows.length,
                crsValues,
            };
        });
    }, [eoFileContents, eoConfig, selectedImageKeys]);

    const eoCrsValues = useMemo(() => {
        if (!eoFileName) return [];
        const fallbackCrs = normalizeEoCrs(eoConfig?.crs) || eoConfig?.crs || 'EPSG:5186';
        return Array.from(new Set(
            eoRowsAfterUserExclusions
                .map((row) => normalizeEoCrs(row.crs) || fallbackCrs)
                .filter(Boolean)
        )).sort();
    }, [eoConfig, eoFileName, eoRowsAfterUserExclusions]);

    const hasMixedEoCrs = eoCrsValues.length > 1;
    const duplicateEoImages = useMemo(() => findDuplicateEoImages(eoRowsAfterUserExclusions), [eoRowsAfterUserExclusions]);
    const hasDuplicateEoImages = duplicateEoImages.length > 0;
    const duplicateIgnoredCount = useMemo(
        () => duplicateEoImages.reduce((total, item) => total + Math.max(0, item.count - 1), 0),
        [duplicateEoImages]
    );

    const eoBrowserInitialPath = useMemo(() => {
        const lastPath = eoFileContents[eoFileContents.length - 1]?.path;
        if (!lastPath) return sourceDir;
        const parts = lastPath.split('/');
        parts.pop();
        return parts.join('/') || sourceDir;
    }, [eoFileContents, sourceDir]);

    const toggleEoImageExcluded = (imageKey) => {
        if (!imageKey) return;
        setExcludedEoImageKeys((prev) => {
            const next = new Set(prev);
            if (next.has(imageKey)) next.delete(imageKey);
            else next.add(imageKey);
            return next;
        });
    };

    const setEoImagesExcluded = (imageKeys, excluded) => {
        const keys = Array.from(imageKeys || []).filter(Boolean);
        if (keys.length === 0) return;

        setExcludedEoImageKeys((prev) => {
            const next = new Set(prev);
            keys.forEach((key) => {
                if (excluded) next.add(key);
                else next.delete(key);
            });
            return next;
        });
    };

    const handleProceedToStep4 = () => {
        if (effectiveEoLineCount === 0) {
            alert('처리에 사용할 EO 데이터가 없습니다. CRS/열 매핑 또는 제외 상태를 확인해주세요.');
            return;
        }
        if (hasMixedEoCrs) {
            alert(`EO 좌표계가 섞여 있습니다: ${eoCrsValues.join(', ')}\n좌표계를 통일하거나 문제 파일을 제거한 뒤 진행해주세요.`);
            return;
        }
        if (imageCount !== effectiveEoLineCount) {
            setShowMismatchWarning(true);
        } else {
            setStep(4);
        }
    };

    const handleConfirmMismatch = () => {
        setShowMismatchWarning(false);
        setStep(4);
    };

    const handleCancelUpload = () => {
        if (isFinishing) return;
        if (imageCount > 0 || eoFileName) {
            if (window.confirm('업로드를 취소하시겠습니까? 모든 선택이 초기화됩니다.')) {
                onClose();
            }
        } else {
            onClose();
        }
    };

    const handleFinish = async () => {
        if (isFinishing) return;
        if (hasMixedEoCrs) {
            alert('EO 파일의 좌표계 혼재를 먼저 해결해주세요.');
            return;
        }
        if (effectiveEoLineCount === 0) {
            alert('처리에 사용할 EO 데이터가 없습니다. CRS/열 매핑 또는 제외 상태를 확인해주세요.');
            return;
        }

        const uploadEoConfig = {
            ...eoConfig,
            excludedImageNames: Array.from(excludedEoImageKeys),
        };

        const projectData = {
            title: projectName || `Project_${new Date().toISOString().slice(0, 19).replace(/-/g, '').replace(/:/g, '').replace('T', '')}`,
            region: '수도권북부 권역',
            company: '',
        };

        setIsFinishing(true);
        try {
            const result = await onComplete({
                projectData,
                sourceDir,
                filePaths: serverFilePaths,
                eoFile: selectedEoFile,
                eoConfig: uploadEoConfig,
                cameraModel,
                autoProcess: autoProcess && !!eoFileName,
                processMode,
                imageCount,
            });
            if (result?.ok === false) return;
            onClose();
        } catch (error) {
            console.error('Upload completion failed:', error);
            alert(`프로젝트 생성 처리 실패: ${error?.message || '알 수 없는 오류'}`);
        } finally {
            setIsFinishing(false);
        }
    };

    if (!isOpen) return null;

    return (
        <>
        <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200" onClick={handleCancelUpload}>
            <div
                className={`bg-white rounded-xl shadow-2xl flex flex-col ${step === 2 ? 'w-[min(1280px,96vw)] h-[98vh]' : 'w-[900px] max-h-[95vh]'}`}
                onClick={e => e.stopPropagation()}
            >
                <div className="h-16 border-b border-slate-200 flex items-center justify-between px-8 bg-slate-50">
                    <h3 className="font-bold text-slate-800 text-lg flex items-center gap-2"><UploadCloud size={24} className="text-blue-600" />새 프로젝트 데이터 업로드</h3>
                    <div className="flex items-center gap-3">
                        <div className="flex items-center gap-1">{[1, 2, 3, 4].map(s => (<div key={s} className={`w-2 h-2 rounded-full ${step === s ? 'bg-blue-600 scale-125' : step > s ? 'bg-blue-300' : 'bg-slate-200'}`} />))}</div>
                        <button onClick={handleCancelUpload} className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-200 rounded-lg transition-colors" title="닫기"><X size={20} /></button>
                    </div>
                </div>
                <div className={`${step === 2 ? 'p-4' : 'p-8'} flex-1 overflow-y-auto min-h-0`}>
                    {step === 1 && (
                        <div className="space-y-6 max-w-2xl mx-auto h-full flex flex-col justify-center">
                            <h4 className="text-xl font-bold text-slate-800 text-center mb-6">1. 원본 이미지 선택</h4>
                            <div className="grid grid-cols-2 gap-4">
                                <button
                                    onClick={() => { setFileBrowserMode('folder'); setShowFileBrowser(true); }}
                                    className={`p-10 border-2 rounded-xl flex flex-col items-center gap-4 transition-all ${selectionMode === 'folder' ? 'border-blue-500 bg-blue-50' : 'border-slate-200 hover:border-blue-300'}`}
                                >
                                    <FolderOpen size={48} className="text-blue-600" />
                                    <div>
                                        <div className="font-bold text-slate-700 text-lg">폴더 선택</div>
                                        <div className="text-sm text-slate-500">폴더 내 전체 로드</div>
                                    </div>
                                </button>
                                <button
                                    onClick={() => { setFileBrowserMode('files'); setShowFileBrowser(true); }}
                                    className={`p-10 border-2 rounded-xl flex flex-col items-center gap-4 transition-all ${selectionMode === 'files' ? 'border-blue-500 bg-blue-50' : 'border-slate-200 hover:border-blue-300'}`}
                                >
                                    <FilePlus size={48} className="text-emerald-600" />
                                    <div>
                                        <div className="font-bold text-slate-700 text-lg">이미지 선택</div>
                                        <div className="text-sm text-slate-500">개별 파일 선택</div>
                                    </div>
                                </button>
                            </div>
                            {imageCount > 0 && (
                                <div className="text-center p-4 bg-slate-100 rounded-lg text-slate-700 animate-in fade-in">
                                    <div className="flex items-center justify-center gap-2">
                                        <CheckCircle2 size={20} className="text-blue-600" />
                                        총 <span className="font-bold text-blue-600">{imageCount}</span>장의 이미지가 확인되었습니다.
                                    </div>
                                    {sourceDir && <div className="text-xs text-slate-500 mt-2 font-mono truncate" title={sourceDir}>{sourceDir}</div>}
                                </div>
                            )}
                        </div>
                    )}
                    {step === 2 && (
                        <div className="flex flex-col h-full gap-6">
                            <div className="flex justify-between items-center shrink-0"><h4 className="text-xl font-bold text-slate-800">2. EO (Exterior Orientation) 로드 및 설정</h4><button onClick={() => { setEoConfig(createDefaultEoConfig()); setEoCrsTouched(false); handleClearEoFiles(); }} className="text-xs flex items-center gap-1 text-slate-500 hover:text-blue-600 bg-slate-100 px-2 py-1 rounded"><RefreshCw size={12} /> 설정 초기화</button></div>
                            <div className="flex gap-6 shrink-0 h-[220px]">
                                <div
                                    className={`w-1/4 border-2 border-dashed rounded-xl flex flex-col items-center justify-center gap-3 cursor-pointer transition-colors ${eoFileName ? 'border-emerald-500 bg-emerald-50' : 'border-slate-300 hover:bg-slate-50'}`}
                                    onClick={() => setShowEoFileBrowser(true)}
                                >
                                    {eoFileName ? (<><div className="p-3 bg-emerald-100 rounded-full text-emerald-600"><FileText size={32} /></div><div className="text-center px-4"><div className="text-sm font-bold text-slate-800 truncate max-w-[150px]">{eoFileName}</div><div className="text-[10px] text-emerald-600 font-bold mt-1">추가 로드 가능</div>{eoFilePath && <div className="text-[9px] text-slate-400 font-mono truncate max-w-[150px] mt-0.5" title={eoFilePath}>{eoFilePath}</div>}</div></>) : (<><div className="p-3 bg-slate-100 rounded-full text-slate-400"><UploadCloud size={32} /></div><div className="text-center"><div className="text-sm font-bold text-slate-600">EO 파일 선택</div><div className="text-xs text-slate-400 mt-1">.txt, .csv, .json</div></div></>)}
                                </div>
                                <div className="flex-1 bg-slate-50 p-5 rounded-xl border border-slate-200 flex flex-col justify-between">
                                    <div className="grid grid-cols-3 gap-6">
                                        <div className="space-y-1.5"><label className="text-xs font-bold text-slate-500 block">좌표계 (CRS)</label><select className="w-full text-sm border p-2.5 rounded-lg bg-white shadow-sm" value={eoConfig.crs} onChange={(e) => { setEoCrsTouched(true); setEoConfig({ ...eoConfig, crs: e.target.value }); }}><option value="TM중부 (EPSG:5186)">TM 중부 (EPSG:5186)</option><option value="TM서부 (EPSG:5185)">TM 서부 (EPSG:5185)</option><option value="TM동부 (EPSG:5187)">TM 동부 (EPSG:5187)</option><option value="TM동해 (EPSG:5188)">TM 동해 (EPSG:5188)</option><option value="UTM-K (EPSG:5179)">UTM-K (EPSG:5179)</option><option value="WGS84 (EPSG:4326)">WGS84 (EPSG:4326)</option></select></div>
                                        <div className="space-y-1.5"><label className="text-xs font-bold text-slate-500 block">구분자</label><select className="w-full text-sm border p-2.5 rounded-lg bg-white shadow-sm" value={eoConfig.delimiter} onChange={(e) => setEoConfig({ ...eoConfig, delimiter: e.target.value })}><option value="space">공백 (Space)</option><option value="tab">탭 (Tab)</option><option value=",">콤마 (,)</option></select></div>
                                        <div className="space-y-1.5"><label className="text-xs font-bold text-slate-500 block">헤더 행</label><select className="w-full text-sm border p-2.5 rounded-lg bg-white shadow-sm" value={eoConfig.hasHeader} onChange={(e) => setEoConfig({ ...eoConfig, hasHeader: e.target.value === 'true' })}><option value="false">포함 (Include)</option><option value="true">첫 줄 제외 (Skip)</option></select></div>
                                    </div>
                                    <div className="pt-4 border-t border-slate-200">
                                        <label className="text-xs font-bold text-slate-500 mb-2 block">열 번호 매핑 (Column Index)</label>
                                        <div className="flex gap-3">{Object.entries(eoConfig.columns).map(([key, val]) => (<div key={key} className="flex-1 bg-white p-1.5 rounded border border-slate-200 flex flex-col items-center"><span className="text-[10px] font-bold text-slate-400 uppercase mb-1">{key}</span><input type="number" min="0" className="w-full text-center font-mono text-sm font-bold text-blue-600 bg-transparent outline-none" value={val} onChange={(e) => setEoConfig({ ...eoConfig, columns: { ...eoConfig.columns, [key]: parseInt(e.target.value) || 0 } })} /></div>))}</div>
                                    </div>
                                </div>
                            </div>
                            {eoFileContents.length > 0 && (
                                <div className={`shrink-0 rounded-xl border p-3 ${(hasMixedEoCrs || hasDuplicateEoImages || hasEoMatchWarning) ? 'bg-amber-50 border-amber-200' : 'bg-emerald-50 border-emerald-200'}`}>
                                    <div className="flex items-start justify-between gap-4">
                                        <div className="min-w-0">
                                            <div className={`text-sm font-bold flex items-center gap-2 ${(hasMixedEoCrs || hasDuplicateEoImages || hasEoMatchWarning) ? 'text-amber-800' : 'text-emerald-800'}`}>
                                                {(hasDuplicateEoImages || hasMixedEoCrs || hasEoMatchWarning) ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
                                                {hasMixedEoCrs ? `좌표계 혼재 감지: ${eoCrsValues.join(', ')}` : hasDuplicateEoImages ? `이미지명 중복 감지: ${duplicateIgnoredCount}개 행 자동 제외 예정` : hasEoMatchWarning ? '이미지명 매칭 필요' : `적용 좌표계: ${eoCrsValues[0] || eoConfig.crs}`}
                                            </div>
                                            <p className={`text-xs mt-1 ${(hasMixedEoCrs || hasDuplicateEoImages || hasEoMatchWarning) ? 'text-amber-700' : 'text-emerald-700'}`}>
                                                {hasMixedEoCrs ? '지도에서 비정상 위치를 선택 제외하거나 좌표계를 하나로 통일해야 합니다.' : hasDuplicateEoImages ? `동일 이미지명은 먼저 로드된 EO 행 1개만 사용합니다. 매칭 ${eoLineCount}행 중 유효 ${effectiveEoLineCount}행으로 처리됩니다.` : hasEoMatchWarning ? `EO 파일은 ${rawEoLineCount}행 읽혔지만 선택한 이미지와 일치한 행이 없습니다. 아래에는 원본 EO 행과 좌표를 표시합니다.` : `${eoFileContents.length}개 EO 파일, 이미지와 매칭된 ${effectiveEoLineCount}개 데이터 행이 병합됩니다.${unmatchedEoLineCount > 0 ? ` 미매칭 EO ${unmatchedEoLineCount}행은 preview에서 제외됩니다.` : ''}${excludedEoImageKeys.size > 0 ? ` 수동 제외 ${excludedEoImageKeys.size}개.` : ''}`}
                                            </p>
                                        </div>
                                        <button onClick={() => setShowEoFileBrowser(true)} className="shrink-0 px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs font-bold text-slate-600 hover:text-blue-600 hover:border-blue-300">파일 추가</button>
                                    </div>
                                    <div className="mt-3 grid grid-cols-1 gap-1.5 max-h-24 overflow-y-auto">
                                        {eoFileContents.map((item) => {
                                            const key = getEoItemKey(item);
                                            const summary = eoFileSummaries.find((entry) => entry.key === key);
                                            return (
                                                <div key={key} className="flex items-center gap-2 bg-white/80 border border-white rounded-lg px-2 py-1.5">
                                                    <FileText size={14} className="text-slate-400 shrink-0" />
                                                    <div className="min-w-0 flex-1">
                                                        <div className="text-xs font-semibold text-slate-700 truncate">{item.filename}</div>
                                                        <div className="text-[10px] text-slate-400 font-mono truncate" title={item.path}>{item.path}</div>
                                                    </div>
                                                    <span className="text-[10px] text-slate-500 shrink-0">
                                                        {summary && summary.totalRowCount !== summary.rowCount ? `${summary.rowCount}/${summary.totalRowCount}줄 매칭` : `${summary?.rowCount ?? 0}줄`} · {(summary?.crsValues || []).join(', ') || 'CRS 기본값'}
                                                    </span>
                                                    <button onClick={() => handleRemoveEoFile(key)} className="p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded" title="EO 파일 제거"><Trash2 size={13} /></button>
                                                </div>
                                            );
                                        })}
                                    </div>
                                    {hasDuplicateEoImages && (
                                        <div className="mt-2 text-[11px] text-amber-700 bg-white/70 border border-amber-100 rounded-lg px-2 py-1.5">
                                            자동 제외 {duplicateIgnoredCount}행: {duplicateEoImages.slice(0, 5).map((item) => `${item.imageName}(${item.count - 1}행 제외)`).join(', ')}
                                        </div>
                                    )}
                                </div>
                            )}
                            <div className="flex-1 min-h-[460px] grid grid-cols-[0.9fr_1.1fr] gap-4">
                                <div className="min-h-[460px] flex flex-col bg-white rounded-xl border border-slate-200 overflow-hidden shadow-sm">
                                    <div className="p-3 border-b border-slate-100 bg-slate-50 flex justify-between items-center shrink-0"><span className="text-sm font-bold text-slate-700 flex items-center gap-2"><TableIcon size={16} className="text-slate-400" /> EO 행 선택</span>{eoFileName && <span className="text-[10px] text-blue-600 bg-blue-50 px-2 py-1 rounded font-bold">표 또는 지도에서 제외 가능</span>}</div>
                                    <div className="flex-1 overflow-auto custom-scrollbar relative">
                                        {!eoFileName ? (<div className="absolute inset-0 flex flex-col items-center justify-center text-slate-300"><FileText size={48} className="mb-3 opacity-30" /><p className="text-sm font-medium">상단에서 EO 파일을 로드하면<br />이곳에 미리보기가 표시됩니다.</p></div>) : (
                                            <table className="w-full min-w-[960px] text-sm text-left">
                                                <thead className="bg-slate-50 sticky top-0 z-10 text-slate-500 text-xs uppercase">
                                                    <tr>
                                                        <th className="p-3 border-b font-semibold w-[82px]">상태</th>
                                                        <th className="p-3 border-b font-semibold w-[15%]">EO 파일명</th>
                                                        <th className="p-3 border-b font-semibold w-[17%]">IMAGE_NAME ({eoConfig.columns.image_name})</th>
                                                        <th className="p-3 border-b font-semibold">X ({eoConfig.columns.x})</th>
                                                        <th className="p-3 border-b font-semibold">Y ({eoConfig.columns.y})</th>
                                                        <th className="p-3 border-b font-semibold">Z ({eoConfig.columns.z})</th>
                                                        <th className="p-3 border-b font-semibold">Omega ({eoConfig.columns.omega})</th>
                                                        <th className="p-3 border-b font-semibold">Phi ({eoConfig.columns.phi})</th>
                                                        <th className="p-3 border-b font-semibold">Kappa ({eoConfig.columns.kappa})</th>
                                                    </tr>
                                                </thead>
                                                <tbody className="divide-y divide-slate-100">
                                                    {parsedPreview.map((row) => (
                                                        <tr key={row.key} className={`${row.excluded ? 'bg-red-50/60 text-slate-400' : 'hover:bg-blue-50'} transition-colors group`}>
                                                            <td className="p-2">
                                                                {row.unmatched ? (
                                                                    <span className="inline-flex w-[62px] justify-center py-1 rounded border border-amber-200 bg-amber-50 text-[11px] font-bold text-amber-700">
                                                                        미매칭
                                                                    </span>
                                                                ) : (
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => toggleEoImageExcluded(row.imageKey)}
                                                                        className={`w-[62px] py-1 rounded border text-[11px] font-bold ${row.excluded ? 'bg-white border-blue-200 text-blue-700 hover:bg-blue-50' : 'bg-white border-red-200 text-red-600 hover:bg-red-50'}`}
                                                                    >
                                                                        {row.excluded ? '다시 포함' : '제외'}
                                                                    </button>
                                                                )}
                                                            </td>
                                                            <td className="p-3 text-xs text-slate-500 truncate max-w-[120px]" title={row.source_file}>{row.source_file}</td>
                                                            <td className={`p-3 font-mono font-medium ${row.excluded ? 'line-through text-slate-400' : 'text-slate-700 group-hover:text-blue-700'}`}>{row.image_name}</td>
                                                            <td className="p-3 font-mono text-slate-500">{row.x}</td>
                                                            <td className="p-3 font-mono text-slate-500">{row.y}</td>
                                                            <td className="p-3 font-mono text-slate-500">{row.z}</td>
                                                            <td className="p-3 font-mono text-slate-500">{row.omega}</td>
                                                            <td className="p-3 font-mono text-slate-500">{row.phi}</td>
                                                            <td className="p-3 font-mono text-slate-500">{row.kappa}</td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        )}
                                    </div>
                                    {eoFileName && eoLineCount > parsedPreview.length && (
                                        <div className="px-3 py-1.5 bg-slate-50 border-t border-slate-100 text-[11px] text-slate-500">
                                            표는 이미지와 매칭된 EO 중 상위 {parsedPreview.length}행만 표시합니다. 지도에는 매칭된 전체 고유 이미지 위치가 표시됩니다.
                                        </div>
                                    )}
                                </div>
                                <div className="min-h-[460px] bg-white rounded-xl border border-slate-200 overflow-hidden shadow-sm">
                                    <EoLocationPreview
                                        points={eoMapPoints}
                                        excludedCount={excludedEoImageKeys.size}
                                        onToggleExcluded={toggleEoImageExcluded}
                                        onBulkSetExcluded={setEoImagesExcluded}
                                        onClearExcluded={() => setExcludedEoImageKeys(new Set())}
                                    />
                                </div>
                            </div>
                        </div>
                    )}
                    {step === 3 && (
                        <div className="space-y-6 text-center max-w-2xl mx-auto h-full flex flex-col justify-center overflow-y-auto py-4">
                            <div className="space-y-1">
                                <h4 className="text-xl font-bold text-slate-800">3. 카메라 모델 (IO) 선택</h4>
                                <div className="text-xs text-slate-500">
                                    io.csv 기본 모델 {cameraModelCounts.standard}개 · 사용자 모델 {cameraModelCounts.custom}개
                                </div>
                            </div>
                            <div className="max-w-sm mx-auto space-y-6 w-full pb-4">
                                <div className="p-6 bg-slate-50 rounded-full w-32 h-32 mx-auto flex items-center justify-center border border-slate-200 shrink-0"><Camera size={56} className="text-slate-400" /></div>

	                                {isAddingCamera ? (
	                                    <div className="bg-white p-6 rounded-xl border border-blue-200 shadow-lg space-y-4 text-left animate-in fade-in zoom-in-95 duration-200">
	                                        <div className="flex justify-between items-center mb-2">
	                                            <h5 className="font-bold text-blue-600">{editingCameraId ? '카메라 모델 수정' : '새 카메라 추가'}</h5>
	                                            <button onClick={closeCameraForm} className="text-slate-400 hover:text-slate-600"><X size={16} /></button>
	                                        </div>
                                        <div className="space-y-1">
                                            <label className="text-xs font-bold text-slate-500">모델명</label>
                                            <input type="text" className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-blue-500 outline-none" value={newCamera.name} onChange={e => setNewCamera({ ...newCamera, name: e.target.value })} placeholder="Ex: Sony A7R IV" autoFocus />
                                        </div>
                                        <div className="grid grid-cols-2 gap-3">
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">초점거리 (mm)</label>
                                                <input type="number" className="w-full p-2 border rounded text-sm" value={newCamera.focal_length} onChange={e => setNewCamera({ ...newCamera, focal_length: parseFloat(e.target.value) })} />
                                            </div>
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">Pixel Size (µm)</label>
                                                <input type="number" className="w-full p-2 border rounded text-sm" value={newCamera.pixel_size} onChange={e => setNewCamera({ ...newCamera, pixel_size: parseFloat(e.target.value) })} />
                                            </div>
                                        </div>
                                        <div className="grid grid-cols-2 gap-3">
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">Sensor W (mm)</label>
                                                <input type="number" className="w-full p-2 border rounded text-sm" value={newCamera.sensor_width} onChange={e => setNewCamera({ ...newCamera, sensor_width: parseFloat(e.target.value) })} />
                                            </div>
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">Sensor H (mm)</label>
                                                <input type="number" className="w-full p-2 border rounded text-sm" value={newCamera.sensor_height} onChange={e => setNewCamera({ ...newCamera, sensor_height: parseFloat(e.target.value) })} />
                                            </div>
                                        </div>
                                        <div className="grid grid-cols-2 gap-3">
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">이미지 W (px)</label>
                                                <input type="number" className="w-full p-2 border rounded text-sm" value={newCamera.sensor_width_px} onChange={e => setNewCamera({ ...newCamera, sensor_width_px: parseInt(e.target.value) })} />
                                            </div>
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">이미지 H (px)</label>
                                                <input type="number" className="w-full p-2 border rounded text-sm" value={newCamera.sensor_height_px} onChange={e => setNewCamera({ ...newCamera, sensor_height_px: parseInt(e.target.value) })} />
                                            </div>
                                        </div>
                                        <div className="grid grid-cols-2 gap-3">
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">PPA X (mm)</label>
                                                <input type="number" step="0.001" className="w-full p-2 border rounded text-sm" value={newCamera.ppa_x} onChange={e => setNewCamera({ ...newCamera, ppa_x: parseFloat(e.target.value) })} />
                                            </div>
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">PPA Y (mm)</label>
                                                <input type="number" step="0.001" className="w-full p-2 border rounded text-sm" value={newCamera.ppa_y} onChange={e => setNewCamera({ ...newCamera, ppa_y: parseFloat(e.target.value) })} />
                                            </div>
                                        </div>
	                                        <button onClick={handleSaveCamera} className="w-full py-3 bg-blue-600 text-white rounded-lg font-bold text-sm hover:bg-blue-700 shadow-md mt-2">
                                                {editingCameraId ? '수정 저장' : '저장 및 선택'}
                                            </button>
	                                    </div>
	                                ) : (
	                                    <div className="space-y-3">
                                        <div className="relative">
                                            <select className="w-full p-4 border border-slate-300 rounded-xl bg-white font-bold text-lg focus:ring-2 focus:ring-blue-500 outline-none appearance-none" value={cameraModel} onChange={(e) => setCameraModel(e.target.value)}>
                                                {Array.isArray(cameraModels) && cameraModels.length > 0 ? (
                                                    cameraModels.map(c => (
                                                        <option key={c.id} value={c.name}>
                                                            {c.name}
                                                        </option>
                                                    ))
                                                ) : (
                                                    <option value="" disabled>카메라 모델 로딩 중...</option>
                                                )}
                                            </select>
	                                            <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-slate-500">▼</div>
	                                        </div>
                                            <div className="grid grid-cols-3 gap-2">
                                                <button onClick={openAddCameraForm} className="min-h-11 border-2 border-dashed border-blue-200 text-blue-600 rounded-xl hover:bg-blue-50 font-bold transition-colors flex items-center justify-center gap-1.5 text-xs">
                                                    <FilePlus size={16} /> 추가
                                                </button>
                                                <button onClick={openEditCameraForm} disabled={!selectedCamera?.id} className="min-h-11 border border-slate-200 text-slate-600 rounded-xl hover:bg-slate-50 font-bold transition-colors flex items-center justify-center gap-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-40">
                                                    <Pencil size={15} /> 수정
                                                </button>
                                                <button onClick={handleDeleteCamera} disabled={!selectedCamera?.id} className="min-h-11 border border-red-200 text-red-600 rounded-xl hover:bg-red-50 font-bold transition-colors flex items-center justify-center gap-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-40">
                                                    <Trash2 size={15} /> 삭제
                                                </button>
                                            </div>
	                                    </div>
	                                )}

                                <div className="bg-slate-50 p-5 rounded-xl text-left space-y-2 border border-slate-200">
                                    <div className="flex justify-between text-sm"><span className="text-slate-500">Focal Length</span><span className="font-mono font-bold text-slate-700">{selectedCamera.focal_length} mm</span></div>
                                    <div className="flex justify-between text-sm"><span className="text-slate-500">Sensor Size</span><span className="font-mono font-bold text-slate-700">{selectedCamera.sensor_width} x {selectedCamera.sensor_height} mm</span></div>
                                    <div className="flex justify-between text-sm"><span className="text-slate-500">Pixel Size</span><span className="font-mono font-bold text-slate-700">{selectedCamera.pixel_size} µm</span></div>
                                    {(selectedCamera.sensor_width_px && selectedCamera.sensor_height_px) && (
                                        <div className="flex justify-between text-sm"><span className="text-slate-500">Image Size</span><span className="font-mono font-bold text-slate-700">{selectedCamera.sensor_width_px} x {selectedCamera.sensor_height_px} px</span></div>
                                    )}
                                    {(selectedCamera.ppa_x != null || selectedCamera.ppa_y != null) && (
                                        <div className="flex justify-between text-sm"><span className="text-blue-600">PPA</span><span className="font-mono font-bold text-blue-700">({selectedCamera.ppa_x?.toFixed(3) || '0.000'}, {selectedCamera.ppa_y?.toFixed(3) || '0.000'}) mm</span></div>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}
                    {step === 4 && (
                        <div className="space-y-8 max-w-2xl mx-auto h-full flex flex-col justify-center">
                            <h4 className="text-2xl font-bold text-slate-800 text-center">4. 업로드 결과 요약</h4>
                            <div className="bg-white p-8 rounded-2xl border border-slate-200 shadow-lg space-y-6">
                                <div className="pb-4 border-b border-slate-100">
                                    <label className="text-slate-500 font-medium block mb-2">프로젝트 이름</label>
                                    <input
                                        type="text"
                                        value={projectName}
                                        onChange={(e) => setProjectName(e.target.value)}
                                        placeholder="프로젝트 이름을 입력하세요"
                                        className="w-full p-3 border border-slate-300 rounded-lg text-lg font-bold focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                                    />
                                    <p className="text-xs text-slate-400 mt-1">비워두면 자동으로 생성됩니다</p>
                                </div>
                                <div className="flex justify-between border-b border-slate-100 pb-4 items-center"><span className="text-slate-500 font-medium">입력 이미지</span><div className="text-right"><span className="text-xl font-bold text-slate-800">{imageCount}</span><span className="text-sm text-slate-400 ml-1">장</span></div></div>
                                <div className="flex justify-between border-b border-slate-100 pb-4 items-center"><span className="text-slate-500 font-medium">위치 데이터(EO)</span><div className="text-right"><div className="font-bold text-emerald-600 flex items-center gap-1 justify-end"><CheckCircle2 size={16} /> {eoFileName}</div><div className="text-xs text-slate-400 mt-1">{eoCrsValues[0] || eoConfig.crs} · 유효 {effectiveEoLineCount}줄{excludedEoImageKeys.size > 0 ? ` / 제외 ${excludedEoImageKeys.size}개` : ''}{hasDuplicateEoImages ? ` / 원본 ${eoLineCount}줄` : ''}</div></div></div>
                                <div className="flex justify-between border-b border-slate-100 pb-4 items-center"><span className="text-slate-500 font-medium">카메라 모델</span><span className="font-bold text-slate-800">{cameraModel}</span></div>
                                <div className="flex justify-between items-center pt-2"><span className="text-slate-500 font-medium">데이터 상태</span><span className="bg-blue-100 text-blue-700 px-3 py-1 rounded-full text-sm font-bold">준비 완료</span></div>
                                <label className={`flex items-center gap-3 pt-4 border-t border-slate-100 cursor-pointer ${!eoFileName ? 'opacity-50 cursor-not-allowed' : ''}`}>
                                    <input
                                        type="checkbox"
                                        checked={autoProcess && !!eoFileName}
                                        onChange={(e) => setAutoProcess(e.target.checked)}
                                        disabled={!eoFileName}
                                        className="w-5 h-5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                                    />
                                    <div>
                                        <span className="font-bold text-slate-700">완료 후 자동 처리</span>
                                        <p className="text-xs text-slate-400 mt-0.5">{eoFileName ? '프로젝트 생성 즉시 처리를 시작합니다' : 'EO 파일을 먼저 선택해주세요'}</p>
                                    </div>
                                </label>
                                {autoProcess && !!eoFileName && (
                                    <div className="ml-8 mt-2 flex items-center gap-3">
                                        <span className="text-sm text-slate-500">처리 모드</span>
                                        <select
                                            className="border border-slate-300 rounded-lg px-3 py-1.5 text-sm bg-white font-bold"
                                            value={processMode}
                                            onChange={(e) => setProcessMode(e.target.value)}
                                        >
                                            <option value="Normal">정밀 처리</option>
                                            <option value="Fast">고속 처리</option>
                                        </select>
                                        <span className="text-xs text-slate-400">{processMode === 'Normal' ? '품질 우선 (느림)' : '속도 우선 (빠름)'}</span>
                                    </div>
                                )}
                            </div>
                            <p className="text-center text-sm text-slate-500">{autoProcess && eoFileName ? <><span className="font-bold text-blue-600">확인</span> 버튼을 누르면 프로젝트가 생성되고 <span className="font-bold">즉시 처리가 시작</span>됩니다.</> : <><span className="font-bold text-slate-700">확인</span> 버튼을 누르면 프로젝트 처리 옵션 화면으로 이동합니다.</>}</p>
                        </div>
                    )}
                </div>
                {showMismatchWarning && (
                    <div className="absolute inset-0 z-[1100] flex items-center justify-center bg-black/40 backdrop-blur-sm">
                        <div className="bg-white rounded-xl shadow-2xl p-6 max-w-md animate-in zoom-in-95">
                            <div className="flex items-center gap-3 mb-4">
                                <div className="p-2 bg-amber-100 rounded-full text-amber-600"><AlertTriangle size={24} /></div>
                                <h4 className="font-bold text-slate-800">데이터 불일치</h4>
                            </div>
                            <p className="text-sm text-slate-600 mb-4">
                                이미지 수(<span className="font-bold text-blue-600">{imageCount}장</span>)와
                                EO 데이터 수(<span className="font-bold text-amber-600">{effectiveEoLineCount}줄</span>)가 일치하지 않습니다.
                            </p>
                            <p className="text-xs text-slate-500 mb-6">계속 진행하시겠습니까?</p>
                            <div className="flex gap-3">
                                <button onClick={() => setShowMismatchWarning(false)} className="flex-1 py-2.5 border border-slate-200 text-slate-600 rounded-lg font-medium hover:bg-slate-50">돌아가기</button>
                                <button onClick={handleConfirmMismatch} className="flex-1 py-2.5 bg-amber-500 text-white rounded-lg font-bold hover:bg-amber-600">계속 진행</button>
                            </div>
                        </div>
                    </div>
                )}
                <div className="h-20 border-t border-slate-200 px-8 flex items-center justify-between bg-slate-50">
                    <button onClick={handleCancelUpload} className="px-4 py-2 text-slate-400 hover:text-slate-600 text-sm">취소</button>
                    <div className="flex items-center gap-3">
                        {step > 1 && <button onClick={() => setStep(s => s - 1)} disabled={isFinishing} className="px-5 py-2.5 text-slate-500 font-bold hover:bg-slate-200 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed">이전</button>}
                        {step === 1 && <button onClick={() => setStep(2)} disabled={imageCount === 0} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm">확인</button>}
                        {step === 2 && <button onClick={() => setStep(3)} disabled={!eoFileName || hasMixedEoCrs || effectiveEoLineCount === 0} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm flex items-center gap-2">{hasMixedEoCrs ? '좌표계 확인 필요' : effectiveEoLineCount === 0 ? 'EO 확인 필요' : '다음'} <ArrowRight size={18} /></button>}
                        {step === 3 && <button onClick={handleProceedToStep4} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 transition-colors shadow-sm flex items-center gap-2">다음 <ArrowRight size={18} /></button>}
                        {step === 4 && <button onClick={handleFinish} disabled={isFinishing} className="px-8 py-2.5 bg-emerald-600 text-white rounded-lg font-bold hover:bg-emerald-700 flex items-center gap-2 shadow-md transition-all active:scale-95 disabled:opacity-60 disabled:cursor-wait disabled:active:scale-100">{isFinishing ? <RefreshCw size={18} className="animate-spin" /> : <CheckCircle2 size={18} />} {isFinishing ? '프로젝트 생성 중...' : '확인 및 설정 이동'}</button>}
                    </div>
                </div>
            </div>
        </div>
        <ServerFileBrowser
            isOpen={showFileBrowser}
            onClose={() => setShowFileBrowser(false)}
            onSelect={handleServerSelect}
            mode={fileBrowserMode}
        />
        <ServerFileBrowser
            isOpen={showEoFileBrowser}
            onClose={() => setShowEoFileBrowser(false)}
            onSelect={handleEoServerSelect}
            mode="eo"
            fileTypes="eo"
            initialPath={eoBrowserInitialPath}
        />
        </>
    );
}
