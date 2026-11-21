/** Which links the app opens in the user's browser (never inside the app window): secure web
 * pages, and the apps H.E.X runs on this computer (`http://localhost:<port>`, PRD D71). Anything
 * else (file:, javascript:, http to another host) is not opened. */
const LOCAL_APP = /^http:\/\/(localhost|127\.0\.0\.1):\d{1,5}(\/[^\s]*)?$/

export function openableInBrowser(url: string): boolean {
  return url.startsWith('https://') || LOCAL_APP.test(url)
}
