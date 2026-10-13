import { Buffer } from "node:buffer";
import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

const api = "http://127.0.0.1:8100";
const token = "browser-e2e-token"; // Explicit local UI fixture credential.

function ulid(): string {
  const alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  let random = 0n;
  for (const byte of crypto.getRandomValues(new Uint8Array(10))) random = (random << 8n) | BigInt(byte);
  let value = (BigInt(Date.now()) << 80n) | random, out = "";
  for (let i = 0; i < 26; i++) { out = alphabet[Number(value & 31n)] + out; value >>= 5n; }
  return out;
}

async function connectAndCreate(page: Page) {
  const slug = "browser-e2e-" + Date.now();
  await page.goto("/");
  await expect(page.getByLabel("Getting started")).toBeVisible();
  await page.getByRole("button", { name: "Open connection settings" }).click();
  await expect(page.getByLabel("Access token")).toHaveValue("");
  await page.getByLabel("API base URL").fill(api);
  await page.getByLabel("Access token").fill(token);
  await page.getByRole("button", { name: "Connect to API" }).click();
  await expect(page.getByText("API CONNECTED")).toBeVisible();
  await page.getByPlaceholder(/Project name/).fill("Browser UI fixture project");
  await page.getByPlaceholder(/slug \(e.g./).fill(slug);
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Project created:" })).toBeVisible();
  const projectId = await page.locator("header select").inputValue();
  expect(projectId).not.toBe("");
  return projectId;
}

async function upload(page: Page, name: string, mimeType: string, buffer: Buffer) {
  await page.locator('input[type="file"]').setInputFiles({ name, mimeType, buffer });
  await page.getByRole("button", { name: "Upload structure file" }).click();
  await expect(page.getByRole("status").filter({ hasText: /Uploaded to project CAS/ })).toContainText(name);
}

test("guided setup, real registry, previews, and decision-resume workflow", async ({ page }) => {
  test.setTimeout(120_000);
  const projectId = await connectAndCreate(page);
  await page.getByRole("button", { name: /Ligand Registry/ }).click();
  await page.getByLabel("Compound name / identifier").fill("Ethanol");
  await page.getByLabel("SMILES string").fill("CCO");
  await page.getByRole("button", { name: "Standardize & register compound" }).click();
  await expect(page.getByText("CMP0001", { exact: true })).toBeVisible();
  const response = await page.request.get(api + "/v1/projects/" + projectId + "/compounds",
    { headers: { Authorization: "Bearer " + token } });
  expect(response.ok()).toBeTruthy();
  const compounds = await response.json();
  expect(compounds).toHaveLength(1);

  await page.getByRole("button", { name: /Pipeline Studio/ }).click();
  const admet = page.getByRole("button", { name: /ADMET Screening/ });
  await admet.focus();
  await page.keyboard.press("Enter");
  await expect(admet).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: /3D Molecular Studio/ }).click();
  const complex = await readFile(new URL(
    "../../../tests/data/golden/docking_g1/results/RC8__5NIU_complex.pdb", import.meta.url));
  await upload(page, "RC8_5NIU_complex.pdb", "chemical/x-pdb", complex);
  await page.getByRole("button", { name: "View in Mol*", exact: true }).click();
  await expect(page.getByLabel("Molecular structure viewer")).toBeVisible();
  await expect(page.locator(".molstar-host canvas").first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Close viewer", exact: true }).click();

  const workflow = {
    schema: "caddsuite.workflow/1", name: "UI fixture decision workflow",
    inputs: { candidate: { contract: "candidate/1.0" } },
    stages: [{ id: "review", kind: "e2e.review_candidate",
      input_contracts: { candidate: "candidate/1.0" },
      input_bindings: { candidate: "$candidate" }, output_contract: "candidate/1.0", params: {} }],
    outputs: { candidate: "review" },
  };
  await page.getByRole("button", { name: /Pipeline Studio/ }).click();
  await page.getByText(/Advanced: Raw Workflow JSON/).click();
  await page.locator(".advanced-workflow textarea").fill(JSON.stringify(workflow));
  await page.getByRole("button", { name: /3D Molecular Studio/ }).click();
  await page.getByText(/Advanced: Raw Input Contracts JSON/).click();
  await page.locator("textarea.inputs").fill(JSON.stringify({ candidate: {
    schema_version: "candidate/1.0", id: ulid(), compound_id: compounds[0].id,
    project_id: projectId, status: "active", reason_evidence_ids: [],
  } }));
  await page.getByRole("button", { name: /Pipeline Studio/ }).click();
  await page.getByRole("button", { name: "Validate & Plan" }).click();
  await expect(page.getByRole("status").filter({ hasText: /compiled successfully/ })).toBeVisible();
  await page.getByRole("button", { name: /Queue Pipeline/ }).click();
  await expect(page.getByText("Choose how to handle this candidate.")).toBeVisible();
  await page.getByPlaceholder("Your name or identifier").fill("browser-e2e-reviewer");
  await page.getByRole("button", { name: /Continue candidate/ }).click();
  const progress = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Execution progress" }) });
  await expect(progress.locator(".pill").filter({ hasText: "succeeded" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Inspect run provenance artifacts" }).click();
  await expect(page.getByText("Run provenance loaded")).toBeVisible();
  await page.getByRole("button", { name: /Overview & Evidence/ }).click();
  await expect(page.getByRole("heading", { name: "Project dashboard" })).toBeVisible();
  await expect(page.locator(".dashboard-run").getByText("succeeded", { exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/workspace-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "test-results/workspace-mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test("recorded metrics retain methods and download with authentication", async ({ page }) => {
  const projectId = await connectAndCreate(page);
  await page.getByRole("button", { name: /3D Molecular Studio/ }).click();
  // These uploads and route payloads are UI fixtures only. Backend scoping/hash checks
  // are separately exercised by test_recorded_trajectory_preview.py.
  await upload(page, "browser-topology.pdb", "chemical/x-pdb", Buffer.from(
    "ATOM      1  C1  LIG A   1       1.000   1.000   1.000  1.00  0.00           C\nEND\n"));
  await upload(page, "browser-trajectory.xtc", "application/octet-stream", Buffer.from("UI fixture only"));
  const topology = page.getByRole("combobox", { name: "Topology", exact: true });
  const coords = page.getByRole("combobox", { name: "Coordinates", exact: true });
  const topId = await topology.locator("option").filter({ hasText: "browser-topology.pdb" }).getAttribute("value");
  const trajId = await coords.locator("option").filter({ hasText: "browser-trajectory.xtc" }).getAttribute("value");
  const load = page.getByRole("button", { name: /Load recorded analysis/ });
  await expect(load).toBeDisabled();
  await topology.selectOption(topId!);
  await coords.selectOption(trajId!);
  const metricId = ulid();
  await page.route(api + "/v1/projects/" + projectId + "/trajectories/analyze?**", async (route) => {
    const requested = new URL(route.request().url());
    expect(requested.searchParams.get("topology_artifact_id")).toBe(topId);
    expect(requested.searchParams.get("trajectory_artifact_id")).toBe(trajId);
    await route.fulfill({ json: {
      status: "recorded", result_id: ulid(), task_id: ulid(), run_id: ulid(),
      analyzer: { name: "Explicit UI fixture only", version: "1" },
      warnings: ["UI fixture; not a scientific result."],
      metrics: [{ name: "rg", unit: "A", axis: "time_ns", x: [0, 1], values: [2, 4],
        artifact_id: metricId, summary: { mean: 3 }, window_ns: [0, 1],
        definition: { target_selection: "protein", fit_selection: null,
          refit: null, weighting: "mass", notes: "Explicit fixture methodology" } }],
    } });
  });
  await page.route(api + "/v1/projects/" + projectId + "/artifacts/" + metricId + "/content", async (route) => {
    expect(route.request().headers().authorization).toBe("Bearer " + token);
    await route.fulfill({ contentType: "text/csv", body: "time_ns,value\n0,2\n1,4\n" });
  });
  await load.click();
  await expect(page.getByLabel("Recorded trajectory analysis")).toBeVisible();
  await expect(page.getByText("UI fixture; not a scientific result.")).toBeVisible();
  await page.getByText("Method and recorded summary").click();
  await expect(page.getByText("Explicit fixture methodology")).toBeVisible();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download CSV" }).click();
  expect((await downloaded).suggestedFilename()).toBe("rg.csv");
  await topology.selectOption("");
  await expect(page.getByLabel("Recorded trajectory analysis")).not.toBeVisible();
});


test("cube and compatible trajectory previews preserve their existing viewer paths", async ({ page }) => {
  test.setTimeout(90_000);
  await connectAndCreate(page);
  await page.getByRole("button", { name: /3D Molecular Studio/ }).click();
  const cube = [
    "Explicit UI cube fixture", "Synthetic 2 x 2 x 2 scalar field",
    "2 0.000000 0.000000 0.000000", "2 1.000000 0.000000 0.000000",
    "2 0.000000 1.000000 0.000000", "2 0.000000 0.000000 1.000000",
    "1 0.000000 0.000000 0.000000 0.000000",
    "1 0.000000 1.000000 0.000000 0.000000", "0.0 0.1 0.2 0.3 0.4 0.5 0.6 0.7",
  ].join("\n");
  await upload(page, "browser-fixture.cube", "chemical/x-gaussian-cube", Buffer.from(cube));
  await page.getByRole("button", { name: "View cube", exact: true }).click();
  await expect(page.getByLabel("Volumetric cube viewer")).toBeVisible();
  await expect(page.locator(".molstar-host canvas").first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Close viewer", exact: true }).click();
  const topology = [
    "ATOM      1  C1  LIG A   1       1.000   1.000   1.000  1.00  0.00           C",
    "ATOM      2  O1  LIG A   1       2.000   1.000   1.000  1.00  0.00           O", "END",
  ].join("\n");
  const frames = [0, 1].map((frame) => [
    "ITEM: TIMESTEP", String(frame), "ITEM: NUMBER OF ATOMS", "2",
    "ITEM: BOX BOUNDS pp pp pp", "0 10", "0 10", "0 10", "ITEM: ATOMS id type x y z",
    "1 1 " + (1 + frame * 0.1) + " 1 1", "2 2 " + (2 + frame * 0.1) + " 1 1",
  ].join("\n")).join("\n");
  await upload(page, "two-atom-topology.pdb", "chemical/x-pdb", Buffer.from(topology));
  await upload(page, "two-atom-trajectory.lammpstrj", "text/plain", Buffer.from(frames));
  const tops = page.getByRole("combobox", { name: "Topology", exact: true });
  const coords = page.getByRole("combobox", { name: "Coordinates", exact: true });
  await tops.selectOption((await tops.locator("option").filter({ hasText: "two-atom-topology" }).getAttribute("value"))!);
  await coords.selectOption((await coords.locator("option").filter({ hasText: "two-atom-trajectory" }).getAttribute("value"))!);
  await expect(page.getByLabel("Molecular trajectory viewer")).toBeVisible();
  await expect(page.locator(".molstar-host canvas").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByLabel("Molecular trajectory viewer").locator(".alert")).not.toBeVisible();
});

test("engine configuration displays discovered readiness and supports editable path overrides", async ({ page }) => {
  test.setTimeout(60_000);
  await connectAndCreate(page);
  await page.getByRole("button", { name: /Projects & API/ }).click();
  await expect(page.getByRole("heading", { name: "Scientific Engine Configuration & Readiness" })).toBeVisible();
  await expect(page.getByText("Docking (Vina / Meeko):")).toBeVisible();
  await expect(page.getByText("Molecular Dynamics (GROMACS):")).toBeVisible();
  await expect(page.getByText("Quantum Chemistry (Psi4):")).toBeVisible();
  await expect(page.getByText("MM-PBSA (gmx_MMPBSA):")).toBeVisible();

  const vinaInput = page.getByLabel("AutoDock Vina executable");
  await expect(vinaInput).toBeVisible();
  await vinaInput.fill("/usr/local/bin/vina");
  await page.getByRole("button", { name: "Save & Apply paths" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Engine configuration saved to local storage." })).toBeVisible();

  await page.getByRole("button", { name: "Reset to auto-discovered" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Engine configuration reset to auto-discovered defaults." })).toBeVisible();
});

test("guided preparation, explicit DFT plans, and project deletion lifecycle", async ({ page }) => {
  test.setTimeout(60_000);
  const projectId = await connectAndCreate(page);

  // Register a compound in the Ligand Registry
  await page.getByRole("button", { name: /Ligand Registry/ }).click();
  await page.getByLabel("Compound name / identifier").fill("Aspirin");
  await page.getByLabel("SMILES string").fill("CC(=O)Oc1ccccc1C(=O)O");
  await page.getByRole("button", { name: "Standardize & register compound" }).click();
  await expect(page.getByText("CMP0001", { exact: true })).toBeVisible();

  // Navigate to Pipeline Studio
  await page.getByRole("button", { name: /Pipeline Studio/ }).click();

  // 1. Verify Guided Receptor Preparation Controls
  await page.getByRole("button", { name: /ADMET \+ AutoDock Vina/ }).click();
  await expect(page.getByText("RECEPTOR SPECIFICATION")).toBeVisible();
  const phInput = page.getByLabel("Receptor pH");
  await expect(phInput).toBeVisible();
  await phInput.fill("7.0");
  const altlocSelect = page.getByLabel("Altloc / Model Policy");
  await expect(altlocSelect).toBeVisible();
  await altlocSelect.selectOption("highest_occupancy_single_model");
  await altlocSelect.selectOption("require_full_occupancy");

  // 2. Verify Explicit QM / DFT Specification Controls
  await page.getByRole("button", { name: /Ligand DFT/ }).click();
  await expect(page.getByText("EXPLICIT QM CALCULATION PLAN")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Electronic Structure & DFT Specification" })).toBeVisible();

  const functionalSelect = page.getByLabel("DFT Functional / Method");
  await expect(functionalSelect).toBeVisible();
  await functionalSelect.selectOption("wb97x-d");

  const basisSelect = page.getByLabel("Basis Set");
  await expect(basisSelect).toBeVisible();
  await basisSelect.selectOption("6-31g*");

  const protocolSelect = page.getByLabel("Calculation Protocol");
  await expect(protocolSelect).toBeVisible();
  await protocolSelect.selectOption("optimization");

  const solvationSelect = page.getByLabel("Solvation Model");
  await expect(solvationSelect).toBeVisible();
  await solvationSelect.selectOption("water");

  const explicitFormId = ulid();
  const explicitConfId = ulid();
  const formIdInput = page.getByLabel("Target Form / Microstate ID (ULID)");
  await expect(formIdInput).toBeVisible();
  await formIdInput.fill(explicitFormId);

  const confIdInput = page.getByLabel("Target Conformer / Geometry ID (ULID)");
  await expect(confIdInput).toBeVisible();
  await confIdInput.fill(explicitConfId);

  // Verify generated inputs JSON contains explicit contracts and zero placeholders
  await page.getByRole("button", { name: /3D Molecular Studio/ }).click();
  await page.getByText(/Advanced: Raw Input Contracts JSON/).click();
  const inputsArea = page.locator("textarea.inputs");
  const inputsText = await inputsArea.inputValue();
  expect(inputsText).toContain('"optimization"');
  expect(inputsText).toContain('"ddx_pcm"');
  expect(inputsText).toContain(explicitFormId);
  expect(inputsText).toContain(explicitConfId);
  expect(inputsText).not.toContain("00000000000000000000000000");

  // 3. Compile/Plan Workflow against discovered capabilities
  await page.getByRole("button", { name: /Pipeline Studio/ }).click();
  await page.getByRole("button", { name: "Validate & Plan" }).click();
  await expect(page.getByRole("status").filter({ hasText: /compiled successfully/ })).toBeVisible();

  // 4. Test Project Lifecycle & Deletion Confirmation
  await page.getByRole("button", { name: /Projects & API/ }).click();
  page.once("dialog", (dialog) => {
    expect(dialog.message()).toContain("Are you sure you want to delete project");
    void dialog.accept();
  });
  await page.getByRole("button", { name: "Delete project" }).click();
  await expect(page.getByRole("status").filter({ hasText: /Project deleted/ })).toBeVisible();
});


