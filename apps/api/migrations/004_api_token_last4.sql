-- The last four characters of each API token's secret, kept at creation so a token can be recognised.
ALTER TABLE api_tokens ADD COLUMN last4 text NOT NULL DEFAULT '';
