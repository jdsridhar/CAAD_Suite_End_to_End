import {useEffect,useRef,useState} from "react";
import {Viewer} from "molstar/lib/apps/viewer/app";
import "molstar/build/viewer/molstar.css";
type Props={apiUrl:string;token:string;projectId:string;artifactId:string;name:string;sizeBytes:number;onClose:()=>void};
const LIMIT=100*1024*1024;
export default function VolumeViewer(p:Props){
 const host=useRef<HTMLDivElement>(null),[error,setError]=useState(""),[loading,setLoading]=useState(true);
 useEffect(()=>{let cancelled=false,viewer:Viewer|undefined;
 async function load(){try{if(p.sizeBytes>LIMIT)throw Error("Cube file exceeds the 100 MiB in-browser preview limit.");const r=await fetch(`${p.apiUrl.replace(/\/$/,"")}/v1/projects/${p.projectId}/artifacts/${p.artifactId}/content`,{headers:{Authorization:`Bearer ${p.token}`}});if(!r.ok)throw Error(`Artifact request failed (${r.status})`);const bytes=await r.arrayBuffer();if(cancelled||!host.current)return;viewer=await Viewer.create(host.current,{layoutIsExpanded:true,layoutShowLeftPanel:true});await viewer.loadFiles([new File([bytes],p.name)]);if(!cancelled)setLoading(false)}catch(e){if(!cancelled){setError(e instanceof Error?e.message:String(e));setLoading(false)}}}
 void load();return()=>{cancelled=true;viewer?.dispose()}
 },[p.apiUrl,p.token,p.projectId,p.artifactId,p.name,p.sizeBytes]);
 return <section className="molecular-viewer" aria-label="Volumetric cube viewer"><div className="between"><div><h3>Volumetric cube / molecular orbital</h3><p>{p.name}; grid values follow the cube data; scalar units may need calculation metadata for interpretation.</p></div><button className="link" onClick={p.onClose}>Close viewer</button></div><p className="viewer-status">Use Mol* volume controls to adjust the isosurface. The isovalue uses the cube scalar-value scale. Cube scalar units are not consistently declared; consult the originating calculation output.</p>{loading&&<p className="viewer-status">Loading cube...</p>}{error&&<div className="alert">{error}</div>}<div className="molstar-host" ref={host}/></section>
}
