/** Whether `url` is a secure web address the browser may be sent to. Anything else (a `javascript:` value, plain http, junk) is not. */
export function isSecureUrl(url: string): boolean {
  try {
    return new URL(url).protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * Leave the app for another site, such as an app's own sign-in page. Only a secure web address is followed;
 * the answer says whether the browser left. Its own module so tests can replace it.
 */
export function leaveFor(url: string): boolean {
  if (!isSecureUrl(url)) return false;
  window.location.assign(url);
  return true;
}
