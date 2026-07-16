export const EO_CRS_OPTIONS = [
    { value: 'EPSG:5186', label: 'TM 중부 (EPSG:5186)' },
    { value: 'EPSG:5185', label: 'TM 서부 (EPSG:5185)' },
    { value: 'EPSG:5187', label: 'TM 동부 (EPSG:5187)' },
    { value: 'EPSG:5188', label: 'TM 동해 (EPSG:5188)' },
    { value: 'EPSG:5179', label: 'UTM-K (EPSG:5179)' },
    { value: 'EPSG:4326', label: 'WGS84 (EPSG:4326)' },
];

export const EO_CRS_LABEL_BY_CODE = Object.fromEntries(
    EO_CRS_OPTIONS.map((option) => [option.value, option.label])
);

export function normalizeCrsCode(value, fallback = null) {
    const text = String(value || '').trim();
    if (!text) return fallback;
    const match = text.match(/(?:EPSG[:\s]*)?(\d{4,5})/i);
    return match ? `EPSG:${match[1]}` : fallback;
}

export function formatCrsLabel(value) {
    const code = normalizeCrsCode(value);
    return code ? (EO_CRS_LABEL_BY_CODE[code] || code) : '확인되지 않음';
}
