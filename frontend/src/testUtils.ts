/**
 * Helpers shared by the test files. Nothing in the app imports this module, so Vite never
 * bundles it.
 */

/**
 * Every `class="..."` attribute value found in the rendered markup, split into individual
 * tokens. Reads serialised HTML rather than `element.className` on purpose: an SVG
 * element's `className` is an `SVGAnimatedString`, not a plain string, so a uniform scan
 * over markup (which serialises `class="..."` identically for HTML and SVG elements) is
 * simpler and correct for both, and it is also what the numbers page's "never reveals"
 * scan of `container.innerHTML` already does.
 */
export function classTokensIn(container: HTMLElement): string[] {
  return [...container.innerHTML.matchAll(/class="([^"]*)"/g)].flatMap((match) =>
    match[1].split(/\s+/).filter((token) => token.length > 0),
  )
}
