import type { Palette } from "@/lib/api/gen/types.gen";
import type { StepNodeData } from "./graph";

const text = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : null);

/**
 * A step's name as a builder knows it: the app tool, agent or memory it uses, the question it decides, or what
 * its person is asked. Null when it has none yet; the canvas then shows the step's kind.
 */
export function stepTitle(data: StepNodeData, palette: Palette): string | null {
  const { config } = data;
  switch (data.type) {
    case "memory":
      return palette.spaces.find((s) => s.key === config.space)?.name ?? null;
    case "connector": {
      const tool = palette.tools.find((t) => t.ref === config.tool);
      return tool ? `${tool.app}: ${tool.name}` : null;
    }
    case "agent":
      return palette.agents.find((a) => a.key === config.agent)?.name ?? null;
    case "decision":
      return text(data.rules?.question);
    case "human_workforce":
    case "approval":
      return text(config.title);
    default:
      return null;
  }
}
