"use client";

import { type ReactElement, useId } from "react";
import { Tooltip } from "./base";

export const READ_ONLY_TEXT = "Support access is read-only";

/**
 * Wraps a disabled action for the support role. The wrapper takes focus so keyboard and pointer users can
 * learn why it is off; the button keeps its own name and the reason is attached as a description.
 */
export function ReadOnly({ children }: { children: ReactElement }) {
  const id = useId();
  return (
    <Tooltip label={READ_ONLY_TEXT}>
      <span tabIndex={0} aria-describedby={id} className="inline-flex rounded-md">
        {children}
        <span id={id} hidden>
          {READ_ONLY_TEXT}
        </span>
      </span>
    </Tooltip>
  );
}
