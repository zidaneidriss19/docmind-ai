# DocMind AI

Application web pour interroger des documents PDF.

- `apps/web` contient le frontend React et TypeScript, construit avec Vite.
- `apps/api` contient l’API FastAPI.

## Frontend

Depuis la racine du dépôt, dans PowerShell.

```powershell
Set-Location apps/web
npm.cmd ci
npm.cmd run dev
```

## API

Dans une autre fenêtre PowerShell, depuis la racine du dépôt.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r apps/api/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir apps/api --reload
```

La route de santé est disponible sur http://127.0.0.1:8000/health et la documentation interactive sur http://127.0.0.1:8000/docs.

## Services locaux

Démarre Docker Desktop avec le moteur Linux. Depuis la racine du dépôt, copie la configuration la première fois, puis démarre les services.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up -d --wait
docker compose ps
```

| Service | Adresse locale |
| --- | --- |
| PostgreSQL 17 avec pgvector | 127.0.0.1:5432 |
| Redis 8 | 127.0.0.1:6379 |
| API MinIO | http://127.0.0.1:9000 |
| Console MinIO | http://127.0.0.1:9001 |

Les identifiants d’exemple sont prévus pour le développement local. Utilise les valeurs de `MINIO_ROOT_USER` et `MINIO_ROOT_PASSWORD` dans `.env` pour te connecter à la console MinIO. Si un port est occupé, modifie sa valeur dans `.env`.

PostgreSQL active l’extension `vector` lors de la première initialisation du volume. Pour arrêter les services en conservant leurs données, exécute `docker compose down`.

## Vérifications de qualité

Depuis la racine du dépôt, après avoir préparé le frontend et l’environnement Python.

```powershell
npm.cmd --prefix apps/web run lint
npm.cmd --prefix apps/web run build

.\.venv\Scripts\python.exe -m pip install -r apps/api/requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check apps/api
.\.venv\Scripts\python.exe -m ruff format --check apps/api
Push-Location apps/api
try { ..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v }
finally { Pop-Location }
```

GitHub Actions exécute ces contrôles sur les contributions vers `main` et les envois sur `main`. La vérification du frontend inclut TypeScript. Le test de l’API couvre `GET /health` et fonctionne sans Docker.
