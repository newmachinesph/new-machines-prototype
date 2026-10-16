/** The roles that build in the Studio and see publishing (the API's `require_builder` and
 * `publishers.require_manager`): owners and admins. Members read the Studio only. */
export const MANAGERS: ReadonlySet<string> = new Set(["owner", "admin"]);

export const isManager = (role: string | undefined) => MANAGERS.has(role ?? "");
