<div align="center">

# LiquidPilot

### A local browser agent with an explicitly paired Chrome tab

![Source release](https://img.shields.io/badge/release-source-2563eb?style=flat-square)
![Local first](https://img.shields.io/badge/design-local--first-0f766e?style=flat-square)

**Coded by [zaid.dev](https://github.com/gamerock587)** · **invnty**

Python · React · TypeScript

</div>

---

## What it does

- Pair an existing Chrome tab without exporting its cookies
- Structured navigation and table exports
- Local decision model and task history

## Quick start

**Requirements:** Windows, Python 3.12+, Node.js, compatible d1 model, projector and llama.cpp runtime.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
python main.py
```

## Before you run

Copy config/settings.example.json to config/settings.json and configure your model/runtime paths. Model binaries are not included. Browser actions can change websites; review approvals and SECURITY.md. This is an experimental structured agent, not a general-purpose autonomous browser.

## Documentation

See [USAGE.md](USAGE.md) for the original detailed operating guide.

## Privacy and configuration

This source export excludes local credentials, databases, sessions, logs, recordings,
personal spreadsheets and compiled distributions. Supply your own configuration.
The ignore rules help prevent accidental commits; they do not replace reviewing files.

## Contributing

Describe the problem, include reproducible steps with synthetic data, and keep changes focused.
Never include tokens, private recordings, customer data or personal contact lists in an issue.
Validation and remaining limitations are recorded in [RELEASE_REVIEW.md](RELEASE_REVIEW.md).

## License and attribution

Original application code is licensed under [MIT](LICENSE). Third-party components retain
their own licenses and authorship; see THIRD-PARTY-NOTICES.md and any bundled license files.
