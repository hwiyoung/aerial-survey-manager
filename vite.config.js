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
