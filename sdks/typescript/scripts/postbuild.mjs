// dist/cjs holds CommonJS output inside a "type": "module" package; mark it so Node loads it as CommonJS.
import { writeFileSync } from "node:fs";

writeFileSync(new URL("../dist/cjs/package.json", import.meta.url), `${JSON.stringify({ type: "commonjs" }, null, 2)}\n`);
