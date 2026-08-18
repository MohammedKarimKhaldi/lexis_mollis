import { createRequire } from "node:module";

import { defineConfig } from "astro/config";

const require = createRequire(import.meta.url);
const graphologyCjs = require.resolve("graphology");

export default defineConfig({
  output: "static",
  site: "https://lexis-mollis.org",
  build: {
    format: "directory"
  },
  vite: {
    resolve: {
      // Vite 8's dev import analysis mistakes Graphology's `import(...)`
      // class method for a dynamic import and emits invalid JavaScript. The
      // equivalent CommonJS build names the method through the prototype and
      // avoids that transform while preserving Graphology's public API.
      alias: [{ find: /^graphology$/, replacement: graphologyCjs }]
    }
  }
});
