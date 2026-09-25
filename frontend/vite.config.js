import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    cssCodeSplit: false,
    rollupOptions: {
      input: fileURLToPath(new URL("./src/js/retorna.js", import.meta.url)),
      output: {
        entryFileNames: "retorna.js",
        chunkFileNames: "[name].js",
        assetFileNames: (assetInfo) => {
          const name = assetInfo.names?.[0] ?? assetInfo.name ?? "";
          return name.endsWith(".css") ? "retorna.css" : "[name][extname]";
        },
      },
    },
  },
});
