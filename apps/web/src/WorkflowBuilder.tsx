import { useCallback, useState } from "react";

type Port = { name: string; contracts: string[]; required: boolean };
type Capability = {
  kind: string;
  engine?: string | null;
  inputs: Port[];
  outputs: string[];
  for_each: string[];
};
type StageForm = {
  id: string;
  capabilityIndex: number;
  enabled: boolean;
  forEach: string;
  output: string;
  params: string;
  contracts: Record<string, string>;
  included: Record<string, boolean>;
  bindings: Record<string, string>;
};

type Props = { capabilities: Record<string, unknown>[]; onChange: (json: string) => void };

function asCapability(value: Record<string, unknown>): Capability {
  return {
    kind: String(value.kind ?? ""),
    engine: value.engine == null ? null : String(value.engine),
    inputs: (value.inputs ?? []) as Port[],
    outputs: (value.outputs ?? []) as string[],
    for_each: (value.for_each ?? []) as string[],
  };
}

export default function WorkflowBuilder({ capabilities: raw, onChange }: Props) {
  const capabilities = raw.map(asCapability);
  const [name, setName] = useState("New computational workflow");
  const [stages, setStages] = useState<StageForm[]>([]);
  const [selected, setSelected] = useState(0);
  const [builderError, setBuilderError] = useState("");

  const emit = useCallback((updated: StageForm[], workflowName = name) => {
    const inputs: Record<string, { contract: string; required: boolean }> = {};
    const definitions = updated.map((stage) => {
      const capability = capabilities[stage.capabilityIndex];
      const inputContracts: Record<string, string> = {};
      const inputBindings: Record<string, string> = {};
      const dependencies = new Set<string>();
      for (const port of capability.inputs) {
        if (!stage.included[port.name]) continue;
        const contract = stage.contracts[port.name] || port.contracts[0];
        const source = stage.bindings[port.name] || "$" + stage.id + "_" + port.name;
        inputContracts[port.name] = contract;
        inputBindings[port.name] = source;
        if (source.startsWith("$")) {
          inputs[source.slice(1)] = { contract, required: port.required };
        } else {
          dependencies.add(source);
        }
      }
      const parsedParams = JSON.parse(stage.params || "{}") as Record<string, unknown>;
      return {
        id: stage.id,
        kind: capability.kind,
        enabled: stage.enabled,
        ...(capability.engine ? { engine: capability.engine } : {}),
        ...(stage.forEach ? { for_each: stage.forEach } : {}),
        ...(dependencies.size ? { needs: [...dependencies] } : {}),
        input_contracts: inputContracts,
        input_bindings: inputBindings,
        ...(stage.output ? { output_contract: stage.output } : {}),
        params: parsedParams,
      };
    });
    const workflow = {
      schema: "caddsuite.workflow/1",
      name: workflowName,
      inputs,
      stages: definitions,
      outputs: Object.fromEntries(updated.map((stage) => [stage.id, stage.id])),
    };
    onChange(JSON.stringify(workflow, null, 2));
  }, [capabilities, name, onChange]);

  const publish = (updated: StageForm[]) => {
    try {
      emit(updated);
      setBuilderError("");
    } catch (error) {
      setBuilderError(error instanceof Error ? error.message : "Stage form is invalid.");
    }
  };

  const update = (index: number, patch: Partial<StageForm>) => {
    const next = stages.map((stage, i) => i === index ? { ...stage, ...patch } : stage);
    setStages(next);
    publish(next);
  };

  const addStage = () => {
    const capability = capabilities[selected];
    if (!capability) return;
    const count = stages.length + 1;
    const included: Record<string, boolean> = {};
    const contracts: Record<string, string> = {};
    const bindings: Record<string, string> = {};
    for (const port of capability.inputs) {
      included[port.name] = port.required;
      contracts[port.name] = port.contracts[0] ?? "";
      bindings[port.name] = "$stage_" + count + "_" + port.name;
    }
    const stage: StageForm = {
      id: "stage_" + count,
      capabilityIndex: selected,
      enabled: true,
      forEach: capability.for_each[0] ?? "",
      output: capability.outputs[0] ?? "",
      params: "{}",
      included,
      contracts,
      bindings,
    };
    const next = [...stages, stage];
    setStages(next);
    publish(next);
  };

  const removeStage = (index: number) => {
    const next = stages.filter((_, i) => i !== index);
    setStages(next);
    publish(next);
  };

  const moveStage = (from: number, to: number) => {
    if (to < 0 || to >= stages.length) return;
    const next = [...stages];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setStages(next);
    publish(next);
  };

  return <div className="stage-builder">
    <div className="builder-heading">
      <label>Workflow name<input value={name} maxLength={160} onChange={(event) => {
        setName(event.target.value);
        try { emit(stages, event.target.value); setBuilderError(""); } catch (error) { setBuilderError(error instanceof Error ? error.message : "Stage form is invalid."); }
      }} /></label>
      <span>{stages.length} stage{stages.length === 1 ? "" : "s"} configured</span>
    </div>
    <div className="add-stage-row">
      <select value={selected} onChange={(event) => setSelected(Number(event.target.value))} disabled={!capabilities.length}>
        {capabilities.map((capability, index) =>
          <option value={index} key={index}>{capability.kind}{capability.engine ? " / " + capability.engine : ""}</option>,
        )}
      </select>
      <button className="light" onClick={addStage} disabled={!capabilities.length}>Add configured stage</button>
    </div>
    {stages.map((stage, index) => {
      const capability = capabilities[stage.capabilityIndex];
      return <article className="stage-card" key={index}>
        <div className="stage-title">
          <div><span className="stage-number">{String(index + 1).padStart(2, "0")}</span>
            <strong>{capability.kind}</strong><small>{capability.engine || "engine agnostic"}</small></div>
          <div className="stage-controls">
            <label className="enabled-toggle"><input type="checkbox" checked={stage.enabled} onChange={(event) => update(index, { enabled: event.target.checked })} /> Enabled</label>
            <button className="link" aria-label={"Move " + stage.id + " up"} disabled={index === 0} onClick={() => moveStage(index, index - 1)}>Up</button>
            <button className="link" aria-label={"Move " + stage.id + " down"} disabled={index === stages.length - 1} onClick={() => moveStage(index, index + 1)}>Down</button>
            <button className="link" onClick={() => removeStage(index)}>Remove</button>
          </div>
        </div>
        <div className="stage-fields">
          <label>Stage ID<input value={stage.id} pattern="[a-z][a-z0-9_]{0,62}" onChange={(event) => update(index, { id: event.target.value })} /></label>
          {capability.for_each.length > 0 && <label>Fan-out scope<select value={stage.forEach} onChange={(event) => update(index, { forEach: event.target.value })}>{capability.for_each.map((scope) => <option key={scope}>{scope}</option>)}</select></label>}
          <label>Output contract<select value={stage.output} onChange={(event) => update(index, { output: event.target.value })}>{capability.outputs.map((contract) => <option key={contract}>{contract}</option>)}</select></label>
        </div>
        <div className="ports">
          <div className="port-heading">INPUT PORTS <span>Contract compatibility is compiled by the API.</span></div>
          {capability.inputs.map((port) => <div className="port-row" key={port.name}>
            <label className="port-enabled"><input type="checkbox" checked={Boolean(stage.included[port.name])} onChange={(event) => update(index, { included: { ...stage.included, [port.name]: event.target.checked } })} />{port.name}{port.required ? " *" : ""}</label>
            {stage.included[port.name] && <>
              <select aria-label={port.name + " contract"} value={stage.contracts[port.name]} onChange={(event) => update(index, { contracts: { ...stage.contracts, [port.name]: event.target.value } })}>
                {port.contracts.map((contract) => <option key={contract}>{contract}</option>)}
              </select>
              <select aria-label={port.name + " source"} value={stage.bindings[port.name]} onChange={(event) => update(index, { bindings: { ...stage.bindings, [port.name]: event.target.value } })}>
                <option value={stage.bindings[port.name]?.startsWith("$") ? stage.bindings[port.name] : "$" + stage.id + "_" + port.name}>Workflow input</option>
                {stages.filter((_, sourceIndex) => sourceIndex !== index).map((source) => <option key={source.id} value={source.id}>Stage: {source.id}</option>)}
              </select>
            </>}
          </div>)}
        </div>
        <label className="params-label">Stage parameters (JSON)<textarea value={stage.params} onChange={(event) => update(index, { params: event.target.value })} spellCheck={false} /></label>
      </article>;
    })}
    {builderError && <div className="builder-error">{builderError}</div>}
    {!stages.length && <div className="empty-builder">Choose an installed stage capability and add it to begin. Port contracts and bindings are generated into the standard workflow definition.</div>}
  </div>;
}
