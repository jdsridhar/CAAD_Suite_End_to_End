import { DefaultPluginUISpec } from "molstar/lib/mol-plugin-ui/spec";
import { createPluginUI } from "molstar/lib/mol-plugin-ui";
import { renderReact18 } from "molstar/lib/mol-plugin-ui/react18";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";

type ViewerOptions = {
  layoutIsExpanded: boolean;
  layoutShowLeftPanel?: boolean;
};

export async function createMolstarViewer(
  target: HTMLElement,
  options: ViewerOptions,
): Promise<PluginUIContext> {
  const spec = DefaultPluginUISpec();
  spec.layout = {
    initial: {
      isExpanded: options.layoutIsExpanded,
      showControls: true,
      controlsDisplay: "reactive",
      regionState: {
        bottom: "full",
        left: options.layoutShowLeftPanel === false ? "hidden" : "full",
        right: "hidden",
        top: "full",
      },
    },
  };
  return createPluginUI({ target, spec, render: renderReact18 });
}
