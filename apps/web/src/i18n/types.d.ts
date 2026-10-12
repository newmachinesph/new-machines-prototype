import type en from "../../messages/en.json";
import type { Locale } from "./locales";

// Makes t("some.key") a compile error when the key is not in en.json.
declare module "next-intl" {
  interface AppConfig {
    Locale: Locale;
    Messages: typeof en;
  }
}
