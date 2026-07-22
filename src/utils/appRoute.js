export const DASHBOARD_ROUTE = Object.freeze({
  valid: true,
  viewMode: 'dashboard',
  projectId: null,
});

export function parseAppRoute(search = '') {
  const params = new URLSearchParams(search);
  const rawViewMode = params.get('viewMode');
  const projectId = (params.get('projectId') || '').trim();

  if (!rawViewMode && !projectId) {
    return { ...DASHBOARD_ROUTE };
  }
  if (rawViewMode === 'processing' && projectId) {
    return { valid: true, viewMode: 'processing', projectId };
  }
  return { valid: false, viewMode: 'dashboard', projectId: null };
}

export function buildAppRouteUrl(currentHref, route = DASHBOARD_ROUTE) {
  const url = new URL(currentHref, 'http://localhost');
  url.searchParams.delete('projectId');
  url.searchParams.delete('viewMode');

  if (route.viewMode === 'processing' && route.projectId) {
    url.searchParams.set('viewMode', 'processing');
    url.searchParams.set('projectId', route.projectId);
  }

  return `${url.pathname}${url.search}${url.hash}`;
}

function commitRoute(route, { replace = false } = {}) {
  const nextUrl = buildAppRouteUrl(window.location.href, route);
  const method = replace ? 'replaceState' : 'pushState';
  window.history[method](route, '', nextUrl);
}

export function setProcessingRoute(projectId, options) {
  commitRoute({ viewMode: 'processing', projectId }, options);
}

export function clearProjectRoute(options) {
  commitRoute(DASHBOARD_ROUTE, options);
}
