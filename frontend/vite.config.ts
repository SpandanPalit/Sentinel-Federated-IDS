import { defineConfig } from "vite";
import { copyFileSync, mkdirSync } from "node:fs";
export default defineConfig({
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/docs": "http://127.0.0.1:8000",
    },
  },
  plugins: [
    {
      name: "sentinel-offline-docs",
      closeBundle() {
        mkdirSync("dist/swagger", { recursive: true });
        for (const asset of [
          "swagger-ui-bundle.js",
          "swagger-ui.css",
          "favicon-32x32.png",
          "LICENSE",
        ])
          copyFileSync(
            "node_modules/swagger-ui-dist/" + asset,
            "dist/swagger/" + asset,
          );
      },
    },
  ],
});
