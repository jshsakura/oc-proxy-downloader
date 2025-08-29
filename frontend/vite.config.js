import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: 'build'
  },
  server: {
    port: 3000,
    host: '0.0.0.0',
    proxy: {
      // string shorthand
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true
      }
    }
  }
})
