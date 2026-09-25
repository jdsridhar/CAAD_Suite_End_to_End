import createClient from "openapi-fetch";
import type { paths } from "./schema.js";

/** Typed JSON client for the FastAPI contract. Keep the bearer token in app state. */
export function createApiClient(baseUrl: string, token: string) {
  return createClient<paths>({
    baseUrl: baseUrl.replace(/\/$/, ""),
    headers: { Authorization: `Bearer ${token}` },
  });
}

/** Stream a raw input file; upload is deliberately separate from JSON OpenAPI calls. */
export async function uploadArtifact(
  baseUrl: string,
  token: string,
  projectId: string,
  file: File,
  role = "input",
): Promise<Response> {
  const response = await fetch(
    `${baseUrl.replace(/\/$/, "")}/v1/projects/${encodeURIComponent(projectId)}/artifacts`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": file.type || "application/octet-stream",
        "X-Filename": file.name,
        "X-Artifact-Role": role,
      },
      body: file,
    },
  );
  if (!response.ok) {
    throw new Error(`Artifact upload failed (${response.status}): ${await response.text()}`);
  }
  return response;
}
