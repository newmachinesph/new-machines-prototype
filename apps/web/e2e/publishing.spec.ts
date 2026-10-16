import { expect, test, type Page, type Route } from "@playwright/test";
import {
  zAgent,
  zPalette,
  zPublisherEarnings,
  zPublisherSettings,
  zStudioListingDetail,
} from "../src/lib/api/gen/zod.gen";
import { presignIn, waitForPageReady } from "./helpers";

/**
 * Developer publishing, in the browser: Acme turns publishing on, submits an agent for review, and the listing
 * reaches Buyer's workspace once it is approved. Every API call the scenario makes is answered by the small
 * in-memory fake below (the real API is not touched); anything else goes on to the demo API. Approval is an ops
 * action in a separate app, so the fake applies it directly (the ops console and the API have their own tests).
 */

type Money = { amountMinor: number; currency: "USD" };
const usd = (amountMinor: number): Money => ({ amountMinor, currency: "USD" });

const AGENT_KEY = "org-acme--matcher";
const LISTING_ID = "lst_matcher";
const SUBMITTED_AT = "2026-10-16T09:00:00Z";
const PRICE = usd(30);
const PUBLISHER_NAME = "Acme Labs";

type Org = { orgId: string; orgName: string; userId: string; name: string };
const ACME: Org = { orgId: "org_acme", orgName: "Acme", userId: "user_ana", name: "Ana" };
const BUYER: Org = { orgId: "org_buyer", orgName: "Buyer", userId: "user_ben", name: "Ben" };

type VersionStatus = "checking" | "in_review" | "approved";

type Fake = {
  /** Who is signed in; read by every handler, so a test switches user by assigning it. */
  user: Org;
  /** Acme's publisher profile, once it has turned publishing on. */
  profile?: { name: string; description: string; payoutNote: string; updatedAt: string };
  /** The one listing: absent until Acme submits. */
  listing?: { status: VersionStatus };
  /** Writes the fake has seen, for the tests to assert on. */
  puts: unknown[];
  submissions: unknown[];
  /** Ops approves the listing, as the ops console would. */
  approve: () => void;
};

const cors = (route: Route) => {
  const headers = route.request().headers();
  return {
    "access-control-allow-origin": headers.origin ?? "*",
    "access-control-allow-headers": headers["access-control-request-headers"] ?? "*",
    "access-control-allow-methods": "GET,POST,PUT,DELETE,OPTIONS",
  };
};

const reply = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", headers: cors(route), body: JSON.stringify(body) });

/** The latest version as the API reports it (its check details too): the sandbox check is still running right
 * after the submission. */
function version(status: VersionStatus) {
  const sandbox =
    status === "checking"
      ? { name: "sandbox", state: "running", detail: "A sandbox run of this version is running.", runId: "run_sbx1" }
      : { name: "sandbox", state: "passed", detail: "The sandbox run completed.", runId: "run_sbx1" };
  return {
    id: "lv_1",
    definitionVersion: 1,
    status,
    price: PRICE,
    checks: [{ name: "definition", state: "passed", detail: "The definition checks found no problems." }, sandbox],
    submittedAt: SUBMITTED_AT,
    submittedBy: ACME.name,
    ...(status === "approved" ? { decidedAt: "2026-10-16T10:00:00Z", decidedBy: "ops" } : {}),
  };
}

function listingBody(status: VersionStatus) {
  const latest = version(status);
  return {
    id: LISTING_ID,
    kind: "agent",
    key: AGENT_KEY,
    name: "Matcher",
    status: status === "approved" ? "listed" : "pending",
    price: PRICE,
    latest,
    ...(status === "approved" ? { approvedVersion: 1 } : {}),
    installs: 0,
    runs30d: 0,
    earningsMonth: usd(0),
    simulated: true,
    versions: [latest],
  };
}

const matcherDraft = {
  name: "Matcher",
  summary: "Matches orders to payouts.",
  instructions: "Match each order to the payout that paid it.",
  modelProfile: "reasoning",
  skills: [],
  tools: [],
  maxTurns: 6,
};

/** The agent as Buyer's marketplace and palette list it, with the listing that carries publisher and fee. */
const marketListing = {
  listingId: LISTING_ID,
  publisher: PUBLISHER_NAME,
  fee: PRICE,
  feeUnit: "call",
  version: 1,
};

function listedAgent() {
  return {
    id: AGENT_KEY,
    version: "1",
    name: "Matcher",
    publisher: PUBLISHER_NAME,
    summary: matcherDraft.summary,
    capabilities: [],
    regions: [],
    certified: false,
    skills: [],
    tools: [],
    usedBy: [],
    listing: marketListing,
    source: "definition",
  };
}

function palette(fake: Fake) {
  const own = fake.user.orgId === ACME.orgId;
  const agents = own
    ? [{ key: AGENT_KEY, name: "Matcher", summary: matcherDraft.summary, builtByTeam: true, outputSchemaRef: "out" }]
    : fake.listing?.status === "approved"
      ? [
          {
            key: AGENT_KEY,
            name: "Matcher",
            summary: matcherDraft.summary,
            outputSchemaRef: "out",
            listing: marketListing,
          },
        ]
      : [];
  return { agents, tools: [], spaces: [], schemas: [] };
}

/** Answers one /v1 call from the fake; `undefined` means "not mine", and the request goes on to the demo API. */
function handle(
  fake: Fake,
  method: string,
  path: string,
  body: unknown,
): { status: number; body: unknown } | undefined {
  const org = `/v1/organizations/${fake.user.orgId}`;
  const own = fake.user.orgId === ACME.orgId;
  if (method === "GET" && path === "/v1/me") {
    const { orgId, orgName, userId, name } = fake.user;
    return { status: 200, body: { userId, name, orgId, orgName, role: "owner", workspace: "live" } };
  }
  if (path === `${org}/publisher`) {
    if (method === "GET") {
      return {
        status: 200,
        body: { enabled: !!fake.profile, ...(fake.profile ? { profile: fake.profile } : {}), simulated: true },
      };
    }
    if (method === "PUT") {
      fake.puts.push(body);
      fake.profile = {
        ...(body as { name: string; description: string; payoutNote: string }),
        updatedAt: SUBMITTED_AT,
      };
      return { status: 200, body: { enabled: true, profile: fake.profile, simulated: true } };
    }
  }
  if (method === "GET" && path === `${org}/studio/palette`) return { status: 200, body: palette(fake) };
  if (own && method === "GET" && path === `${org}/studio/agents/${AGENT_KEY}`) {
    return {
      status: 200,
      body: { key: AGENT_KEY, version: 1, publishedAt: SUBMITTED_AT, publishedBy: ACME.name, draft: matcherDraft },
    };
  }
  if (own && method === "POST" && path === `${org}/studio/agents/${AGENT_KEY}/submissions`) {
    fake.submissions.push(body);
    fake.listing = { status: "checking" };
    return { status: 201, body: listingBody("checking") };
  }
  if (own && method === "GET" && path === `${org}/studio/listings`) {
    if (!fake.listing) return { status: 200, body: [] };
    // The sandbox run finishes between the submission and the next read.
    if (fake.listing.status === "checking") fake.listing.status = "in_review";
    return { status: 200, body: [listingBody(fake.listing.status)] };
  }
  if (own && method === "GET" && path === `${org}/studio/listings/${LISTING_ID}` && fake.listing) {
    if (fake.listing.status === "checking") fake.listing.status = "in_review";
    return { status: 200, body: listingBody(fake.listing.status) };
  }
  if (own && method === "GET" && path === `${org}/studio/earnings`) {
    return { status: 200, body: { month: usd(0), payouts: [], simulated: true } };
  }
  if (method === "GET" && path === "/v1/agents") {
    const visible = !own && fake.listing?.status === "approved";
    return { status: 200, body: visible ? [listedAgent()] : [] };
  }
  // The Settings page also lists the workspace's policies, members and tokens; the demo API knows no such org.
  if (method === "GET" && path === org) {
    const { orgId, orgName } = fake.user;
    const body = {
      id: orgId,
      name: orgName,
      short: orgName,
      plan: "Live",
      monthlyCap: usd(0),
      monthSpent: usd(0),
      region: "us",
    };
    return { status: 200, body };
  }
  if (method === "GET" && (path === `${org}/policies` || path === `${org}/members` || path === "/v1/tokens")) {
    return { status: 200, body: [] };
  }
  if (method === "GET" && path === "/v1/workflow-packs") return { status: 200, body: [] };
  if (method === "GET" && path === "/v1/catalog/taxonomy")
    return { status: 200, body: { functions: [], industries: [] } };
  return undefined;
}

async function installFake(page: Page, user: Org): Promise<Fake> {
  const fake: Fake = {
    user,
    puts: [],
    submissions: [],
    approve: () => {
      if (fake.listing) fake.listing.status = "approved";
    },
  };
  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors(route) });
      return;
    }
    const answer = handle(fake, request.method(), new URL(request.url()).pathname, request.postDataJSON());
    if (!answer) {
      await route.continue();
      return;
    }
    await reply(route, answer.status, answer.body);
  });
  return fake;
}

/** The pack editor shows its steps first; the palette is behind the side panel's "Add" switch. */
async function openPalette(page: Page) {
  await page.getByRole("group", { name: "Side panel" }).getByRole("button", { name: "Add" }).click();
}

test("the fake answers in the shapes the contract describes", () => {
  // Contract drift (a renamed field, a new status) fails here rather than passing against a stale fake.
  for (const status of ["checking", "in_review", "approved"] as const) {
    expect(zStudioListingDetail.safeParse(listingBody(status)).error).toBeUndefined();
  }
  const profile = { name: PUBLISHER_NAME, description: "", payoutNote: "", updatedAt: SUBMITTED_AT };
  expect(zPublisherSettings.safeParse({ enabled: true, profile, simulated: true }).error).toBeUndefined();
  expect(zPublisherEarnings.safeParse({ month: usd(0), payouts: [], simulated: true }).error).toBeUndefined();
  expect(zAgent.safeParse(listedAgent()).error).toBeUndefined();
  const buyer = { user: BUYER, listing: { status: "approved" } } as Fake;
  expect(zPalette.safeParse(palette(buyer)).error).toBeUndefined();
  expect(zPalette.safeParse(palette({ ...buyer, user: ACME })).error).toBeUndefined();
});

test("a listed agent reaches another workspace after review", async ({ page, context }) => {
  await presignIn(context);
  const fake = await installFake(page, ACME);

  // 1. Ana turns publishing on.
  await page.goto("/app/settings");
  await page.getByRole("button", { name: "Turn on publishing" }).click();
  await page.getByLabel("Publisher name").fill(PUBLISHER_NAME);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Publishing is on.").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Turn off publishing" })).toBeVisible();
  expect(fake.profile?.name).toBe(PUBLISHER_NAME);
  expect(fake.puts).toHaveLength(1);

  // 2. She submits the Matcher agent for review at $0.30 per call.
  await page.goto(`/studio/agents/${AGENT_KEY}`);
  await page.getByRole("button", { name: "Submit for review" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Price per call").fill("0.30");
  await dialog.getByRole("button", { name: "Submit for review" }).click();
  await expect(dialog.getByText("Sandbox test")).toBeVisible();
  // The dialog reads the listing again while it is checking, so it moves on to "Sent for review" by itself.
  await expect(dialog.getByRole("status")).toHaveText("Sent for review");
  expect(fake.submissions).toEqual([{ priceMinor: 30 }]);

  // 3. The Publisher tab shows it in review.
  await page.goto("/studio/publisher");
  const row = page.getByRole("row", { name: /Matcher/ });
  await waitForPageReady(page, row);
  await expect(row.getByText("In review")).toBeVisible();

  // 6. Before the approval, Ben sees nothing of it: not in the marketplace, not in the palette.
  fake.user = BUYER;
  await page.goto("/app/marketplace?view=agents");
  await expect(page.getByText("No agents are listed by other publishers yet.")).toBeVisible();
  // Assert absence only once the palette has been fetched and the opened palette shows its search box.
  const paletteLoaded = page.waitForResponse((r) => r.url().endsWith("/studio/palette") && r.ok());
  await page.goto("/studio/packs/new");
  await paletteLoaded;
  await openPalette(page);
  await expect(page.getByRole("searchbox")).toBeVisible();
  await expect(page.getByRole("heading", { name: "From other workspaces" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Matcher/ })).toHaveCount(0);

  // 4. Ops approves the listing.
  fake.approve();

  // 5. Now Ben sees it with its publisher and fee, and can use it in a pack.
  await page.goto("/app/marketplace?view=agents");
  const card = page.getByRole("listitem").filter({ has: page.getByRole("link", { name: "Matcher" }) });
  await waitForPageReady(page, card);
  await expect(card.getByText(`By ${PUBLISHER_NAME}`)).toBeVisible();
  await expect(card.getByText("$0.30 per call")).toBeVisible();

  await page.goto("/studio/packs/new");
  await openPalette(page);
  await expect(page.getByRole("heading", { name: "From other workspaces" })).toBeVisible();
  const matcher = page.getByRole("button", { name: /Matcher/ });
  await expect(matcher).toBeVisible();
  await expect(matcher).toContainText(`By ${PUBLISHER_NAME} · $0.30 per call`);
});

test("the Japanese marketplace shows the fee", async ({ page, context }) => {
  await presignIn(context);
  const fake = await installFake(page, BUYER);
  fake.listing = { status: "approved" };

  await page.goto("/app/marketplace?view=agents");
  await expect(page.getByRole("link", { name: "Matcher" })).toBeVisible();
  await page
    .getByRole("button", { name: /switch workspace/ })
    .first()
    .click();
  await page.getByRole("menuitemradio", { name: "日本語" }).click();
  await page.goto("/app/marketplace?view=agents");
  await expect(page.locator("html")).toHaveAttribute("lang", "ja");
  await expect(page.getByText(`提供元: ${PUBLISHER_NAME}`)).toBeVisible();
  await expect(page.getByText("1回の呼び出しあたり$0.30", { exact: true })).toBeVisible();
});
