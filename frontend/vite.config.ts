import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 3000,
    proxy: {
      "/health": "http://localhost:8090",
      "/auth": "http://localhost:8090",
      "/claims": "http://localhost:8090",
      "/twin": "http://localhost:8090",
      "/graph": "http://localhost:8090",
      "/documents": "http://localhost:8090",
      "/interviews": "http://localhost:8090",
      "/projects": "http://localhost:8090",
      "/api": "http://localhost:8090",
      "/ws": { target: "ws://localhost:8090", ws: true },
    },
  },
});
