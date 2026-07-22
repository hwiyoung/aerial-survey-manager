import assert from 'node:assert/strict';

import { buildAppRouteUrl, parseAppRoute } from '../src/utils/appRoute.js';

assert.deepEqual(parseAppRoute(''), {
  valid: true,
  viewMode: 'dashboard',
  projectId: null,
});
assert.deepEqual(parseAppRoute('?viewMode=processing&projectId=project-1'), {
  valid: true,
  viewMode: 'processing',
  projectId: 'project-1',
});
assert.equal(parseAppRoute('?viewMode=processing').valid, false);
assert.equal(parseAppRoute('?projectId=project-1').valid, false);
assert.equal(parseAppRoute('?viewMode=unknown&projectId=project-1').valid, false);
assert.equal(
  buildAppRouteUrl('https://example.test/app?keep=1&viewMode=processing&projectId=old#map'),
  '/app?keep=1#map',
);
assert.equal(
  buildAppRouteUrl('https://example.test/app?keep=1#map', {
    viewMode: 'processing',
    projectId: 'project 1',
  }),
  '/app?keep=1&viewMode=processing&projectId=project+1#map',
);

console.log('App route checks: PASS');
