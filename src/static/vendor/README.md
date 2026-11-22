# Vendored front-end libraries

Self-hosted copies of third-party libraries, pinned to an exact version. Each folder
holds the library's own LICENSE file. Templates load them with `url_for('static', ...)`.
Downloaded 2026-11-22 over HTTPS.

| Library | Version | Licence | Source | SHA-384 |
|---|---|---|---|---|
| htmx | 1.9.12 | 0BSD (Zero-Clause BSD) | https://unpkg.com/htmx.org@1.9.12 | `sha384-ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2` (matches the integrity hash the app used before) |
| Alpine.js | 3.17.5 | MIT | https://cdn.jsdelivr.net/npm/alpinejs@3.17.5/dist/cdn.min.js (what `alpinejs@3.x.x` resolved to; same bytes). LICENSE from https://github.com/alpinejs/alpine (the npm package has none) | `sha384-FYLKjwG3aohNhNZoVG8sY/5ntunm+MqylL90Q+rT3OM7AwV9/BKFjk/RjoIpIgsI` |
| ApexCharts | 4.7.0 | MIT | https://cdn.jsdelivr.net/npm/apexcharts@4.7.0/dist/apexcharts.min.js | `sha384-Hf0cGsweCbozkRP14s5KIue6STJYKaoipB/i1gTdbX+umKD59qA/Szk42FPMuKtB` |
| Cropper.js (JS) | 1.6.2 | MIT | https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.2/cropper.min.js | `sha384-jrOgQzBlDeUNdmQn3rUt/PZD+pdcRBdWd/HWRqRo+n2OR2QtGyjSaJC0GiCeH+ir` (sha512 matches the old integrity attribute) |
| Cropper.js (CSS) | 1.6.2 | MIT | https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.2/cropper.min.css | `sha384-6LFfkTKLRlzFtgx8xsWyBdKGpcMMQTkv+dB7rAbugeJAu1Ym2q1Aji1cjHBG12Xh` (sha512 matches the old integrity attribute) |

## Why ApexCharts is 4.7.0, not the latest

The app used the unpinned "latest" ApexCharts, which is now 8.9.1. Since version 5 the
package is no longer MIT: it ships a dual Community/Commercial licence (free only for
organisations under 2M USD revenue, with an OEM licence needed for products used by other
people). 4.7.0 is the last MIT release, so it is pinned here. Check the licence before
upgrading past 4.x.
