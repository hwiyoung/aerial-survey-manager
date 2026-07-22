import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { readFileSync } from 'node:fs'

const appVersion = readFileSync(new URL('./VERSION', import.meta.url), 'utf8').trim()

const versionManifestPlugin = {
  name: 'version-manifest',
  transformIndexHtml(html) {
    return html.replace(
      '</head>',
      `    <meta name="app-version" content="${appVersion}" />\n  </head>`,
    )
  },
  generateBundle() {
    this.emitFile({
      type: 'asset',
      fileName: 'version.json',
      source: `${JSON.stringify({ version: appVersion })}\n`,
    })
  },
}

export default defineConfig({
  plugins: [react(), versionManifestPlugin],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  optimizeDeps: {
    include: ['proj4']
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (
            id.includes('/node_modules/leaflet/') ||
            id.includes('/node_modules/react-leaflet/') ||
            id.includes('/node_modules/proj4/')
          ) {
            return 'map-vendor'
          }
          if (id.includes('/node_modules/recharts/')) {
            return 'chart-vendor'
          }
        },
      },
    },
  },
})
