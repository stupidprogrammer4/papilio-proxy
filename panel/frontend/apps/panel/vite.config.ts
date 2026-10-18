import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  if (!env.PAPILIO_BACKEND_URL || !env.PAPILIO_PANEL_PORT) throw new Error("Configure PAPILIO_BACKEND_URL and PAPILIO_PANEL_PORT");
  const fileWatcher = process.env.PAPILIO_DISABLE_FILE_WATCHER === "true" ? null : undefined;
  const listener = {
    host: "127.0.0.1", port: Number(env.PAPILIO_PANEL_PORT), strictPort: true,
    proxy: { "/api": { target: env.PAPILIO_BACKEND_URL, changeOrigin: false, rewrite: (path: string) => path.replace(/^\/api/, "") } },
  };
  return {
    plugins: [vue()],
    server: { ...listener, watch: fileWatcher },
    preview: listener,
  };
});
