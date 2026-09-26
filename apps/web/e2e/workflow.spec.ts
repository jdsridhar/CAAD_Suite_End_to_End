import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
function ulid(): string {
  const alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  let random = 0n;
  for (const byte of crypto.getRandomValues(new Uint8Array(10)))
    random = (random << 8n) | BigInt(byte);
  let value = (BigInt(Date.now()) << 80n) | random;
  let out = "";
  for (let i = 0; i < 26; i++) {
    out = alphabet[Number(value & 31n)] + out;
    value >>= 5n;
  }
  return out;
}
test("project compound workflow pauses for a decision and resumes successfully", async ({
  page,
}) => {
  const api = "http://127.0.0.1:8100",
    token = "browser-e2e-token",
    slug = `browser-e2e-${Date.now()}`;
  await page.goto("/");
  await page.getByLabel("API base URL").fill(api);
  await page.getByLabel("Access token").fill(token);
  await page.getByRole("button", { name: "Connect API" }).click();
  await expect(page.getByText("API CONNECTED")).toBeVisible();
  await expect(page.getByText("1 installed stages")).toBeVisible();
  await page.getByText("Installed stage capabilities").click();
  await expect(page.getByText("e2e.review_candidate / generic")).toBeVisible();
  await page.getByPlaceholder("Project name").fill("Browser E2E project");
  await page.getByPlaceholder("lowercase-project-slug").fill(slug);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByText(`Project created: ${slug}`)).toBeVisible();
  const projectId = await page.locator("select").first().inputValue();
  expect(projectId).not.toBe("");
  await page.getByPlaceholder("Compound name").fill("Ethanol");
  await page.getByPlaceholder("SMILES (example: CCO)").fill("CCO");
  await page.getByRole("button", { name: "Standardize and register" }).click();
  await expect(page.getByText("CMP0001", { exact: true })).toBeVisible();
  const response = await page.request.get(
    `${api}/v1/projects/${projectId}/compounds`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect(response.ok()).toBeTruthy();
  const compounds = (await response.json()) as Array<{ id: string }>;
  expect(compounds).toHaveLength(1);

  const receptorComplex = await readFile(
    new URL(
      "../../../tests/data/golden/docking_g1/results/RC8__5NIU_complex.pdb",
      import.meta.url,
    ),
  );
  await page.locator('input[type="file"]').setInputFiles({
    name: "RC8_5NIU_complex.pdb",
    mimeType: "chemical/x-pdb",
    buffer: receptorComplex,
  });
  await page
    .getByRole("button", { name: "Upload artifact to project" })
    .click();
  await expect(page.getByText(/Uploaded to project CAS/)).toBeVisible();
  await page.getByRole("button", { name: "View in Mol*" }).click();
  await expect(page.getByLabel("Molecular structure viewer")).toBeVisible();
  await expect(page.locator(".molstar-host canvas").first()).toBeVisible({
    timeout: 30_000,
  });
  const workflow = {
    schema: "caddsuite.workflow/1",
    name: "Browser decision-resume workflow",
    inputs: { candidate: { contract: "candidate/1.0" } },
    stages: [
      {
        id: "review",
        kind: "e2e.review_candidate",
        input_contracts: { candidate: "candidate/1.0" },
        input_bindings: { candidate: "$candidate" },
        output_contract: "candidate/1.0",
        params: {},
      },
    ],
    outputs: { candidate: "review" },
  };
  await page.locator(".advanced-workflow summary").click();
  await page
    .locator(".advanced-workflow textarea")
    .fill(JSON.stringify(workflow, null, 2));
  const candidate = {
    schema_version: "candidate/1.0",
    id: ulid(),
    compound_id: compounds[0].id,
    project_id: projectId,
    status: "active",
    reason_evidence_ids: [],
  };
  await page
    .locator("textarea.inputs")
    .fill(JSON.stringify({ candidate }, null, 2));
  await page.getByRole("button", { name: "Validate and plan" }).click();
  await expect(
    page.getByText("Workflow compiled against installed capabilities"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Queue workflow" }).click();
  await expect(
    page.getByText("Choose how to handle this candidate."),
  ).toBeVisible();
  await page
    .getByPlaceholder("Your name or identifier")
    .fill("browser-e2e-reviewer");
  await page.getByRole("button", { name: /Continue candidate/ }).click();
  const monitor = page
    .locator(".panel")
    .filter({ hasText: "06 / Run monitor" });
  await expect(
    monitor.locator(".pill").filter({ hasText: "succeeded" }),
  ).toBeVisible({ timeout: 20000 });
  await page.getByRole("button", { name: "Inspect run provenance" }).click();
  await expect(page.getByText("Run provenance loaded")).toBeVisible();
  await expect(page.getByText("Recent project runs")).toBeVisible();
});
