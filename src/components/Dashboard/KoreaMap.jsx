import React, { useMemo } from 'react';

// Korea regions with approximate positions for simplified SVG map
const REGIONS = {
    '서울': { path: 'M 195 120 L 205 115 L 215 120 L 215 130 L 205 135 L 195 130 Z', center: [205, 125] },
    '경기': { path: 'M 170 100 L 240 100 L 250 160 L 170 170 L 160 130 Z', center: [205, 135] },
    '인천': { path: 'M 155 110 L 175 105 L 180 130 L 160 140 Z', center: [167, 120] },
    '강원': { path: 'M 240 80 L 310 100 L 320 180 L 250 170 L 230 120 Z', center: [275, 130] },
    '충북': { path: 'M 210 170 L 270 165 L 280 220 L 220 230 L 200 195 Z', center: [240, 195] },
    '충남': { path: 'M 130 170 L 200 165 L 210 230 L 140 250 L 110 210 Z', center: [165, 205] },
    '대전': { path: 'M 190 235 L 210 232 L 215 250 L 195 255 Z', center: [202, 243] },
    '세종': { path: 'M 175 220 L 190 218 L 192 235 L 177 238 Z', center: [183, 228] },
    '전북': { path: 'M 110 255 L 195 250 L 200 320 L 120 330 L 95 290 Z', center: [150, 290] },
    '전남': { path: 'M 80 330 L 180 320 L 200 400 L 100 420 L 60 370 Z', center: [130, 365] },
    '광주': { path: 'M 125 345 L 145 340 L 150 360 L 130 365 Z', center: [137, 352] },
    '경북': { path: 'M 250 175 L 340 180 L 350 280 L 260 290 L 235 230 Z', center: [295, 230] },
    '대구': { path: 'M 275 285 L 300 280 L 308 305 L 283 310 Z', center: [291, 295] },
    '경남': { path: 'M 200 310 L 300 300 L 330 380 L 220 400 L 180 350 Z', center: [255, 350] },
    '울산': { path: 'M 330 290 L 360 285 L 365 325 L 335 330 Z', center: [347, 305] },
    '부산': { path: 'M 310 365 L 350 355 L 360 390 L 325 400 Z', center: [335, 377] },
    '제주': { path: 'M 110 480 L 180 475 L 190 510 L 100 520 Z', center: [145, 495] },
};

// Status colors
const STATUS_COLORS = {
    completed: '#3b82f6',   // Blue
    processing: '#10b981',  // Green  
    pending: '#94a3b8',     // Gray
    error: '#ef4444',       // Red
};

/**
 * Simplified Korea Map Component
 * Shows regional processing status with color coding
 */
export function KoreaMap({ data = {}, onRegionClick, height = 400 }) {
    // Merge data with defaults
    const regionData = useMemo(() => {
        const result = {};
        Object.keys(REGIONS).forEach(region => {
            result[region] = data[region] || { status: 'pending', count: 0 };
        });
        return result;
    }, [data]);

    const getRegionColor = (region) => {
        const info = regionData[region];
        if (!info) return STATUS_COLORS.pending;

        // Determine dominant status
        if (info.status) return STATUS_COLORS[info.status] || STATUS_COLORS.pending;

        // Or use count-based logic
        if (info.completed > 0 && info.processing === 0) return STATUS_COLORS.completed;
        if (info.processing > 0) return STATUS_COLORS.processing;
        return STATUS_COLORS.pending;
    };

    return (
        <div className="bg-white rounded-xl p-5 shadow-sm border border-slate-100">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold text-slate-700">전국 처리 현황</h3>
                <div className="flex gap-3 text-xs">
                    <div className="flex items-center gap-1.5">
                        <div className="w-3 h-3 rounded" style={{ backgroundColor: STATUS_COLORS.completed }}></div>
                        <span className="text-slate-600">완료</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                        <div className="w-3 h-3 rounded" style={{ backgroundColor: STATUS_COLORS.processing }}></div>
                        <span className="text-slate-600">진행중</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                        <div className="w-3 h-3 rounded" style={{ backgroundColor: STATUS_COLORS.pending }}></div>
                        <span className="text-slate-600">대기</span>
                    </div>
                </div>
            </div>

            <svg
                viewBox="50 70 340 470"
                style={{ height, width: '100%' }}
                className="mx-auto"
            >
                {/* Render each region */}
                {Object.entries(REGIONS).map(([name, { path, center }]) => (
                    <g
                        key={name}
                        className="cursor-pointer transition-all hover:opacity-80"
                        onClick={() => onRegionClick && onRegionClick(name)}
                    >
                        <path
                            d={path}
                            fill={getRegionColor(name)}
                            stroke="white"
                            strokeWidth="2"
                            className="transition-colors"
                        />
                        {/* Region label for larger regions */}
                        {['경기', '강원', '충남', '전북', '전남', '경북', '경남'].includes(name) && (
                            <text
                                x={center[0]}
                                y={center[1]}
                                textAnchor="middle"
                                dominantBaseline="middle"
                                className="text-[8px] fill-white font-medium pointer-events-none"
                            >
                                {name}
                            </text>
                        )}
                    </g>
                ))}
            </svg>
        </div>
    );
}

/**
 * Region Stats Table - shows detailed stats per region
 */
export function RegionStatsTable({ data = [] }) {
    return (
        <div className="bg-white rounded-xl shadow-sm border border-slate-100 overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-100">
                <h3 className="text-sm font-bold text-slate-700">지역별 처리 현황</h3>
            </div>
            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead className="bg-slate-50">
                        <tr>
                            <th className="px-4 py-2 text-left font-medium text-slate-600">지역</th>
                            <th className="px-4 py-2 text-right font-medium text-slate-600">완료</th>
                            <th className="px-4 py-2 text-right font-medium text-slate-600">진행중</th>
                            <th className="px-4 py-2 text-right font-medium text-slate-600">데이터량</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                        {data.map((row, index) => (
                            <tr key={index} className="hover:bg-slate-50">
                                <td className="px-4 py-2.5 font-medium text-slate-700">{row.region}</td>
                                <td className="px-4 py-2.5 text-right text-emerald-600">{row.completed}</td>
                                <td className="px-4 py-2.5 text-right text-blue-600">{row.processing}</td>
                                <td className="px-4 py-2.5 text-right text-slate-500">{row.dataSize}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

export default KoreaMap;
