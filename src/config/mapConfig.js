/**
 * 지도 타일 설정
 *
 * 환경변수:
 * - VITE_MAP_OFFLINE: 'true'로 설정하면 오프라인 타일 사용
 * - VITE_TILE_URL: 커스텀 타일 URL (예: /tiles/{z}/{x}/{y}.png)
 */

export const MAP_CONFIG = {
    // 오프라인 모드 여부 (환경변수로 설정)
    offline: import.meta.env.VITE_MAP_OFFLINE === 'true',

    // 타일 URL 템플릿
    tileUrl: {
        // 오프라인: nginx를 통해 제공되는 로컬 타일
        offline: '/tiles/{z}/{x}/{y}.png',

        // 온라인: OpenStreetMap
        online: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    },

    // Attribution (출처 표시)
    attribution: {
        offline: '&copy; Local Tiles | Data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        online: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },

    // 서브도메인 (온라인 전용)
    subdomains: ['a', 'b', 'c'],

    // 기본 설정 (대한민국 중심)
    defaultCenter: [36.5, 127.5],
    defaultZoom: 7,
    maxZoom: 18,
    minZoom: 5,
};

/**
 * 현재 환경에 맞는 타일 설정 반환
 * @returns {Object} url, attribution, subdomains (온라인 전용)
 */
export const getTileConfig = () => {
    // 환경변수로 커스텀 URL이 설정된 경우 우선 사용
    const customUrl = import.meta.env.VITE_TILE_URL;
    if (customUrl) {
        return {
            url: customUrl,
            attribution: import.meta.env.VITE_TILE_ATTRIBUTION || MAP_CONFIG.attribution.offline,
            subdomains: undefined,
        };
    }

    const isOffline = MAP_CONFIG.offline;
    return {
        url: isOffline ? MAP_CONFIG.tileUrl.offline : MAP_CONFIG.tileUrl.online,
        attribution: isOffline ? MAP_CONFIG.attribution.offline : MAP_CONFIG.attribution.online,
        subdomains: isOffline ? undefined : MAP_CONFIG.subdomains,
    };
};

export default MAP_CONFIG;
