import { useEffect, useRef, useState } from "react";
import { Viewer } from "molstar/lib/apps/viewer/app";
import "molstar/build/viewer/molstar.css";
export type TopologyFormat = "gro" | "pdb" | "mmcif" | "psf" | "prmtop" | "top";
export type CoordinatesFormat = "xtc" | "trr" | "dcd" | "nctraj" | "lammpstrj";
type Props = { apiUrl: string; token: string; projectId: string; topologyId: string; topologyName: string; topologyFormat: TopologyFormat; topologySize: number; trajectoryId: string; trajectoryName: string; trajectoryFormat: CoordinatesFormat; trajectorySize: number; onClose: () => void };
const MAX_BYTES = 100 * 1024 * 1024;
export default function TrajectoryViewer(p: Props) {
 const host=useRef<HTMLDivElement>(null),[error,setError]=useState(""),[loading,setLoading]=useState(true);
 useEffect(()=>{let cancelled=false,viewer:Viewer|undefined;
 async function load(){try{setError("");setLoading(true);if(p.topologySize+p.trajectorySize>MAX_BYTES)throw Error("Selected files exceed the combined 100 MiB browser preview limit.");
 const base=p.apiUrl.replace(/\/$/,""),headers={Authorization:`Bearer ${p.token}`};
 async function bytes(id:string){const r=await fetch(`${base}/v1/projects/${p.projectId}/artifacts/${id}/content`,{headers});if(!r.ok)throw Error(`Artifact request failed (${r.status})`);return new Uint8Array(await r.arrayBuffer())}
 const [topology,coordinates]=await Promise.all([bytes(p.topologyId),bytes(p.trajectoryId)]);if(cancelled||!host.current)return;
 viewer=await Viewer.create(host.current,{layoutIsExpanded:false,viewportShowAnimation:true,viewportShowTrajectoryControls:true});if(cancelled){viewer.dispose();return}
 const model = p.topologyFormat === "psf" || p.topologyFormat === "prmtop" || p.topologyFormat === "top" ? {kind:"topology-data" as const,data:topology,format:p.topologyFormat} : {kind:"model-data" as const,data:new TextDecoder().decode(topology),format:p.topologyFormat};
 await viewer.loadTrajectory({model,modelLabel:p.topologyName,coordinates:{kind:"coordinates-data",data:coordinates,format:p.trajectoryFormat},coordinatesLabel:p.trajectoryName,preset:"all-models"});
 if(!cancelled)setLoading(false)}catch(e){if(!cancelled){setError(e instanceof Error?e.message:String(e));setLoading(false)}}}
 void load();return()=>{cancelled=true;viewer?.dispose()}
 },[p.apiUrl,p.token,p.projectId,p.topologyId,p.topologyName,p.topologyFormat,p.topologySize,p.trajectoryId,p.trajectoryName,p.trajectoryFormat,p.trajectorySize]);
 return <section className="molecular-viewer" aria-label="Molecular trajectory viewer"><div className="between"><div><h3>Trajectory preview</h3><p>Topology: {p.topologyName} / Trajectory: {p.trajectoryName}</p></div><button className="link" onClick={p.onClose}>Close viewer</button></div><p className="viewer-status">Confirm both files describe the same system and atom ordering.</p>{loading&&<p className="viewer-status">Loading trajectory...</p>}{error&&<div className="alert">{error}</div>}<div className="molstar-host" ref={host}/></section>
}