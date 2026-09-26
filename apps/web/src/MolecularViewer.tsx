import { useEffect, useRef, useState } from "react";
import { Viewer } from "molstar/lib/apps/viewer/app";
import "molstar/build/viewer/molstar.css";

export type StructureFormat = "pdb" | "mmcif" | "sdf" | "mol2" | "gro";

type Props = {
  apiUrl: string;
  token: string;
  projectId: string;
  artifactId: string;
  label: string;
  format: StructureFormat;
  sizeBytes: number;
  onClose: () => void;
};

export default function MolecularViewer({
  apiUrl,
  token,
  projectId,
  artifactId,
  label,
  format,
  sizeBytes,
  onClose,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let viewer: Viewer | undefined;

    async function load() {
      try {
        setError("");
        setLoading(true);
        if (sizeBytes > 100 * 1024 * 1024) {
          throw new Error("This structure exceeds the 100 MiB in-browser preview limit.");
        }
        const base = apiUrl.replace(/\/$/, "");
        const response = await fetch(
          `${base}/v1/projects/${projectId}/artifacts/${artifactId}/content`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        if (!response.ok)
          throw new Error(`Artifact request failed (${response.status})`);
        const text = await response.text();
        if (cancelled || !host.current) return;
        viewer = await Viewer.create(host.current, { layoutIsExpanded: false });
        if (cancelled) {
          viewer.dispose();
          return;
        }
        await viewer.loadStructureFromData(text, format, { dataLabel: label });
        if (!cancelled) setLoading(false);
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : String(cause));
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
      viewer?.dispose();
    };
  }, [apiUrl, artifactId, format, label, projectId, sizeBytes, token]);

  return (
    <section
      className="molecular-viewer"
      aria-label="Molecular structure viewer"
    >
      <div className="between">
        <div>
          <h3>{label}</h3>
          <code>Artifact {artifactId}</code>
        </div>
        <button className="link" onClick={onClose}>
          Close viewer
        </button>
      </div>
      {loading && <p className="viewer-status">Loading molecular structure&</p>}
      {error && <div className="alert">{error}</div>}
      <div className="molstar-host" ref={host} />
    </section>
  );
}
