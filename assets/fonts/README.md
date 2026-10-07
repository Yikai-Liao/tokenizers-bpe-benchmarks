# Plot fonts

Unmodified Liberation Sans 2.1.5 regular and bold, distributed by Debian's
`fonts-liberation` package under the SIL Open Font License (see [LICENSE](LICENSE)).
Liberation Sans is a metrically compatible alternative to Arial, included in the
Nature Figure skill's sans-serif fallback guidance. These exact files are copied
into the Docker image and explicitly registered before rendering. Reports record
their SHA-256 in `fonts.json`; rendering fails if another font is resolved.
