# DocMind AI en production

La livraison M7 regroupe le frontend compilé et le proxy Caddy dans une image, et FastAPI, Celery et Alembic dans une seconde image. Docker Compose lance PostgreSQL/pgvector, Redis, la migration, l’API, le worker et les tâches de reprise. Le proxy est le seul service publié sur l’hôte.

## Démarrer sur un serveur

Prépare un hôte Docker avec Compose, un nom DNS qui pointe vers l’hôte et un service Ollama joignable sur le réseau privé. Sur ce service, charge le modèle `qwen2.5:1.5b` ou configure `DOCMIND_OLLAMA_MODEL` pour un modèle déjà disponible. Pour les PDF, utilise un bucket S3 privé ou un volume local sur une installation à un seul hôte.

Copie `.env.production.example` vers `.env.production`, puis configure le vrai nom DNS, les deux mots de passe PostgreSQL, le modèle et le stockage. Caddy utilise le nom DNS pour obtenir son certificat. Autorise les ports publics 80 et 443. Les cookies requièrent HTTPS par défaut. La documentation Swagger est désactivée dans le Compose de production.

Depuis la racine dans PowerShell.

```powershell
Copy-Item .env.production.example .env.production
$compose = @('--env-file', '.env.production', '-f', 'compose.production.yaml')
docker compose @compose config --quiet
docker compose @compose build api gateway
docker compose @compose up -d --no-build --wait
docker compose @compose run --rm warmup
docker compose @compose ps -a
```

La migration s’exécute avant le démarrage de l’API, du worker et du relais. Une étape `migrate` terminée avec le code 0 est normale. Le service `warmup` remplit le cache MiniLM partagé. Les extraits du PDF utilisés pour répondre sont transmis au service Ollama configuré.

Pour utiliser des images publiées, renseigne `DOCMIND_API_IMAGE` et `DOCMIND_WEB_IMAGE` avec le même tag, connecte Docker à GHCR si les paquets sont privés, puis exécute `docker compose @compose pull` et `docker compose @compose up -d --no-build --wait`. Le workflow **Release images** construit et vérifie la pile, puis publie les deux images lorsque tu pousses un tag de version `v*`.

## Vérifier la mise en ligne

```powershell
python infra/production/smoke.py https://docmind.example.com
docker compose @compose logs --tail 100 api gateway worker dispatcher
docker compose @compose exec -T redis redis-cli ping
```

Remplace le domaine par celui du serveur. `/health` indique que FastAPI tourne et `/ready` vérifie la connexion PostgreSQL. Surveille aussi les échecs de migration, les erreurs du worker et les PDF qui restent longtemps en attente. Les journaux Docker sont limités à trois fichiers de 10 Mio par service.

Pour vérifier le parcours utilisateur, importe un PDF de test, attends son statut **Prêt**, pose une question et ouvre la citation. Vérifie la page citée et le texte surligné. Un succès de `/ready` seul ne valide ni Ollama ni le stockage.

L’adresse du proxy interne est fixe pour que FastAPI accepte ses en-têtes de transfert. En cas de conflit de réseau Docker, configure `DOCMIND_PROXY_SUBNET`, `DOCMIND_PROXY_DYNAMIC_RANGE` et `DOCMIND_PROXY_IP`. Choisis une adresse de proxy dans le sous-réseau, hors de la plage dynamique.

## Sauvegarder et rétablir

Avant une mise à jour, conserve les tags d’images en cours et une sauvegarde de PostgreSQL et des PDF correspondant au même point de restauration. Pour produire une sauvegarde cohérente du stockage local, mets la pile hors trafic et arrête les services qui écrivent dans PostgreSQL ou les PDF pendant la capture des deux sauvegardes.

```powershell
New-Item -ItemType Directory -Force backup | Out-Null
docker compose @compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/docmind.dump'
$database = docker compose @compose ps -q postgres
docker cp "$($database):/tmp/docmind.dump" ./backup/docmind.dump
docker compose @compose exec -T postgres rm -f /tmp/docmind.dump
```

- En stockage local, sauvegarde également le volume `documents` avec ton outil de sauvegarde de volumes Docker. En S3, conserve un instantané cohérent du bucket selon les possibilités du fournisseur.
- Vérifie une restauration sur une base PostgreSQL isolée disposant de pgvector et sur un stockage isolé. Utilise `pg_restore --exit-on-error --single-transaction --no-owner --no-privileges` sur la base vide avec le compte de migration. Le rôle applicatif doit exister sur le serveur de restauration. Il reçoit les droits sur les tables créées si tu as initialisé PostgreSQL avec le Compose M7 et utilisé le compte de migration pour la restauration.
- Pour revenir aux images précédentes, remets leurs deux tags dans `.env.production` et redémarre la pile si elles sont compatibles avec le schéma courant. En cas d’incompatibilité, restaure la sauvegarde PostgreSQL et les PDF correspondants avant de remettre la version précédente en ligne.
- `docker compose @compose down` arrête la pile en conservant ses volumes.

## Démonstration locale

Pour une préproduction sur ton PC, utilise un fichier d’environnement distinct, avec les variables suivantes en plus des deux mots de passe PostgreSQL et d’un accès au modèle.

```dotenv
DOCMIND_SITE_ADDRESS=http://:80
DOCMIND_BIND_ADDRESS=127.0.0.1
DOCMIND_HTTP_PORT=18080
DOCMIND_HTTPS_PORT=18443
DOCMIND_COOKIE_SECURE=false
DOCMIND_STORAGE_BACKEND=local
DOCMIND_OLLAMA_URL=http://host.docker.internal:11434
```

Cette configuration se limite à la boucle locale et utilise un stockage Docker indépendant. Le compte de développement appartient à une base différente. Crée un compte pour cette instance, importe un PDF et utilise les citations pour la démonstration.
