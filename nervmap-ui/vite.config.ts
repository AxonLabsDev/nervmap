import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

export default defineConfig({
  plugins: [preact()],
  build: {
    outDir: "../nervmap/web/static",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          three: ["three", "3d-force-graph"],
          codemirror: ["codemirror", "@codemirror/state", "@codemirror/view"],
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:9000",
      "/ws": { target: "ws://127.0.0.1:9000", ws: true },
    },
  },
});
