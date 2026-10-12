import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../api/openapi.json",
  output: { path: "src/lib/api/gen", postProcess: ["prettier"] },
  plugins: ["@hey-api/client-fetch", "zod", { name: "@hey-api/sdk", validator: true }, "@tanstack/react-query"],
});
