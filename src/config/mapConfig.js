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
        // 오프라인: nginx를 통해 제공되는 로컬 타일 (확장자 없음 - nginx가 자동 감지)
        offline: '/tiles/{z}/{x}/{y}',

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

    // 기본 설정 (대한민국 전체 - 제주도 포함)
    defaultCenter: [35.5, 127.5],
    defaultZoom: 7,
    minZoom: 5,

    // maxZoom: 모든 환경에서 16으로 통일
    maxZoom: {
        offline: 16,
        online: 16,
    },
};

/**
 * 현재 환경에 맞는 타일 설정 반환
 * @returns {Object} url, attribution, subdomains (온라인 전용)
 */
export const getTileConfig = () => {
    const isOffline = MAP_CONFIG.offline;
    const maxZoom = isOffline ? MAP_CONFIG.maxZoom.offline : MAP_CONFIG.maxZoom.online;

    // 환경변수로 커스텀 URL이 설정된 경우 우선 사용
    const customUrl = import.meta.env.VITE_TILE_URL;

    let config;
    if (customUrl) {
        config = {
            url: customUrl,
            attribution: import.meta.env.VITE_TILE_ATTRIBUTION || MAP_CONFIG.attribution.offline,
            subdomains: undefined,
            maxZoom: maxZoom,
        };
    } else {
        config = {
            url: isOffline ? MAP_CONFIG.tileUrl.offline : MAP_CONFIG.tileUrl.online,
            attribution: isOffline ? MAP_CONFIG.attribution.offline : MAP_CONFIG.attribution.online,
            subdomains: isOffline ? undefined : MAP_CONFIG.subdomains,
            maxZoom: maxZoom,
        };
    }

    // 디버깅용 로그 (첫 호출시에만)
    if (!getTileConfig._logged) {
        console.log('[MapConfig] Tile settings:', {
            VITE_MAP_OFFLINE: import.meta.env.VITE_MAP_OFFLINE,
            VITE_TILE_URL: import.meta.env.VITE_TILE_URL,
            isOffline,
            tileUrl: config.url,
        });
        getTileConfig._logged = true;
    }

    return config;
};

export default MAP_CONFIG;
