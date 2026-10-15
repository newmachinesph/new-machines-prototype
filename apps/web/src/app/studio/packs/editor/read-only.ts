import { createContext, useContext } from "react";

/**
 * True while the signed-in member may only read the open pack. The pack editor provides it; the settings forms
 * pass it to the Base UI controls (Select, Menu, Checkbox), which a disabled fieldset does not reach on its own.
 */
export const ReadOnlyContext = createContext(false);

export const useReadOnly = () => useContext(ReadOnlyContext);
