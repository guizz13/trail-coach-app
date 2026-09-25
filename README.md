# Coach Hybride

Application personnelle de coaching (trail, squash, musculation). Spécification : [CLAUDE.md](CLAUDE.md).

## Lancer

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export COACH_PASSWORD='un-mot-de-passe-long'   # obligatoire : l'app refuse de démarrer sans
export ANTHROPIC_API_KEY='sk-ant-...'           # facultatif : sans clé, import et historique fonctionnent, l'analyse LLM est signalée indisponible
.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Données : `data/coach.db` et `data/usage_llm.json` (modifiable via `COACH_DATA_DIR`).
Derrière un reverse proxy HTTPS, lancer uvicorn avec `--proxy-headers` pour que le cookie de session soit marqué `Secure`.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

Les tests importent les 5 fichiers Suunto réels de `docs/` et n'appellent jamais l'API Anthropic (client LLM factice).
