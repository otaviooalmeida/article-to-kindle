# Vendored Mozilla Readability

`Readability.js` is the unmodified browser script from the npm release
[`@mozilla/readability@0.6.0`](https://www.npmjs.com/package/@mozilla/readability/v/0.6.0).
It is bundled locally for Chrome's extension content-script injection; no CDN,
model download, or build step is required.

Source package: `https://registry.npmjs.org/@mozilla/readability/-/readability-0.6.0.tgz`

The package's SHA-512 integrity was verified against npm metadata when vendored.
SHA-256 of `Readability.js`:

```text
34dcab3d0832d0019f02990eed6b6124e029e8c32b9f0c6f2550544ff8dff174
```

The release's copyright/license notice is in `LICENSE.md`; the complete Apache
2.0 license is in `Apache-2.0.txt`. `NOTICE` records the upstream project credits.
Upstream project: https://github.com/mozilla/readability.

Application code must not display the raw extractor output or treat it as safe
HTML. The capture code uses its source-node references to locate original article
material; the existing preview and backend sanitizers still apply.
