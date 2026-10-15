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
  await expect(page.getByText("API CONNECTED")).toBeVisible({ timeout: 30_000 });
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

test.describe("guided trajectory analysis", () => {
  let projectId: string;
  let taskId: string;
  let topologyId: string;
  let trajectoryId: string;

  test.beforeEach(async ({ page }) => {
    test.setTimeout(90_000);
    projectId = await connectAndCreate(page);
    taskId = ulid(); topologyId = ulid(); trajectoryId = ulid();
    // Metadata and intercepted requests only; these fixtures do not run scientific engines.
    const artifact = (id: string, name: string) => ({
      id, original_name: name, kind: "ui_fixture", media_type: "application/octet-stream",
      sha256: "a".repeat(64), size_bytes: 1,
    });
    await page.route(api + "/v1/projects/" + projectId + "/dashboard", async (route) => {
      const original = await route.fetch();
      await route.fulfill({ json: { ...await original.json(), trajectory_options: [{
        task_id: taskId, run_id: ulid(), accession: "MD UI fixture", stage_id: "production",
        stage_kind: "production", system_id: ulid(),
        topologies: [artifact(topologyId, "recorded.gro")],
        trajectories: [artifact(trajectoryId, "recorded.xtc")],
      }] } });
    });
    await page.route(api + "/v1/projects/" + projectId + "/trajectory-analysis/prepare", (route) =>
      route.fulfill({ status: 422, json: { detail: "UI fixture: prepare request captured" } }));
    await page.getByRole("button", { name: /3D Molecular Studio/ }).click();
    await expect(page.getByRole("combobox", { name: "Topology", exact: true })).toHaveValue(topologyId, { timeout: 20_000 });
    await expect(page.getByRole("button", { name: "Calculate analysis", exact: true })).toBeEnabled();
  });

  async function capturePrepare(page: Page) {
    const requested = page.waitForRequest(api + "/v1/projects/" + projectId + "/trajectory-analysis/prepare");
    await page.getByRole("button", { name: "Calculate analysis", exact: true }).click();
    const request = await requested;
    expect(request.headers().authorization).toBe("Bearer " + token);
    await expect(page.getByText("UI fixture: prepare request captured", { exact: false })).toBeVisible();
    return request.postDataJSON();
  }

  test("keeps three default metrics and sends explicit optional SASA selections and settings", async ({ page }) => {
    const defaults = ["backbone_rmsd", "protein_ca_rmsf", "protein_radius_of_gyration"];
    const sasa = page.getByRole("checkbox", { name: "Solvent accessible surface area (SASA)", exact: true });
    const hbond = page.getByRole("checkbox", { name: "Protein–ligand hydrogen bonds", exact: true });
    await expect(sasa).not.toBeChecked();
    await expect(hbond).not.toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Protein hydrogen bonds", exact: true })).not.toBeChecked();
    expect(await capturePrepare(page)).toMatchObject({
      source_task_id: taskId, topology_artifact_id: topologyId, trajectory_artifact_id: trajectoryId,
      metrics: defaults,
    });
    await sasa.check();
    await expect(page.getByLabel("SASA surface selection (MDAnalysis)")).toHaveValue("protein");
    await expect(page.getByLabel("SASA output selection (MDAnalysis)")).toHaveValue("protein");
    const sasaDefaults = await capturePrepare(page);
    expect(sasaDefaults).toMatchObject({
      metrics: [...defaults, "solvent_accessible_surface_area"], sasa_surface_selection: "protein",
      sasa_output_selection: "protein", sasa_probe_radius_A: 1.4, sasa_sphere_points: 24,
    });
    expect(sasaDefaults).not.toHaveProperty("ligand_selection");
    await page.getByLabel("SASA surface selection (MDAnalysis)").fill("protein or resname DRG");
    await page.getByLabel("SASA output selection (MDAnalysis)").fill("resname DRG");
    await page.getByLabel("SASA probe radius (Å)").fill("1.6");
    await page.getByLabel("SASA sphere points").fill("96");
    expect(await capturePrepare(page)).toMatchObject({
      sasa_surface_selection: "protein or resname DRG", sasa_output_selection: "resname DRG",
      sasa_probe_radius_A: 1.6, sasa_sphere_points: 96,
    });
    const calculate = page.getByRole("button", { name: "Calculate analysis", exact: true });
    await page.getByLabel("SASA surface selection (MDAnalysis)").fill("   ");
    await expect(calculate).toBeDisabled();
    await expect(page.getByRole("alert").filter({ hasText: "Enter both the SASA" })).toBeVisible();
    await page.getByLabel("SASA surface selection (MDAnalysis)").fill("protein or resname DRG");
    await page.getByLabel("SASA output selection (MDAnalysis)").fill("");
    await expect(calculate).toBeDisabled();
    await page.getByLabel("SASA output selection (MDAnalysis)").fill("resname DRG");
    for (const invalid of ["0", "2.5", "1000001"]) {
      await page.getByLabel("SASA sphere points").fill(invalid);
      await expect(calculate).toBeDisabled();
    }
    await page.getByLabel("SASA sphere points").fill("96");
    for (const invalid of ["0", "6"]) {
      await page.getByLabel("SASA probe radius (Å)").fill(invalid);
      await expect(calculate).toBeDisabled();
    }
    await sasa.uncheck();
    const original = await capturePrepare(page);
    expect(original.metrics).toEqual(defaults);
    expect(original).not.toHaveProperty("sasa_surface_selection");
    expect(original).not.toHaveProperty("sasa_output_selection");
    expect(original).not.toHaveProperty("sasa_probe_radius_A");
    expect(original).not.toHaveProperty("sasa_sphere_points");
    await page.getByRole("checkbox", { name: "Backbone RMSD", exact: true }).uncheck();
    await page.getByRole("checkbox", { name: "Cα RMSF", exact: true }).uncheck();
    await page.getByRole("checkbox", { name: "Protein radius of gyration", exact: true }).uncheck();
    await expect(calculate).toBeDisabled();
  });

  test("protein hydrogen bonds work without a ligand and share cutoffs with the ligand option", async ({ page }) => {
    const protein = page.getByRole("checkbox", { name: "Protein hydrogen bonds", exact: true });
    const ligand = page.getByRole("checkbox", { name: "Protein–ligand hydrogen bonds", exact: true });
    const calculate = page.getByRole("button", { name: "Calculate analysis", exact: true });
    await protein.check();
    await expect(page.getByLabel("Ligand selection (MDAnalysis)", { exact: true })).toHaveCount(0);
    const defaults = await capturePrepare(page);
    expect(defaults).toMatchObject({
      metrics: ["backbone_rmsd", "protein_ca_rmsf", "protein_radius_of_gyration", "protein_hbond_count"],
      hbond_distance_nm: 0.35, hbond_angle_deg: 30,
    });
    expect(defaults).not.toHaveProperty("ligand_selection");
    await page.getByLabel("Hydrogen-bond distance cutoff (nm)").fill("0.31");
    await page.getByLabel("Hydrogen-bond angle cutoff (degrees)").fill("20");
    await ligand.check();
    await expect(calculate).toBeDisabled();
    await page.getByLabel("Ligand selection (MDAnalysis)", { exact: true }).fill("resname DRG");
    await expect(page.getByLabel("Hydrogen-bond distance cutoff (nm)")).toHaveCount(1);
    const combined = await capturePrepare(page);
    expect(combined).toMatchObject({ ligand_selection: "resname DRG", hbond_distance_nm: 0.31, hbond_angle_deg: 20 });
    expect(combined.metrics).toContain("protein_hbond_count");
    expect(combined.metrics).toContain("protein_ligand_hbond_count");
    await page.getByLabel("Ligand selection (MDAnalysis)", { exact: true }).fill("");
    await ligand.uncheck();
    const proteinOnly = await capturePrepare(page);
    expect(proteinOnly).not.toHaveProperty("ligand_selection");
    expect(proteinOnly).toMatchObject({ hbond_distance_nm: 0.31, hbond_angle_deg: 20 });
    await protein.uncheck();
    const original = await capturePrepare(page);
    expect(original).not.toHaveProperty("hbond_distance_nm");
    expect(original).not.toHaveProperty("hbond_angle_deg");
  });

  test("requires an explicit ligand and sends both optional metrics through the prepared workflow", async ({ page }) => {
    const hbond = page.getByRole("checkbox", { name: "Protein–ligand hydrogen bonds", exact: true });
    const calculate = page.getByRole("button", { name: "Calculate analysis", exact: true });
    await hbond.check();
    const ligand = page.getByLabel("Ligand selection (MDAnalysis)", { exact: true });
    await expect(ligand).toHaveValue("");
    await expect(calculate).toBeDisabled();
    await expect(page.getByRole("alert").filter({ hasText: "Enter an explicit ligand" })).toBeVisible();
    await ligand.fill("   ");
    await expect(calculate).toBeDisabled();
    await ligand.fill("resname DRG");
    expect(await capturePrepare(page)).toMatchObject({
      ligand_selection: "resname DRG", hbond_distance_nm: 0.35, hbond_angle_deg: 30,
      metrics: ["backbone_rmsd", "protein_ca_rmsf", "protein_radius_of_gyration", "protein_ligand_hbond_count"],
    });
    for (const [label, invalids, valid] of [
      ["Hydrogen-bond distance cutoff (nm)", ["0", "1.1"], "0.32"],
      ["Hydrogen-bond angle cutoff (degrees)", ["0", "181"], "25"],
    ] as const) {
      for (const invalid of invalids) {
        await page.getByLabel(label).fill(invalid);
        await expect(calculate).toBeDisabled();
      }
      await page.getByLabel(label).fill(valid);
    }
    await page.getByLabel("Protein selection (radius of gyration / hydrogen bonds)").fill("protein and segid A");
    await page.getByRole("checkbox", { name: "Solvent accessible surface area (SASA)", exact: true }).check();
    const workflow = { name: "Prepared UI workflow fixture", stages: [] };
    const inputs = { marker: "Prepared inputs fixture" };
    await page.route(api + "/v1/projects/" + projectId + "/trajectory-analysis/prepare", async (route) => {
      expect(route.request().postDataJSON()).toMatchObject({
        ligand_selection: "resname DRG", protein_selection: "protein and segid A",
        hbond_distance_nm: 0.32, hbond_angle_deg: 25,
        sasa_surface_selection: "protein", sasa_output_selection: "protein",
        sasa_probe_radius_A: 1.4, sasa_sphere_points: 24,
        metrics: ["backbone_rmsd", "protein_ca_rmsf", "protein_radius_of_gyration", "protein_ligand_hbond_count", "solvent_accessible_surface_area"],
      });
      await route.fulfill({ json: { workflow, inputs } });
    });
    await page.route(api + "/v1/projects/" + projectId + "/runs/*/execute", async (route) => {
      expect(route.request().postDataJSON()).toEqual({ workflow, inputs });
      await route.fulfill({ json: { project_id: projectId, run_id: ulid(), status: "queued", tasks: [] } });
    });
    await calculate.click();
    await expect(page.getByRole("status").filter({ hasText: "Trajectory analysis queued" })).toBeVisible();
  });

  test("recorded mixed engines show per-metric methods, parameters, provenance, and CSV downloads", async ({ page }) => {
    const mda = { name: "MDAnalysis", version: "2.9.0" };
    const gmx = { name: "GROMACS", version: "2026.1" };
    const metrics = [
      { name: "rmsd_backbone", unit: "Å", analyzer: mda, parameters: { method: "Backbone alignment" } },
      { name: "sasa", unit: "nm^2", analyzer: gmx, parameters: { method: "GROMACS gmx sasa", probe_radius_A: 1.4, sphere_points: 24 } },
      { name: "protein_ligand_hbond_count", unit: "count", analyzer: gmx, parameters: { hbond_distance_nm: 0.35, donor_acceptor_angle_deg: 30 } },
      { name: "hbond_protein", unit: "count", analyzer: gmx, parameters: { hbond_distance_nm: 0.35, donor_acceptor_angle_deg: 30, protein_selection: "protein" } },
      { name: "rmsf_ca", unit: "Å", analyzer: mda, parameters: { method: "Cα fluctuations" } },
      { name: "rg_protein", unit: "Å", analyzer: mda, parameters: { method: "Mass weighting" } },
    ].map((metric) => ({ ...metric, axis: "time_ns", x: [0, 1], values: [2, 4],
      artifact_id: ulid(), result_id: ulid(), task_id: ulid(), summary: { mean: 3 }, window_ns: [0, 1],
      definition: { target_selection: "Recorded fixture selection", fit_selection: null,
        refit: null, weighting: null, notes: "UI fixture only; not a scientific measurement." },
    }));
    await page.route(api + "/v1/projects/" + projectId + "/trajectories/analyze?**", (route) => route.fulfill({ json: {
      status: "recorded", result_id: metrics[0].result_id, task_id: metrics[0].task_id,
      run_id: ulid(), analyzer: mda, analyzers: [mda, gmx, gmx], metrics, warnings: [],
    } }));
    await page.getByRole("button", { name: /Load recorded analysis/ }).click();
    const recorded = page.getByLabel("Recorded trajectory analysis");
    await expect(recorded.getByText("MDAnalysis 2.9.0 · GROMACS 2026.1 · 6 recorded metrics", { exact: true })).toBeVisible();
    for (const [index, title] of ["Backbone RMSD", "Solvent accessible surface area", "Protein–ligand hydrogen bonds", "Protein hydrogen bonds", "Cα RMSF", "Protein radius of gyration"].entries()) {
      const metric = metrics[index];
      const panel = recorded.getByRole("region", { name: title, exact: true });
      await panel.getByText("Method and recorded summary", { exact: true }).click();
      await expect(panel.getByText(`${metric.analyzer.name} ${metric.analyzer.version}`, { exact: true })).toBeVisible();
      if (metric.analyzer.name === "GROMACS") await expect(panel.getByText(/MDAnalysis/)).toHaveCount(0);
      await expect(panel.getByText(metric.result_id, { exact: true })).toBeVisible();
      await expect(panel.getByText(metric.task_id, { exact: true })).toBeVisible();
      for (const key of Object.keys(metric.parameters)) {
        await expect(panel.getByLabel("Recorded method parameters").getByText(key.replaceAll("_", " "), { exact: true })).toBeVisible();
      }
      await page.route(api + "/v1/projects/" + projectId + "/artifacts/" + metric.artifact_id + "/content", async (route) => {
        expect(route.request().headers().authorization).toBe("Bearer " + token);
        await route.fulfill({ contentType: "text/csv", body: "time_ns,value\n0,2\n1,4\n" });
      });
      const downloaded = page.waitForEvent("download");
      await panel.getByRole("button", { name: "Download CSV", exact: true }).click();
      expect((await downloaded).suggestedFilename()).toBe(metric.name + ".csv");
    }
  });
});

test("local MD timestep select offers only 0.5, 1, 1.5, and 2 fs and submits the selected value", async ({ page }) => {
  const projectId = await connectAndCreate(page);
  await page.getByRole("button", { name: /Pipeline Studio/ }).click();
  await page.getByRole("button", { name: /Protein-Ligand MD/ }).click();
  await page.getByRole("button", { name: /Local Solution Builder \(GROMACS\)/ }).click();
  const timestep = page.getByRole("combobox", { name: "Timestep (fs)", exact: true });
  await expect(timestep).toHaveValue("2");
  await expect(timestep.locator("option")).toHaveText(["0.5 fs", "1 fs", "1.5 fs", "2 fs"]);
  expect(await timestep.locator("option").evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value))).toEqual(["0.5", "1", "1.5", "2"]);
  await expect(page.getByRole("spinbutton", { name: "Timestep (fs)", exact: true })).toHaveCount(0);
  await page.route(api + "/v1/projects/" + projectId + "/build-local-solution?**", (route) =>
    route.fulfill({ status: 422, json: { detail: "UI fixture: local build request captured" } }));
  for (const value of ["0.5", "1", "1.5", "2"]) {
    await timestep.selectOption(value);
    const requested = page.waitForRequest(api + "/v1/projects/" + projectId + "/build-local-solution?**");
    await page.getByRole("button", { name: /Build Solution System \(Local GROMACS\)/ }).click();
    expect(new URL((await requested).url()).searchParams.get("timestep_fs")).toBe(value);
    await expect(page.getByText(/UI fixture: local build request captured/)).toBeVisible();
  }
});

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
  await page.getByRole("checkbox", { name: "Choose other files (advanced)" }).check();
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
  await page.getByRole("checkbox", { name: "Choose other files (advanced)" }).check();
  const tops = page.getByRole("combobox", { name: "Topology", exact: true });
  const coords = page.getByRole("combobox", { name: "Coordinates", exact: true });
  await tops.selectOption((await tops.locator("option").filter({ hasText: "two-atom-topology" }).getAttribute("value"))!);
  await coords.selectOption((await coords.locator("option").filter({ hasText: "two-atom-trajectory" }).getAttribute("value"))!);
  await page.getByRole("button", { name: "View trajectory", exact: true }).click();
  await expect(page.getByLabel("Molecular trajectory viewer")).toBeVisible();
  await expect(page.locator(".molstar-host canvas").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByLabel("Molecular trajectory viewer").locator(".alert")).not.toBeVisible();
});

test("trajectory dropdowns show only the selected MD task files", async ({ page }) => {
  test.setTimeout(60_000);
  const projectId = await connectAndCreate(page);
  await page.getByRole("button", { name: /3D Molecular Studio/ }).click();
  // Explicit metadata/UI fixtures; no scientific calculation or trajectory is fabricated.
  for (const name of ["older.pdb", "latest.pdb", "unrelated.pdb", "older.xtc", "latest.xtc"]) {
    await upload(page, name, "application/octet-stream", Buffer.from("UI selection fixture " + name));
  }
  const response = await page.request.get(api + "/v1/projects/" + projectId + "/artifacts",
    { headers: { Authorization: "Bearer " + token } });
  const artifacts = await response.json() as Array<{ id: string; original_name: string }>;
  const artifact = (name: string) => artifacts.find((item) => item.original_name === name)!;
  const latestTask = ulid(), olderTask = ulid();
  const groups = [
    { task_id: latestTask, run_id: ulid(), accession: "Latest MD fixture", stage_id: "production", stage_kind: "production",
      system_id: ulid(), topologies: [artifact("latest.pdb")], trajectories: [artifact("latest.xtc")] },
    { task_id: olderTask, run_id: ulid(), accession: "Older MD fixture", stage_id: "production", stage_kind: "production",
      system_id: ulid(), topologies: [artifact("older.pdb")], trajectories: [artifact("older.xtc")] },
  ];
  await page.route(api + "/v1/projects/" + projectId + "/dashboard", async (route) => {
    const original = await route.fetch();
    const dashboard = await original.json();
    await route.fulfill({ json: { ...dashboard, trajectory_options: groups } });
  });
  const source = page.getByRole("combobox", { name: "Completed MD task", exact: true });
  await expect(source).toBeVisible({ timeout: 20_000 });
  const tops = page.getByRole("combobox", { name: "Topology", exact: true });
  const coords = page.getByRole("combobox", { name: "Coordinates", exact: true });
  await expect(tops.locator("option")).toHaveCount(2);
  await expect(coords.locator("option")).toHaveCount(2);
  await expect(tops).toHaveValue(artifact("latest.pdb").id);
  await expect(coords).toHaveValue(artifact("latest.xtc").id);
  await expect(page.getByLabel("Molecular trajectory viewer")).not.toBeVisible();
  await source.selectOption(olderTask);
  await expect(tops).toHaveValue(artifact("older.pdb").id);
  await expect(coords).toHaveValue(artifact("older.xtc").id);
  await expect(tops.locator("option").filter({ hasText: "latest.pdb" })).toHaveCount(0);
  await expect(tops.locator("option").filter({ hasText: "unrelated.pdb" })).toHaveCount(0);
  await page.getByRole("checkbox", { name: "Choose other files (advanced)" }).check();
  await expect(tops.locator("option")).toHaveCount(4);
  await expect(coords.locator("option")).toHaveCount(3);
  await expect(tops).toHaveValue("");
  await expect(page.getByText(/Manual selection: confirm both files/)).toBeVisible();
  await page.getByRole("checkbox", { name: "Choose other files (advanced)" }).uncheck();
  await expect(tops).toHaveValue(artifact("older.pdb").id);
  await page.locator(".structure-list").filter({ has: page.getByRole("heading", { name: "Trajectory 3D Preview (Mol*)" }) }).screenshot({ path: "test-results/trajectory-file-filtering.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.getByRole("button", { name: /Projects & API/ }).click();
  await page.getByPlaceholder(/Project name/).fill("Separate empty project");
  await page.getByPlaceholder(/slug \(e.g./).fill("empty-trajectory-" + Date.now());
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Project created:" })).toBeVisible();
  await page.getByRole("button", { name: /3D Molecular Studio/ }).click();
  await expect(page.getByRole("heading", { name: "Trajectory 3D Preview (Mol*)" })).not.toBeVisible();
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

  // Verify warning badge is visible when identities are not yet set
  await expect(page.getByText("Prepared Structure Identity Required")).toBeVisible();

  // Verify submission attempt without explicit identities is rejected with actionable error
  await page.getByRole("button", { name: /Queue Pipeline/ }).click();
  await expect(page.getByText(/Quantum chemistry \(DFT\) requires an explicit target form/)).toBeVisible();

  const explicitFormId = ulid();
  const explicitConfId = ulid();
  const formIdInput = page.getByLabel("Target Form / Microstate ID (ULID)");
  await expect(formIdInput).toBeVisible();
  await formIdInput.fill(explicitFormId);

  const confIdInput = page.getByLabel("Target Conformer / Geometry ID (ULID)");
  await expect(confIdInput).toBeVisible();
  await confIdInput.fill(explicitConfId);

  // Warning badge disappears once explicit identities are set
  await expect(page.getByText("Prepared Structure Identity Required")).not.toBeVisible();

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

test("complete guided 3D ligand preparation workflow and explicit DFT conformer binding", async ({ page }) => {
  test.setTimeout(120_000);
  const projectId = await connectAndCreate(page);

  // Register compound in Ligand Registry
  await page.getByRole("button", { name: /Ligand Registry/ }).click();
  await page.getByLabel("Compound name / identifier").fill("Ethanol");
  await page.getByLabel("SMILES string").fill("CCO");
  await page.getByRole("button", { name: "Standardize & register compound" }).click();
  await expect(page.getByText("CMP0001", { exact: true })).toBeVisible();

  // Navigate to Pipeline Studio and select 3D Ligand Preparation preset
  await page.getByRole("button", { name: /Pipeline Studio/ }).click();
  const prep3dBtn = page.getByRole("button", { name: /Ligand 3D/ });
  await prep3dBtn.click();
  await expect(prep3dBtn).toHaveAttribute("aria-pressed", "true");

  // Compile and validate the guided 3D preparation workflow
  await page.getByRole("button", { name: "Validate & Plan" }).click();
  await expect(page.getByRole("status").filter({ hasText: /compiled successfully/ })).toBeVisible();

  // Queue and execute the pipeline
  await page.getByRole("button", { name: /Queue Pipeline/ }).click();
  const progress = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Execution progress" }) });
  await expect(progress.locator(".pill").filter({ hasText: "succeeded" })).toBeVisible({ timeout: 30_000 });

  // Navigate back to Pipeline Studio and select Ligand DFT preset
  await page.getByRole("button", { name: /Pipeline Studio/ }).click();
  const dftBtn = page.getByRole("button", { name: /Ligand DFT/ });
  await dftBtn.click();
  await expect(dftBtn).toHaveAttribute("aria-pressed", "true");

  // The prepared conformer entity is now present in the selector
  const confSelect = page.getByRole("combobox", { name: "Select Prepared 3D Conformer / Structure" });
  await expect(confSelect).toBeVisible();

  // Select the genuine prepared conformer entity
  const options = confSelect.locator("option");
  await expect(options).toHaveCount(2);
  const confValue = await options.nth(1).getAttribute("value");
  expect(confValue).toBeTruthy();
  expect(confValue).not.toBe("");
  await confSelect.selectOption(confValue!);

  // Verify that both conformer ID and form ID inputs were auto-populated with entity ULIDs
  const confInput = page.getByLabel("Target Conformer / Geometry ID (ULID)");
  const formInput = page.getByLabel("Target Form / Microstate ID (ULID)");
  await expect(confInput).toHaveValue(confValue!);
  const formVal = await formInput.inputValue();
  expect(formVal).toBeTruthy();
  expect(formVal).not.toBe("00000000000000000000000000");

  // Verify warning badge disappears
  await expect(page.getByText("Prepared Structure Identity Required")).not.toBeVisible();

  // Validate and plan the DFT workflow with genuine prepared conformer entity contracts
  await page.getByRole("button", { name: "Validate & Plan" }).click();
  await expect(page.getByRole("status").filter({ hasText: /compiled successfully/ })).toBeVisible();

  // Queue and execute the DFT calculation through the UI
  await page.getByRole("button", { name: /Queue Pipeline/ }).click();
  const dftProgress = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Execution progress" }) });
  await expect(dftProgress.locator(".pill").filter({ hasText: "succeeded" })).toBeVisible({ timeout: 60_000 });

  // Verify that the QM stage completed successfully on the monitor
  await expect(dftProgress.locator(".task").filter({ hasText: "qm" }).getByText("succeeded")).toBeVisible();
  await expect(dftProgress.locator(".task").filter({ hasText: "report" }).getByText("succeeded")).toBeVisible();

  // Navigate to Overview & Evidence dashboard and verify scientific results
  await page.getByRole("button", { name: /Overview & Evidence/ }).click();
  await expect(page.getByRole("heading", { name: "Project dashboard" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Scientific evidence & results" })).toBeVisible();

  // Assert normalized quantum chemistry results are visible (electronic energy, dipole moment)
  const qmCard = page.locator(".evidence-card").filter({ hasText: "quantum chemistry" });
  await expect(qmCard).toBeVisible();
  await expect(qmCard.getByText("Total Energy Eh")).toBeVisible();
  await expect(qmCard.getByText("Dipole D")).toBeVisible();
  await expect(qmCard.getByText("Pass")).toBeVisible();
});

test("recorded MD inputs disambiguation supports candidate selection and loads system_build", async ({ page }) => {
  test.setTimeout(60_000);
  const projectId = await connectAndCreate(page);

  // Register compound
  await page.getByRole("button", { name: /Ligand Registry/ }).click();
  await page.getByLabel("Compound name / identifier").fill("Ethanol");
  await page.getByLabel("SMILES string").fill("CCO");
  await page.getByRole("button", { name: "Standardize & register compound" }).click();
  await expect(page.getByText("CMP0001", { exact: true })).toBeVisible();

  // Navigate to Pipeline Studio -> MD preset
  await page.getByRole("button", { name: /Pipeline Studio/ }).click();
  const mdBtn = page.getByRole("button", { name: /Protein-Ligand MD/ });
  await mdBtn.click();
  await expect(mdBtn).toHaveAttribute("aria-pressed", "true");

  // Initial state in fresh project: no recorded runs
  const provisionBtn = page.getByRole("button", { name: /Load recorded MD inputs/ });
  await expect(provisionBtn).toBeDisabled();
  await expect(page.getByText("No completed MD runs recorded in this project yet")).toBeVisible();

  // Mock candidate runs endpoint with 2 disambiguation choices
  const run1Id = ulid();
  const run2Id = ulid();
  await page.route(api + "/v1/projects/" + projectId + "/recorded-md-candidates", async (route) => {
    await route.fulfill({
      json: [
        {
          run_id: run1Id,
          accession: "RUN-EQUIL",
          submitted_at: "2026-10-12T09:10:22Z",
          system_id: ulid(),
          atoms: 49682,
          engine: "gromacs",
          length_ns: 0.001,
          timestep_fs: 4.0,
          temperature_K: 300.0,
          label: "RUN-EQUIL (49,682 atoms, 0.001 ns, 300.0 K)",
        },
        {
          run_id: run2Id,
          accession: "RUN-PROD",
          submitted_at: "2026-10-12T08:57:58Z",
          system_id: ulid(),
          atoms: 49682,
          engine: "gromacs",
          length_ns: 1.0,
          timestep_fs: 4.0,
          temperature_K: 303.15,
          label: "RUN-PROD (49,682 atoms, 1.0 ns, 303.15 K)",
        },
      ],
    });
  });

  // Re-select MD preset to refresh candidates
  await mdBtn.click();

  // Selector should appear with both candidates
  const selector = page.getByRole("combobox", { name: "Select recorded MD run" });
  await expect(selector).toBeVisible();
  await expect(selector.locator("option")).toHaveCount(2);

  // Mock provision response for the second run
  await page.route(api + "/v1/projects/" + projectId + "/provision-demo-md-system?**", async (route) => {
    const reqUrl = new URL(route.request().url());
    expect(reqUrl.searchParams.get("run_id")).toBe(run2Id);
    await route.fulfill({
      json: {
        status: "recorded",
        system_build: {
          schema_version: "system_build_result/1.0",
          id: ulid(),
          atoms: 49682,
        },
        stage_input: {
          schema_version: "md_stage_plan/1.0",
          stage_index: 0,
        },
        info: {
          atoms: 49682,
          length_ns: 1.0,
          timestep_fs: 4.0,
          temperature_K: 303.15,
        },
      },
    });
  });

  // Select the second candidate and load
  await selector.selectOption(run2Id);
  await expect(provisionBtn).toBeEnabled();
  await provisionBtn.click();

  // Verify successful load of recorded system
  await expect(page.getByText("Recorded MD inputs loaded")).toBeVisible();
  await expect(page.getByText("Recorded system (49682 atoms)")).toBeVisible();
  await expect(page.getByText("Prepared system: Recorded inputs loaded")).toBeVisible();
  await expect(page.getByRole("button", { name: /Queue Pipeline/ })).toBeEnabled();
});
