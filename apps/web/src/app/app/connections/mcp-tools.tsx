"use client";

import { useTranslations } from "next-intl";
import { Checkbox, useToast } from "@/components/base";
import type { McpServer, McpTool } from "@/lib/api/gen/types.gen";
import { useErrorText } from "@/lib/api/use-error-text";
import { useSwitchMcpTool } from "@/lib/queries/mcp";
import { useOrgId } from "@/lib/queries/me";

const GROUPS = ["read", "write", "blocked"] as const;

/** The server's tools in the groups a pack meets them in, each with an on/off switch. A blocked tool stays
 * off. Members see the groups without switches (`canSwitch` false). */
export function McpToolGroups({ server, canSwitch = true }: { server: McpServer; canSwitch?: boolean }) {
  const t = useTranslations("connections.mcp");
  const orgId = useOrgId() ?? "";
  const { on, off } = useSwitchMcpTool();
  const toast = useToast();
  const errorText = useErrorText();
  const flip = (tool: McpTool, checked: boolean) =>
    (checked ? on : off).mutate(
      { path: { org_id: orgId, server_id: server.id, tool_id: tool.id } },
      { onError: (err) => toast(t("switchFailed"), errorText(err), "blocked") },
    );
  return (
    <div className="mt-4 space-y-4">
      {GROUPS.map((group) => {
        const tools = server.tools.filter((tool) => tool.toolClass === group);
        if (!tools.length) return null;
        const heading = `mcp-${server.id}-${group}`;
        return (
          <section key={group} aria-labelledby={heading}>
            <h3 id={heading} className="text-sm font-semibold">
              {t(`group.${group}`)}
            </h3>
            <p className="mt-0.5 text-xs text-muted">{t(`groupNote.${group}`)}</p>
            <ul className="mt-2 space-y-2">
              {tools.map((tool) => (
                <li key={tool.id}>
                  <Checkbox
                    checked={tool.on && group !== "blocked"}
                    disabled={!canSwitch || group === "blocked"}
                    onCheckedChange={(checked) => flip(tool, checked)}
                    describedBy={`${heading}-${tool.id}-why`}
                  >
                    <span className="font-medium">{tool.name}</span>
                  </Checkbox>
                  <p id={`${heading}-${tool.id}-why`} className="ml-7 text-xs text-muted">{t(`why.${tool.why}`)}</p>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
