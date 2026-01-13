import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      // Make proj4-fully-loaded resolve to proj4 for better compatibility
      "proj4-fully-loaded": "proj4"
    },
  },
  optimizeDeps: {
    include: ['proj4', 'georaster', 'georaster-layer-for-leaflet']
  }
})