import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const root = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      "/@vite/env": path.join(root, "node_modules/vite/dist/client/env.mjs"),
    },
  },
  test: { environment: "node" },
});
