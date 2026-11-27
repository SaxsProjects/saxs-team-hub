/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { cpSync, existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as { version: string };

/** pdf.js draws PDFs' standard fonts (Helvetica, Times…) from these files; serve them in dev and ship them in the build. */
function pdfStandardFonts(): Plugin {
  const source = fileURLToPath(new URL("./node_modules/pdfjs-dist/standard_fonts", import.meta.url));
  const route = "/assets/pdfjs/standard_fonts/";
  let outDir = "dist";
  return {
    name: "pdfjs-standard-fonts",
    configResolved: (c) => void (outDir = c.build.outDir),
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const name = req.url?.startsWith(route) ? req.url.slice(route.length).split("?")[0] : "";
        const file = name && /^[\w.-]+$/.test(name) ? join(source, name) : "";
        if (!file || !existsSync(file)) return next();
        res.setHeader("Content-Type", "application/octet-stream");
        res.end(readFileSync(file));
      });
    },
    writeBundle: () => cpSync(source, join(outDir, "assets/pdfjs/standard_fonts"), { recursive: true }),
  };
}

export default defineConfig({
  plugins: [react(), pdfStandardFonts()],
  define: { __APP_VERSION__: JSON.stringify(version) },
  server: { port: 5173 },
  build: { sourcemap: false, target: "es2022" },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
