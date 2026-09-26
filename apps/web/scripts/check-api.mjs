import { readFile } from "node:fs/promises";
import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript";

const schema = JSON.parse(
  await readFile(new URL("../../../docs/api/openapi.json", import.meta.url), "utf8"),
);
const generated = COMMENT_HEADER + astToString(await openapiTS(schema));
const current = await readFile(new URL("../src/api/schema.ts", import.meta.url), "utf8");
if (generated !== current) {
  process.stderr.write("Generated API types are stale. Run npm run generate:api.\n");
  process.exitCode = 1;
}
