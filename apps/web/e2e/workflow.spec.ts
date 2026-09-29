import { Buffer } from "node:buffer";
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
  test.setTimeout(120_000);
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
  await expect(page.getByRole("heading", { name: "Project dashboard" })).toBeVisible();
  const compoundsMetric = page
    .locator(".dashboard .metric")
    .filter({ hasText: "Compounds" })
    .locator("b");
  await expect(compoundsMetric).toHaveText("0");
  const projectId = await page.locator("select").first().inputValue();
  expect(projectId).not.toBe("");
  await page.getByPlaceholder("Compound name").fill("Ethanol");
  await page.getByPlaceholder("SMILES (example: CCO)").fill("CCO");
  await page.getByRole("button", { name: "Standardize and register" }).click();
  await expect(page.getByText("CMP0001", { exact: true })).toBeVisible();
  await expect(compoundsMetric).toHaveText("1");
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
  await page.getByRole("button", { name: "Close viewer" }).click();

  const cube = [
    "CADD Suite browser fixture",
    "Synthetic 2 x 2 x 2 scalar field",
    "2 0.000000 0.000000 0.000000",
    "2 1.000000 0.000000 0.000000",
    "2 0.000000 1.000000 0.000000",
    "2 0.000000 0.000000 1.000000",
    "1 0.000000 0.000000 0.000000 0.000000",
    "1 0.000000 1.000000 0.000000 0.000000",
    "0.0 0.1 0.2 0.3 0.4 0.5 0.6 0.7",
  ].join("\n");
  await page.locator('input[type="file"]').setInputFiles({
    name: "browser-fixture.cube",
    mimeType: "chemical/x-gaussian-cube",
    buffer: Buffer.from(cube),
  });
  await page.getByRole("button", { name: "Upload artifact to project" }).click();
  await expect(page.getByText(/Uploaded to project CAS/)).toBeVisible();
  await page.getByRole("button", { name: "View cube" }).click();
  await expect(page.getByLabel("Volumetric cube viewer")).toBeVisible();
  await expect(page.locator(".molstar-host canvas").first()).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole("button", { name: "Close viewer" }).click();

  const topology = [
    "ATOM      1  C1  LIG A   1       1.000   1.000   1.000  1.00  0.00           C",
    "ATOM      2  O1  LIG A   1       2.000   1.000   1.000  1.00  0.00           O",
    "END",
  ].join("\n");
  const trajectory = [
    "ITEM: TIMESTEP",
    "0",
    "ITEM: NUMBER OF ATOMS",
    "2",
    "ITEM: BOX BOUNDS pp pp pp",
    "0 10",
    "0 10",
    "0 10",
    "ITEM: ATOMS id type x y z",
    "1 1 1 1 1",
    "2 2 2 1 1",
    "ITEM: TIMESTEP",
    "1",
    "ITEM: NUMBER OF ATOMS",
    "2",
    "ITEM: BOX BOUNDS pp pp pp",
    "0 10",
    "0 10",
    "0 10",
    "ITEM: ATOMS id type x y z",
    "1 1 1.1 1 1",
    "2 2 2.1 1 1",
  ].join("\n");
  for (const [name, mimeType, contents] of [
    ["browser-topology.pdb", "chemical/x-pdb", topology],
    ["browser-trajectory.lammpstrj", "text/plain", trajectory],
  ]) {
    await page.locator('input[type="file"]').setInputFiles({
      name,
      mimeType,
      buffer: Buffer.from(contents),
    });
    await page.getByRole("button", { name: "Upload artifact to project" }).click();
    await expect(page.getByText(/Uploaded to project CAS/)).toBeVisible();
  }
  const topologySelect = page.getByLabel("Topology");
  const trajectorySelect = page.getByLabel("Coordinates");
  const topologyOption = topologySelect.locator("option").filter({
    hasText: "browser-topology.pdb",
  });
  const trajectoryOption = trajectorySelect.locator("option").filter({
    hasText: "browser-trajectory.lammpstrj",
  });
  await topologySelect.selectOption((await topologyOption.getAttribute("value"))!);
  await trajectorySelect.selectOption((await trajectoryOption.getAttribute("value"))!);
  await expect(page.getByLabel("Molecular trajectory viewer")).toBeVisible();
  await expect(page.locator(".molstar-host canvas").first()).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole("button", { name: "Close viewer" }).click();

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
  await page.route(`${api}/v1/projects/${projectId}/dashboard`, async (route) => {
    const response = await route.fetch();
    const payload = (await response.json()) as Record<string, unknown>;
    payload.scientific_results = [
      {
        schema_version: "browser_fixture/1.0",
        task_id: ulid(),
        source_task_id: ulid(),
        stage_id: "fixture",
        task_state: "succeeded",
        subject_id: compounds[0].id,
        created_at: new Date().toISOString(),
        category: "browser_fixture",
        result_id: ulid(),
        identity: "UI payload only",
        method: "Playwright network fixture",
        values: { message: "not scientific evidence" },
        warnings: ["Test fixture only; not a scientific result."],
      },
    ];
    await route.fulfill({ response, json: payload });
  });
  await expect(page.getByText("browser fixture", { exact: true })).toBeVisible({
    timeout: 15_000,
  });
  await expect(
    page.getByText("Test fixture only; not a scientific result.", { exact: true }),
  ).toBeVisible();
});
