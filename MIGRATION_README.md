# Migration vers PostgreSQL

## Problème résolu

Le problème était que SQLite stocke les données dans un fichier local (`cvbien.db`) qui est **effacé** à chaque redéploiement de Railway. C'est pourquoi les utilisateurs "disparaissaient" après chaque déploiement.

## Solution

Migration vers PostgreSQL qui est une base de données persistante sur Railway.

## Étapes de migration

### 1. Configuration Railway

1. Allez sur votre projet Railway
2. Ajoutez un service PostgreSQL :
   - Cliquez sur "New Service" → "Database" → "PostgreSQL"
3. Railway créera automatiquement la variable `DATABASE_URL`

### 2. Déploiement

Le code est déjà configuré pour utiliser PostgreSQL. Railway va :
- Installer les dépendances PostgreSQL (`psycopg2-binary`, `sqlalchemy`)
- Utiliser `main_postgres.py` au lieu de `main_auth.py`
- Se connecter automatiquement à PostgreSQL via `DATABASE_URL`

### 3. Migration des données (optionnel)

Si vous voulez migrer les données existantes de SQLite vers PostgreSQL :

```bash
# Localement (si vous avez une copie de cvbien.db)
python migrate_to_postgres.py
```

## Avantages

✅ **Persistance des données** - Les utilisateurs ne disparaissent plus
✅ **Performance** - PostgreSQL est plus rapide que SQLite
✅ **Scalabilité** - Peut gérer plus d'utilisateurs simultanés
✅ **Fiabilité** - Base de données professionnelle

## Structure des tables

Les tables sont identiques à SQLite mais avec PostgreSQL :
- `users` - Utilisateurs et leurs crédits
- `generated_cvs` - CV générés
- `transactions` - Historique des paiements et consommations

## Vérification

Après déploiement, vérifiez que :
1. L'API fonctionne : `https://votre-url.railway.app/version`
2. Les utilisateurs persistent après redéploiement
3. Les paiements fonctionnent correctement

## Rollback

Si problème, vous pouvez revenir à SQLite en :
1. Changeant `railway.json` pour utiliser `main_auth.py`
2. Supprimant les dépendances PostgreSQL de `requirements.txt`
