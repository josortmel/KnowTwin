import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import electron from "vite-plugin-electron/simple";
import path from "path";

// Electron desktop app (DESIGN.md §8). The renderer targets Electron's bundled
// Chromium; the preload is forced to CommonJS because §4 requires sandbox:true,
// and sandboxed preloads cannot be ES modules. All API traffic goes through the
// main-process bridge (window.knowtwin) — the renderer never fetches directly.
export default defineConfig({
  base: "./",
  plugins: [
    react(),
    electron({
      main: {
        entry: "src/main.ts",
        vite: {
          build: {
            outDir: "dist-electron",
            // electron-store + ws stay external (CJS, resolved at runtime from
            // node_modules) — bundling their file/native deps is fragile.
            rollupOptions: { external: ["electron", "electron-store", "ws"] },
          },
        },
      },
      preload: {
        input: "src/preload.ts",
        vite: {
          build: {
            outDir: "dist-electron",
            rollupOptions: {
              external: ["electron"],
              output: { format: "cjs", entryFileNames: "preload.js" },
            },
          },
        },
      },
      renderer: process.env.NODE_ENV === "test" ? undefined : {},
    }),
  ],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    outDir: "dist",
    // Emit every asset as a same-origin file. The prod CSP (§4) has no font-src,
    // so inlined data: fonts would be refused — keep fonts as files under 'self'.
    assetsInlineLimit: 0,
  },
  server: {
    port: 3001,
  },
});
