import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: process.env.LEARNING_LAB_API_URL || 'http://127.0.0.1:8765', changeOrigin: true } },
  },
  test: {
    include: ['tests/**/*.test.{mjs,ts,tsx}'],
    environment: 'jsdom',
    setupFiles: ['tests/setup.ts'],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
