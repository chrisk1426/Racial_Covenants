import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/books': 'http://localhost:8000',
      '/scan': 'http://localhost:8000',
      '/detections': 'http://localhost:8000',
      '/stats': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/page-image': 'http://localhost:8000',
    },
  },
})
