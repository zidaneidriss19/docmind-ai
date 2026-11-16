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
.\.venv\Scripts\python.exe -m ruff check apps/api/app apps/api/tests apps/api/migrations
.\.venv\Scripts\python.exe -m ruff format --check apps/api/app apps/api/tests apps/api/migrations
Push-Location apps/api
try { ..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v }
finally { Pop-Location }
```

GitHub Actions exécute ces contrôles sur les contributions vers `main` et les envois sur `main`. La vérification du frontend inclut TypeScript. Le test de santé fonctionne sans PostgreSQL. La CI démarre PostgreSQL pour tester l’authentification et vérifier les migrations.

## Inscription et connexion (M1)

Pour lancer M1 seul pendant que l’infrastructure complète est en attente, utilise PostgreSQL 18 avec le fichier Compose dédié et son volume indépendant. Depuis la racine du dépôt dans PowerShell, avec Docker Desktop démarré.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose -f compose.auth.yaml up -d --wait
.\.venv\Scripts\python.exe -m pip install -r apps/api/requirements.txt
$env:POSTGRES_PORT = '55432'
$env:POSTGRES_PASSWORD = 'docmind-postgres-dev'
$env:DOCMIND_COOKIE_SECURE = 'false'
.\.venv\Scripts\python.exe -m alembic -c apps/api/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir apps/api --reload
```

Adapte les variables PostgreSQL aux valeurs de `.env` si tu les as modifiées. Avec le Compose principal, utilise le port PostgreSQL configuré dans `.env`. Une instance distante peut être configurée avec `DOCMIND_DATABASE_URL` au format `postgresql+psycopg://…`. En HTTPS, conserve le réglage Secure par défaut et fais transiter `/api` et l’interface par la même origine, comme le proxy de développement Vite.

Dans un second PowerShell, lance le frontend avec les commandes de la section Frontend puis ouvre l’adresse affichée. Tu peux t’inscrire, te connecter, retrouver ta session après rechargement et te déconnecter. Les requêtes d’authentification POST exigent l’en-tête `X-DocMind-Request: 1` pour la protection CSRF.

En local, définis `DOCMIND_TEST_DATABASE_URL` vers une base de test migrée pour activer les tests d’intégration.

L’API d’authentification est versionnée sous `/api/v1`. Les erreurs d’authentification utilisent Problem Details avec un code métier et un identifiant de requête.
