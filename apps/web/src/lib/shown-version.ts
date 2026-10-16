import type { MarketplaceListing } from "@/lib/api/gen/types.gen";

/** The version the Studio writes into a definition it builds: `1.0.<definition version>`. */
const STUDIO_VERSION = /^1\.0\.(\d+)$/;

/**
 * The version of an agent or pack as a customer should read it. A listed definition is known by its approved
 * definition version, and one built in the Studio by its definition version (the Studio writes `1.0.<n>` into
 * it, which would read as "1.0.1" for version 1). A platform definition keeps the version its authors gave it.
 */
export function shownVersion(item: { version: string; builtByTeam?: boolean; listing?: MarketplaceListing }): string {
  if (item.listing) return String(item.listing.version);
  const studio = item.builtByTeam ? STUDIO_VERSION.exec(item.version) : null;
  return studio ? studio[1]! : item.version;
}
