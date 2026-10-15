import { useState } from "react";

type Metric = {
  name: string;
  unit: string;
  axis: "time_ns" | "residue";
  x: number[];
  values: number[];
  artifact_id: string;
  definition: {
    target_selection: string;
    fit_selection: string | null;
    refit: boolean | null;
    weighting: string | null;
    notes: string | null;
  };
  summary: Record<string, number>;
  window_ns: number[];
};

export type TrajectoryAnalyticsResult = {
  status: "recorded";
  result_id: string;
  task_id: string;
  run_id: string;
  analyzer: { name: string; version: string };
  metrics: Metric[];
  warnings: string[];
};

type Props = {
  data: TrajectoryAnalyticsResult;
  apiUrl: string;
  token: string;
  projectId: string;
};

function nameLabel(name: string) {
  return ({
    rmsd_backbone: "Backbone RMSD",
    rmsd_ligand_pose: "Ligand pose RMSD",
    rmsd_ligand_internal: "Ligand internal RMSD",
    rmsf_ca: "Cα RMSF",
    rg: "Radius of gyration",
    rg_protein: "Protein radius of gyration",
    sasa: "Solvent accessible surface area",
    protein_ligand_hbond_count: "Protein–ligand hydrogen bonds",
  } as Record<string, string>)[name] || name.replaceAll("_", " ");
}

function MetricChart({ metric }: { metric: Metric }) {
  const repeatedResidues = metric.axis === "residue" && new Set(metric.x).size !== metric.x.length;
  const displayX = repeatedResidues ? metric.x.map((_, index) => index + 1) : metric.x;
  const stride = Math.max(1, Math.ceil(metric.x.length / 1000));
  const indices = metric.x.map((_, i) => i).filter((i) => i % stride === 0 || i === metric.x.length - 1);
  const xs = indices.map((i) => displayX[i]);
  const ys = indices.map((i) => metric.values[i]);
  const xmin = Math.min(...xs), xmax = Math.max(...xs);
  const ymin = Math.min(...ys), ymax = Math.max(...ys);
  const points = indices.map((i) =>
    (45 + 600 * (displayX[i] - xmin) / (xmax - xmin || 1)).toFixed(2) + "," +
    (180 - 145 * (metric.values[i] - ymin) / (ymax - ymin || 1)).toFixed(2)
  ).join(" ");
  const title = nameLabel(metric.name);
  return (
    <>
      <svg viewBox="0 0 680 220" role="img" aria-label={title + " recorded values in " + metric.unit}>
        <title>{title}</title>
        <path d="M45 30 V180 H650" fill="none" stroke="currentColor" opacity=".35" />
        <polyline points={points} fill="none" stroke="#2563eb" strokeWidth="2" />
        <text x="45" y="205" fontSize="12">{xmin.toPrecision(4)}</text>
        <text x="595" y="205" fontSize="12">{xmax.toPrecision(4)}</text>
        <text x="48" y="25" fontSize="12">{ymax.toPrecision(4)} {metric.unit}</text>
        <text x="300" y="217" fontSize="12">{metric.axis === "time_ns" ? "Time (ns)" : repeatedResidues ? "Selected Cα order" : "Residue"}</text>
      </svg>
      <p className="dim">
        {metric.values.length} recorded values.
        {` Range: ${ymin.toPrecision(4)}–${ymax.toPrecision(4)} ${metric.unit}.`}
        {stride > 1 && " The chart shows a sampled preview; the CSV contains every value."}
      </p>
      {repeatedResidues && <p className="dim">Residue numbers repeat across the selection. The horizontal axis uses selected Cα order; the CSV preserves the original residue numbers.</p>}
    </>
  );
}

export default function TrajectoryPlots({ data, apiUrl, token, projectId }: Props) {
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState<string | null>(null);
  async function download(metric: Metric) {
    setError("");
    setDownloading(metric.artifact_id);
    try {
      const response = await fetch(
        apiUrl.replace(/\/$/, "") + "/v1/projects/" + encodeURIComponent(projectId) +
        "/artifacts/" + encodeURIComponent(metric.artifact_id) + "/content",
        { headers: { Authorization: "Bearer " + token } }
      );
      if (!response.ok) throw new Error("Unable to download the recorded CSV (" + response.status + ").");
      const blobUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = metric.name.replace(/[^a-z0-9_-]/gi, "_") + ".csv";
      link.click();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setDownloading(null); }
  }
  return (
    <section className="trajectory-analytics-card" aria-label="Recorded trajectory analysis">
      <h3>Recorded trajectory analysis</h3>
      <p>{data.analyzer.name} {data.analyzer.version} · {data.metrics.length} recorded metrics</p>
      {data.warnings.map((warning) => <p key={warning} className="method-note">{warning}</p>)}
      {error && <p role="alert">{error}</p>}
      <div className="trajectory-charts-grid">
        {data.metrics.map((metric) => (
          <section className="panel" key={metric.name} aria-label={nameLabel(metric.name)}>
            <div className="between">
              <h4>{nameLabel(metric.name)}</h4>
              <button type="button" className="outline small"
                disabled={downloading !== null} onClick={() => void download(metric)}>
                {downloading === metric.artifact_id ? "Downloading…" : "Download CSV"}
              </button>
            </div>
            <MetricChart metric={metric} />
            <details>
              <summary>Method and recorded summary</summary>
              <dl>
                <dt>Atoms measured</dt><dd>{metric.definition.target_selection}</dd>
                <dt>Alignment</dt><dd>{metric.definition.fit_selection || "Not specified"}</dd>
                <dt>Weighting</dt><dd>{metric.definition.weighting || "Not specified"}</dd>
                <dt>Time window</dt><dd>{metric.window_ns.join(" – ")} ns</dd>
              </dl>
              {metric.definition.notes && <p>{metric.definition.notes}</p>}
              <table><caption>Recorded summary ({metric.unit})</caption>
                <tbody>{Object.entries(metric.summary).filter(([, value]) => Number.isFinite(value)).map(([key, value]) => (
                  <tr key={key}><th scope="row">{key.replaceAll("_", " ")}</th><td>{value}</td></tr>
                ))}</tbody>
              </table>
            </details>
          </section>
        ))}
      </div>
      <details><summary>Result provenance</summary>
        <dl><dt>Run</dt><dd>{data.run_id}</dd><dt>Task</dt><dd>{data.task_id}</dd>
          <dt>Result</dt><dd>{data.result_id}</dd></dl>
      </details>
    </section>
  );
}
