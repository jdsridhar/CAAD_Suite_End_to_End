import type { ReactNode } from "react";

type ScientificEvidenceViewProps = {
  values: unknown;
};

type AdmetPropertyItem = {
  endpoint: string;
  value: unknown;
  unit?: string | null;
  kind?: string | null;
  model?: string | null;
  model_version?: string | null;
  uncertainty?: number | null;
};

type DockingPoseItem = {
  pose_id?: string;
  rank?: number;
  score?: number | string;
  unit?: string | null;
  scoring_function?: string | null;
};

type TrajectoryMetricItem = {
  metric: string;
  summary: unknown;
  unit?: string | null;
  window_ns?: [number, number];
};

function formatNumber(val: number): string {
  if (Number.isInteger(val)) return String(val);
  const abs = Math.abs(val);
  if (abs >= 1000) return val.toFixed(1);
  if (abs >= 10) return val.toFixed(2);
  if (abs >= 0.001) return val.toFixed(3);
  return val.toExponential(2);
}

function formatUnit(unit: string | null | undefined): string {
  if (!unit || unit === "dimensionless" || unit === "none") return "—";
  if (unit === "angstrom^2" || unit === "Å^2") return "Å²";
  if (unit === "cm^3/mol") return "cm³/mol";
  if (unit === "elementary_charge") return "e";
  if (unit === "count") return "count";
  return unit;
}

const ENDPOINT_LABELS: Record<string, string> = {
  molecular_weight: "Molecular Weight (MW)",
  crippen_logp: "LogP (Crippen)",
  logp: "LogP",
  tpsa: "Polar Surface Area (TPSA)",
  hbd: "H-Bond Donors (HBD)",
  hba: "H-Bond Acceptors (HBA)",
  rotatable_bonds: "Rotatable Bonds",
  ring_count: "Ring Count",
  aromatic_ring_count: "Aromatic Rings",
  heavy_atom_count: "Heavy Atoms",
  total_atom_count: "Total Atoms (incl. H)",
  fraction_csp3: "Fraction Csp3",
  molar_refractivity: "Molar Refractivity",
  formal_charge: "Formal Charge",
  lipinski_violations: "Lipinski Violations",
  lipinski_pass: "Lipinski Rule of 5",
  veber_violations: "Veber Violations",
  veber_pass: "Veber Filter",
  ghose_violations: "Ghose Violations",
  ghose_pass: "Ghose Filter",
  egan_violations: "Egan Violations",
  egan_pass: "Egan Filter",
  qed: "QED Drug-likeness",
  pains_alerts: "PAINS Alerts",
  brenk_alerts: "Brenk Alerts",
  nih_alerts: "NIH Alerts",
};

function endpointLabel(endpoint: string): string {
  if (ENDPOINT_LABELS[endpoint]) return ENDPOINT_LABELS[endpoint];
  return endpoint
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function kindLabel(kind: string): string {
  if (kind === "calculated_descriptor") return "Descriptor";
  if (kind === "rule") return "Rule";
  if (kind === "structural_alert") return "Alert";
  if (kind === "ml_prediction") return "ML Model";
  return kind.replace(/_/g, " ");
}

function renderCellValue(val: unknown): ReactNode {
  if (val === null || val === undefined) {
    return <span className="evidence-null">—</span>;
  }
  if (typeof val === "boolean") {
    return (
      <span className={`evidence-badge ${val ? "badge-pass" : "badge-fail"}`}>
        {val ? "Pass" : "Fail"}
      </span>
    );
  }
  if (typeof val === "number") {
    return <span className="evidence-num">{formatNumber(val)}</span>;
  }
  if (Array.isArray(val)) {
    if (val.length === 0) return <span className="evidence-muted">None</span>;
    return (
      <span className="evidence-list">
        {val.map((item, idx) => (
          <span key={idx} className="evidence-item-chip">
            {String(item)}
          </span>
        ))}
      </span>
    );
  }
  if (typeof val === "object") {
    return <code>{JSON.stringify(val)}</code>;
  }
  return String(val);
}

export default function ScientificEvidenceView({ values }: ScientificEvidenceViewProps) {
  if (
    Array.isArray(values) &&
    values.length > 0 &&
    typeof values[0] === "object" &&
    values[0] !== null &&
    "endpoint" in values[0]
  ) {
    const rows = values as AdmetPropertyItem[];
    return (
      <div className="evidence-table-container">
        <table className="evidence-table">
          <thead>
            <tr>
              <th>Property / Descriptor</th>
              <th>Value</th>
              <th>Unit</th>
              <th>Type</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => {
              const isAlert =
                row.kind === "structural_alert" ||
                (row.endpoint.includes("violation") &&
                  typeof row.value === "number" &&
                  row.value > 0);
              return (
                <tr key={row.endpoint || idx} className={isAlert ? "row-warning" : undefined}>
                  <td className="evidence-prop-name">
                    <strong>{endpointLabel(row.endpoint)}</strong>
                    {row.model && (
                      <small className="evidence-subtext">
                        {row.model} {row.model_version || ""}
                      </small>
                    )}
                  </td>
                  <td className="evidence-prop-value">{renderCellValue(row.value)}</td>
                  <td className="evidence-prop-unit">{formatUnit(row.unit)}</td>
                  <td className="evidence-prop-kind">
                    <span className={`kind-tag ${row.kind || "generic"}`}>
                      {kindLabel(row.kind || "")}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <details className="evidence-json-toggle">
          <summary>View raw contract data</summary>
          <pre>{JSON.stringify(values, null, 2)}</pre>
        </details>
      </div>
    );
  }

  if (
    Array.isArray(values) &&
    values.length > 0 &&
    typeof values[0] === "object" &&
    values[0] !== null &&
    ("rank" in values[0] || "score" in values[0])
  ) {
    const rows = values as DockingPoseItem[];
    return (
      <div className="evidence-table-container">
        <table className="evidence-table">
          <thead>
            <tr>
              <th>Rank</th>
              <th>Score</th>
              <th>Unit</th>
              <th>Scoring Function</th>
              <th>Pose ID</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr key={row.pose_id || idx}>
                <td>
                  <strong>#{row.rank ?? idx + 1}</strong>
                </td>
                <td className="evidence-prop-value">{renderCellValue(row.score)}</td>
                <td className="evidence-prop-unit">{formatUnit(row.unit)}</td>
                <td>
                  <code>{row.scoring_function || "—"}</code>
                </td>
                <td>
                  <code className="evidence-id">{row.pose_id || "—"}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <details className="evidence-json-toggle">
          <summary>View raw contract data</summary>
          <pre>{JSON.stringify(values, null, 2)}</pre>
        </details>
      </div>
    );
  }

  if (
    Array.isArray(values) &&
    values.length > 0 &&
    typeof values[0] === "object" &&
    values[0] !== null &&
    "metric" in values[0]
  ) {
    const rows = values as TrajectoryMetricItem[];
    return (
      <div className="evidence-table-container">
        <table className="evidence-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Summary</th>
              <th>Unit</th>
              <th>Window</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr key={row.metric || idx}>
                <td className="evidence-prop-name">
                  <strong>{row.metric}</strong>
                </td>
                <td className="evidence-prop-value">{renderCellValue(row.summary)}</td>
                <td className="evidence-prop-unit">{formatUnit(row.unit)}</td>
                <td>
                  {Array.isArray(row.window_ns)
                    ? `${row.window_ns[0]} - ${row.window_ns[1]} ns`
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <details className="evidence-json-toggle">
          <summary>View raw contract data</summary>
          <pre>{JSON.stringify(values, null, 2)}</pre>
        </details>
      </div>
    );
  }

  if (
    Array.isArray(values) &&
    values.length > 0 &&
    typeof values[0] === "object" &&
    values[0] !== null
  ) {
    const list = values as Record<string, unknown>[];
    const columns = Array.from(new Set(list.flatMap((item) => Object.keys(item))));
    return (
      <div className="evidence-table-container">
        <table className="evidence-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col}>{endpointLabel(col)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {list.map((row, idx) => (
              <tr key={idx}>
                {columns.map((col) => (
                  <td key={col}>{renderCellValue(row[col])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <details className="evidence-json-toggle">
          <summary>View raw contract data</summary>
          <pre>{JSON.stringify(values, null, 2)}</pre>
        </details>
      </div>
    );
  }

  if (typeof values === "object" && values !== null && !Array.isArray(values)) {
    const entries = Object.entries(values as Record<string, unknown>);
    return (
      <div className="evidence-table-container">
        <table className="evidence-table">
          <thead>
            <tr>
              <th>Property / Metric</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([k, v]) => (
              <tr key={k}>
                <td className="evidence-prop-name">
                  <strong>{endpointLabel(k)}</strong>
                </td>
                <td className="evidence-prop-value">{renderCellValue(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <details className="evidence-json-toggle">
          <summary>View raw contract data</summary>
          <pre>{JSON.stringify(values, null, 2)}</pre>
        </details>
      </div>
    );
  }

  return (
    <div className="evidence-table-container">
      <pre>{JSON.stringify(values, null, 2)}</pre>
    </div>
  );
}
