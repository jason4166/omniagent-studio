import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    Components({ resolvers: [ElementPlusResolver({ importStyle: false })], dts: false }),
  ],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:18080',
      '/health': 'http://127.0.0.1:18080',
      '/ready': 'http://127.0.0.1:18080',
    },
  },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'], restoreMocks: true },
})
