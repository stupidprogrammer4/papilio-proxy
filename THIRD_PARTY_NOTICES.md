# Third-party licenses

The root [GPL-3.0-only license](LICENSE) applies to original Papilio project code.
Dependencies retain their own copyright and license terms. Do not replace upstream
license notices when distributing source or bundled dependencies.

## Principal dependencies

| Dependency | License source |
| --- | --- |
| Papilio | MIT in the installed framework's distribution license; the application package itself is a separate project |
| Papilio Tasks | MIT in its installed distribution metadata |
| FastAPI, SQLModel, SQLAlchemy, Alembic | MIT in their installed distribution metadata |
| aiogram, Pydantic, Taskiq, Taskiq Redis | MIT in their installed distribution metadata |
| aiohttp | Apache-2.0 AND MIT in its installed distribution metadata |
| HTTPX | BSD-3-Clause in its installed distribution metadata |
| Pillow | MIT-CMU in its installed distribution metadata |
| qrcode | BSD in its installed distribution metadata; retain its supplied license text |
| Vue | MIT in its supplied package license |
| Vue I18n | MIT in its supplied package metadata and license |
| Xray-core | MPL-2.0 in the pinned `v1.260327.0` module's `LICENSE` |

Package manifests and lockfiles identify the dependencies used by each component.
This is a principal-dependency inventory, not a complete transitive license manifest
or a compatibility certification for every build. Distribution of bundled images,
fonts, Android tools or optional cores requires retaining their supplied notices
and completing the corresponding release inventory.

Referenced projects are research sources, not a grant to copy their code.

## Papilio logo assets

`panel/frontend/apps/panel/public/papilio-logo-dark.png` and
`papilio-logo-light.png` are copied from `docs/assets/logo-dark.png` and
`docs/assets/logo-light.png` in the Papilio framework repository (upstream
commit `5226257`). They retain the upstream MIT license and copyright notice:

```text
MIT License
Copyright (c) 2026 عمو پویا

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```
