# DocMind AI

Application web pour interroger des documents PDF.

Pour lancer la version actuelle, suis la section **Indexation des PDF (M3)**.

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

## Inscription et connexion (M1/M2)

Ces commandes concernent les révisions M1 et M2. À partir de M3, utilise le Compose avec pgvector décrit plus bas.

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

## Import de PDF (M2)

Mets l’environnement Python à jour avec `pip install -r apps/api/requirements.txt` dans le venv. Applique `alembic upgrade head` comme dans la section M1 pour créer la table des documents.

Pour développer sur ton PC pendant que MinIO est indisponible, définis cette variable dans le PowerShell de l’API avant de lancer Uvicorn.

```powershell
$env:DOCMIND_STORAGE_BACKEND = 'local'
```

Les PDF sont stockés dans `.docmind-data/documents`, ignoré par Git. Dans **Mes documents**, importe un PDF sans mot de passe de 20 Mio maximum. Tu peux consulter son état, le télécharger ou le supprimer. L’état initial est **En attente d’indexation**. Sous M3, le statut évolue automatiquement lorsque le worker traite le fichier.

Pour utiliser MinIO ou un autre service S3, crée un bucket privé et configure le processus de l’API. Utilise un bucket dédié et des identifiants ayant uniquement les droits de lecture, d’écriture et de suppression sur ses objets. Ne publie jamais les identifiants dans le dépôt.

```powershell
$env:DOCMIND_STORAGE_BACKEND = 's3'
$env:DOCMIND_S3_BUCKET = 'docmind-documents'
$env:DOCMIND_S3_ENDPOINT = 'http://127.0.0.1:9000'
$env:AWS_DEFAULT_REGION = 'us-east-1'
# Définis aussi AWS_ACCESS_KEY_ID et AWS_SECRET_ACCESS_KEY dans cette session.
```

Garde le même stockage pour une base donnée. Changer d’adaptateur ou de bucket n’effectue aucune migration des PDF existants.

Pour reprendre des suppressions interrompues ou nettoyer les imports interrompus depuis plus d’une heure, lance la commande suivante dans un autre PowerShell, avec la même configuration de base et de stockage que l’API. Sans `--watch`, elle effectue un seul passage.

```powershell
Set-Location apps/api
..\..\.venv\Scripts\python.exe -m app.recover_storage --watch
```

Les routes se trouvent sous `/api/v1/documents`. L’import utilise le champ multipart `file`. La liste accepte `limit` et `offset`. Les téléchargements sont servis par l’API après vérification du propriétaire.

## Indexation des PDF (M3)

M3 utilise PostgreSQL 18 avec pgvector, Redis, Celery et le modèle local `all-MiniLM-L6-v2`. Le Compose M3 expose PostgreSQL et Redis sur 55434 et 16379. Il dispose de son propre volume. Pour reprendre une base M1/M2 existante, restaure un export PostgreSQL dans la nouvelle base avant d’appliquer la migration et conserve le même stockage des PDF.

Depuis la racine du dépôt, dans PowerShell.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose -f compose.ingestion.yaml up -d --wait
.\.venv\Scripts\python.exe -m pip install -r apps/api/requirements-ingestion.txt
if (-not (Test-Path .venv-worker\Scripts\python.exe)) { py -3.14 -m venv .venv-worker }
.\.venv-worker\Scripts\python.exe -m pip install -r apps/api/requirements-worker.txt
```

Le worker Windows utilise Python 3.14 pour disposer d’ONNX Runtime. L’API utilise le venv existant. Configure les variables suivantes dans chaque terminal de l’API, du relais et du worker. Adapte les paramètres PostgreSQL aux valeurs de `.env`. L’API et le worker doivent utiliser le même stockage. Pour S3, reprends les variables de la section M2.

```powershell
$env:POSTGRES_PORT = '55434'
$env:POSTGRES_PASSWORD = 'docmind-postgres-dev'
$env:DOCMIND_BROKER_URL = 'redis://127.0.0.1:16379/0'
$env:DOCMIND_STORAGE_BACKEND = 'local'
$env:DOCMIND_COOKIE_SECURE = 'false'
```

Applique la migration, puis lance l’API depuis la racine.

```powershell
.\.venv\Scripts\python.exe -m alembic -c apps/api/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir apps/api --reload
```

Dans un deuxième terminal, démarre le relais.

```powershell
Set-Location apps/api
..\..\.venv\Scripts\python.exe -m app.ingestion_dispatcher
```

Dans un troisième terminal, démarre le worker. Le premier traitement met en cache les poids publics dans `.docmind-data/models`. Le texte des PDF est traité sur la machine.

```powershell
Set-Location apps/api
..\..\.venv-worker\Scripts\python.exe -m celery -A app.celery_app:celery worker --pool=solo --concurrency=1 --loglevel=info
```

Lance le frontend dans un autre terminal. Importe un PDF avec du texte sélectionnable et attends le statut **Prêt**. Chaque fragment conserve son numéro de page et un vecteur de 384 dimensions. La limite est de 500 pages et 2 000 fragments par PDF. Les PDF numérisés sans couche texte affichent un échec explicite. L’OCR est hors périmètre de M3.

Les travaux restent dans PostgreSQL si Redis est indisponible. Un échec temporaire déclenche jusqu’à trois tentatives au total. Une relance manuelle crée un nouveau travail. Les nouveaux fragments sont enregistrés dans la même transaction que le passage à `READY`. La migration ajoute un travail pour chaque PDF déjà importé au statut `UPLOADED`.
