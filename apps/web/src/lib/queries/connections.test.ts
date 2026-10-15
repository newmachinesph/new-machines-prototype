import { describe, expect, it } from "vitest";
import type { Connection as ApiConnection } from "@/lib/api/gen/types.gen";
import type { Connection } from "@/lib/types";
import { withRevoked } from "./org";
import { connectorKey, findConnection, replaceConnection, withGrantRevoked } from "./workspace";

/** A row as the API sends it: no `revoked` unless given. */
const apiRow = (over: Partial<ApiConnection>): ApiConnection => ({
  app: "Stripe",
  key: "stripe",
  account: "",
  status: "not_connected",
  provider: "Mock",
  oauthScopes: [],
  grants: [],
  ...over,
});
/** A row as the UI reads it. */
const conn = (over: Partial<Connection>): Connection => ({ ...apiRow({}), revoked: [], ...over });

describe("withRevoked", () => {
  it("fills in the revoked list the API may leave out, and keeps one it sends", () => {
    const sent = conn({ revoked: [{ install: "Pack", capability: "payment.refund" }] });
    expect(withRevoked([apiRow({}), sent])).toEqual([conn({}), sent]);
  });
});

describe("withGrantRevoked", () => {
  const grant = { install: "Pack", capability: "payment.refund" };
  const row = conn({
    grants: [
      { ...grant, access: "write" },
      { install: "Pack", capability: "payment.read", access: "read" },
    ],
  });

  it("takes the grant off the card and remembers it as revoked", () => {
    expect(withGrantRevoked(row, grant)).toEqual({
      ...row,
      grants: [{ install: "Pack", capability: "payment.read", access: "read" }],
      revoked: [grant],
    });
  });

  it("remembers a grant once however often it is revoked", () => {
    const once = withGrantRevoked(row, grant);
    expect(withGrantRevoked(once, grant).revoked).toEqual([grant]);
  });

  it("copes with a row the API sent without a revoked list", () => {
    expect(withGrantRevoked(apiRow({ grants: row.grants }), grant).revoked).toEqual([grant]);
  });
});

describe("connectorKey", () => {
  it("is the connector key, or the app name for demo rows without one", () => {
    expect(connectorKey(conn({}))).toBe("stripe");
    expect(connectorKey(conn({ key: undefined, app: "Slack" }))).toBe("Slack");
  });
});

describe("replaceConnection", () => {
  it("replaces the card of the same connector key and keeps the others", () => {
    const old = [conn({}), conn({ app: "Shopify", key: "shopify" })];
    const pending = conn({ status: "pending", mode: "composio", provider: "Composio" });
    expect(replaceConnection(old, pending)).toEqual([pending, old[1]]);
  });

  it("matches by app name when there is no key (demo rows)", () => {
    const old = [conn({ key: undefined, app: "Slack" })];
    const next = conn({ key: undefined, app: "Slack", status: "connected" });
    expect(replaceConnection(old, next)).toEqual([next]);
  });

  it("leaves an empty cache empty", () => {
    expect(replaceConnection(undefined, conn({}))).toBeUndefined();
  });
});

describe("findConnection", () => {
  const conns = [conn({}), conn({ app: "Shopify", key: "shopify" }), conn({ key: undefined, app: "Slack" })];

  it("finds the connection of a connector key from the sign-in return (?connected=<key>)", () => {
    expect(findConnection(conns, "shopify")).toBe(conns[1]);
    expect(findConnection(conns, "Slack")).toBe(conns[2]);
  });

  it("gives nothing for a key the workspace does not list, or when nothing is loaded", () => {
    expect(findConnection(conns, "gmail")).toBeUndefined();
    expect(findConnection(conns, "")).toBeUndefined();
    expect(findConnection(undefined, "stripe")).toBeUndefined();
  });
});
