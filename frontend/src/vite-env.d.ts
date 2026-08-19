/// <reference types="vite/client" />

// Lets TypeScript understand `import placeholder from './x.png'` — Vite rewrites those to the
// hashed asset URL at build time, but the compiler needs telling that the module exists.

/**
 * The released version, substituted at build time by `vite.config.ts` — the git tag in CI, a
 * `git describe` locally. Deliberately not read from `package.json`, whose version has never
 * tracked the releases and would report an authoritative-looking lie.
 */
declare const __APP_VERSION__: string
