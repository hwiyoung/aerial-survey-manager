import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
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
        manualChunks: {
          'map-vendor': ['leaflet', 'react-leaflet', 'proj4'],
          'chart-vendor': ['recharts'],
        },
      },
    },
  },
})
