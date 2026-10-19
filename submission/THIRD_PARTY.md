# Third-party resources

Versions are the ones installed in the verified build (`backend/.venv`, `frontend/node_modules`, read from package metadata on 2026-10-08). Licences are read from the same metadata. Only direct dependencies are listed; transitive packages are in `backend/pyproject.toml` resolution and `frontend/package-lock.json`.

## Dataset

| Resource | Version | Licence | Link | Used for | In submission zip |
|---|---|---|---|---|---|
| HAI (HIL-based Augmented ICS) security dataset, ETRI | 20.07 (`train1`, `test1`, `test2`) | **Ambiguous in the source.** See below. | https://github.com/icsdataset/hai | Optional HAI mode, HAI rows of the evaluation | No |

### HAI licence terms (re-read 2026-10-08 from https://github.com/icsdataset/hai, `README.md`)
- Section "License" (applies to "This work"): "This work is licensed under a Creative Commons Attribution-ShareAlike License (CC BY-SA 4.0)" with link http://creativecommons.org/licenses/by-sa/4.0/.
- Section "Dataset Metadata" (schema.org block for "HIL-based Augmented ICS Security Dataset", provider "The Affiliated Institute of ETRI, South Korea"): licence name "CC BY 4.0", url https://creativecommons.org/licenses/by/4.0/.
- No `LICENSE` file in the repo root or in `hai-20.07/` (GitHub API listing: README.md, graph, hai-20.07, hai-21.03, hai-22.04, hai-23.05, hai_dataset_technical_details.pdf, haiend-23.05; GitHub reports no detected licence). `hai-20.07/` holds only the CSV files.
- **Status: ambiguous. Dataset not redistributed.** The raw files stay out of the zip and out of the repo (`data/hai/` is git-ignored). We follow the stricter CC BY-SA 4.0 for any derived use and give attribution.
- Citation requested by the authors: Shin, Lee, Yun, Kim. "HAI 1.0: HIL-Based Augmented ICS Security Dataset". USENIX CSET 2020. ETRI, Daejeon, South Korea.
- Open action: ask the HAI maintainers (GitHub issue on icsdataset/hai) to state one licence, if the data or derived data is ever redistributed.

Phase 11 added no dependency. The incident PDF is written by `backend/app/report/pdf.py` (standard library only, built-in Helvetica fonts). The API key check, rate limiter and demo-mode switch are in `backend/app/api/security.py` (standard library).

## Backend (Python 3.11)

| Library | Version | Licence | Link |
|---|---|---|---|
| FastAPI | 0.142.2 | MIT | https://github.com/fastapi/fastapi |
| Uvicorn | 0.54.0 | BSD-3-Clause | https://github.com/encode/uvicorn |
| websockets (via uvicorn[standard]) | 17.2 | BSD-3-Clause | https://github.com/python-websockets/websockets |
| Pydantic | 2.13.5 | MIT | https://github.com/pydantic/pydantic |
| NumPy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| pandas | 3.0.6 | BSD-3-Clause | https://pandas.pydata.org |
| SciPy | 1.17.1 | BSD (OSI classifier in metadata) | https://scipy.org |
| scikit-learn | 1.9.1 | BSD-3-Clause | https://scikit-learn.org |
| PyTorch (CPU wheel from download.pytorch.org) | 2.14.1 | BSD-3-Clause and others (metadata lists Apache-2.0, BSD-2-Clause, BSL-1.0, MIT) | https://pytorch.org |
| NetworkX | 3.6.1 | BSD-3-Clause | https://networkx.org |
| statsmodels | 0.15.0 | BSD-3-Clause | https://www.statsmodels.org |

Dev only: pytest 9.1.1 (MIT), pytest-asyncio 1.4.0 (Apache-2.0), httpx 0.28.1 (BSD-3-Clause), Ruff 0.16.10 (MIT), mypy 2.4.0 (MIT).

LIVE mode (Phase 13) added two dependencies:

| Library | Version | Licence | Link |
|---|---|---|---|
| pymodbus | 3.15.0 | BSD-3-Clause | https://github.com/pymodbus-dev/pymodbus |
| PyYAML | 6.0.3 | MIT | https://github.com/yaml/pyyaml |

pymodbus is used both ways: as the read-only client in `backend/app/live/modbus.py`, and as the Modbus TCP server inside `plant_emulator/` (which is not part of the backend and ships only to run the demo's own emulated plant). PyYAML loads `config/tagmap.yaml`. No MQTT or OPC UA dependency was added; the live-ingestion plan's optional scope for those was skipped.

## Frontend (Node 22)

| Library | Version | Licence | Link |
|---|---|---|---|
| React / React DOM | 18.3.1 | MIT | https://react.dev |
| @xyflow/react (React Flow) | 12.12.0 | MIT | https://reactflow.dev |
| Apache ECharts | 6.1.0 | Apache-2.0 | https://echarts.apache.org |
| echarts-for-react | 3.0.6 | MIT | https://github.com/hustcc/echarts-for-react |
| Framer Motion | 14.0.0 | MIT | https://www.framer.com/motion |
| lucide-react | 1.52.0 | ISC | https://lucide.dev |
| Zustand | 5.0.15 | MIT | https://github.com/pmndrs/zustand |

Dev only: Vite 5.4.21 (MIT), Vitest 2.1.9 (MIT), Tailwind CSS 3.4.19 (MIT), TypeScript 5.9.3 (Apache-2.0), ESLint 9.39.5 (MIT), Playwright 1.63.0 (Apache-2.0; downloads a Chromium build for tests).

## External services, fonts and reference data

| Resource | Licence | Link | How used |
|---|---|---|---|
| Inter, JetBrains Mono (Google Fonts) | SIL Open Font License 1.1 (as published by Google Fonts; not re-verified here) | https://fonts.google.com | Loaded by the browser from `fonts.googleapis.com` at page load (`frontend/index.html`). Offline, the UI uses fallback fonts. |
| MITRE ATT&CK for ICS | MITRE ATT&CK terms of use (not re-verified here) | https://attack.mitre.org | Technique IDs and names T0856, T0831, T0855 are typed into `backend/app/attacks/engine.py`. No data is fetched at runtime. |
| Docker base images `python:3.11-slim`, `node:22-slim` | Per image (Debian and language runtimes) | https://hub.docker.com | Container build only. |

React Flow attribution: the graph view shows the "React Flow" attribution link. React Flow's documentation (https://reactflow.dev/learn/troubleshooting/remove-attribution, read 2026-10-08) allows removing it only with a React Flow Pro subscription and says to remove it only then. The library is MIT, but the page does not say that the MIT licence permits hiding it for free users. We keep the attribution.

No paid API, API key, or network call to a third-party service is made by the backend at runtime. The only runtime request outside localhost is the font load above.
