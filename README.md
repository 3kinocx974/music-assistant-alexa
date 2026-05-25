# Music Assistant → Alexa (sans Docker)

> Contrôler la lecture de [Music Assistant](https://music-assistant.io) sur des enceintes Amazon Echo, **sans Docker externe**, via un add-on Home Assistant et une fonction AWS Lambda gratuite.

Basé sur le travail de [timlaing/music-assistant-alexa-api](https://github.com/timlaing/music-assistant-alexa-api) et [alams154/music-assistant-alexa-skill-prototype](https://github.com/alams154/music-assistant-alexa-skill-prototype).

---

## Sommaire

- [Architecture](#architecture)
- [Prérequis](#prérequis)
- [Étape 1 — Add-on Home Assistant](#étape-1--add-on-home-assistant)
- [Étape 2 — Cloudflare tunnel](#étape-2--cloudflare-tunnel)
- [Étape 3 — Music Assistant](#étape-3--music-assistant)
- [Étape 4 — Skill Alexa](#étape-4--skill-alexa)
- [Étape 5 — AWS Lambda](#étape-5--aws-lambda)
- [Étape 6 — Finaliser la Skill](#étape-6--finaliser-la-skill)
- [Étape 7 — Vérification](#étape-7--vérification)
- [Étape 8 — Automation HA](#étape-8--automation-ha)
- [Dépannage](#dépannage)

---

## Architecture

```
Commande vocale → Amazon Cloud → Skill Alexa (Developer Console)
                                         │
                                  AWS Lambda (eu-west-1)
                              (handler Python / ASK SDK)
                                         │
                              HTTPS (Cloudflare tunnel)
                                         │
                     Add-on HA : timlaing/music-assistant-alexa-api
                              (port 5000, GET /ma/latest-url)
                                         │
                             Music Assistant (port 8097)
                                         │
                              HTTPS (Cloudflare tunnel)
                                         ▼
                                  Echo Dot / Echo Show
```

| Composant | Rôle |
|---|---|
| **Add-on timlaing** | Reçoit l'URL du stream de Music Assistant (`POST /ma/push-url`) et la sert à la Lambda (`GET /ma/latest-url`) |
| **AWS Lambda** | Reçoit les requêtes Alexa, interroge l'add-on, répond avec une directive `AudioPlayer.Play` |
| **Cloudflare tunnel** | Expose l'add-on (port 5000) et Music Assistant (port 8097) en HTTPS public |

---

## Prérequis

- Home Assistant OS opérationnel
- [Music Assistant](https://music-assistant.io) installé dans HA
- Un domaine connecté à Cloudflare avec tunnel actif
- [Alexa Media Player](https://github.com/alandtse/alexa_media_player) (HACS) installé dans HA
- Un compte [Amazon Developer](https://developer.amazon.com) (gratuit)
- Un compte [AWS](https://aws.amazon.com) (gratuit — Lambda inclus dans le free tier)

---

## Étape 1 — Add-on Home Assistant

### 1.1 Ajouter le dépôt

**Paramètres → Modules complémentaires → Boutique → ⋮ → Dépôts**

```
https://github.com/timlaing/music-assistant-alexa-api
```

Rafraîchir la boutique → **Music Assistant Alexa API** → **Installer**.

### 1.2 Configurer l'add-on

Dans l'onglet **Configuration** :

```yaml
ma_hostname: https://stream.mondomaine.com   # sous-domaine stream MA (créé étape 2)
api_username: mon-utilisateur-api            # identifiant de votre choix
api_password: mon-mot-de-passe-api           # laisser vide = généré automatiquement
aws_default_region: eu-west-1
```

> Si vous laissez `api_password` vide, récupérez le mot de passe généré dans l'onglet **Journal** après le premier démarrage.

**Démarrer l'add-on.**

---

## Étape 2 — Cloudflare tunnel

Dans **Cloudflare Zero Trust → Réseaux → Tunnels → votre tunnel → Routes des applications publiées**, créer **deux routes** :

| Sous-domaine | Service | Usage |
|---|---|---|
| `alexa-api.mondomaine.com` | `http://IP_HA:5000` | Add-on (API Skill) |
| `stream.mondomaine.com` | `http://IP_HA:8097` | Music Assistant (audio) |

> Remplacer `IP_HA` par l'IP locale de votre serveur Home Assistant.  
> Laisser les enregistrements DNS en mode **Proxied** (nuage orange) — obligatoire pour les tunnels Cloudflare.

### Règle WAF

Dans **Cloudflare → votre domaine → Sécurité → WAF → Règles personnalisées**, créer une règle :

```
(http.user_agent contains "Alexa") or
(http.user_agent contains "AmazonAlexa") or
(http.host eq "alexa-api.mondomaine.com")
```

**Action : Skip (Ignorer)**

---

## Étape 3 — Music Assistant

### 3.1 Provider Alexa

**Music Assistant → Paramètres → Player Providers → + → Alexa**

| Champ | Valeur |
|---|---|
| API URL | `http://homeassistant:5000` |
| API Basic Auth Username | valeur de `api_username` (étape 1) |
| API Basic Auth Password | valeur de `api_password` (étape 1) |

Cliquer **Authenticate with Amazon** et compléter l'authentification OAuth.

### 3.2 Published IP address

**Music Assistant → Paramètres → Système → Flux → Published IP address**

```
stream.mondomaine.com
```

> Sans `https://` — Music Assistant compose l'URL complète automatiquement.

---

## Étape 4 — Skill Alexa

Sur [developer.amazon.com/alexa/console/ask](https://developer.amazon.com/alexa/console/ask) → **Create Skill** :

| Champ | Valeur |
|---|---|
| Skill name | `Music Assistant` |
| Primary locale | `English (US)` ou `French (FR)` |
| Type | Custom |
| Hosting | Provision your own |

### 4.1 Invocation Name

**Build → Invocation** :

```
music assistant
```

### 4.2 Interaction Model

**Build → Interaction Model → JSON Editor** — coller le contenu de [`interaction_model_en.json`](interaction_model_en.json) (anglais) ou [`interaction_model_fr.json`](interaction_model_fr.json) (français).

### 4.3 Interfaces

**Build → Interfaces** — activer :

- ✅ **Audio Player**
- ✅ **Alexa Presentation Language (APL)**

### 4.4 Endpoint

Laisser en attente — l'ARN Lambda sera ajouté à l'étape 6.

---

## Étape 5 — AWS Lambda

> ⚠️ La région **eu-west-1 (Irlande)** est obligatoire pour les Skills Alexa ciblant l'Europe. Les régions non supportées (ex : eu-west-3 Paris) empêchent le déclenchement de la Skill.

### 5.1 Créer la fonction

Sur [console.aws.amazon.com/lambda](https://console.aws.amazon.com/lambda) — sélectionner la région **Europe (Irlande) eu-west-1** :

- **Créer une fonction** → "Créer depuis zéro"
- Nom : `music-assistant-alexa`
- Runtime : **Python 3.12**
- Architecture : x86_64

### 5.2 Déployer le code

Cloner ce dépôt, puis depuis le dossier `lambda/` :

```bash
pip install ask-sdk-core --target . --break-system-packages
zip -r ../lambda.zip . -x "*.pyc" -x "*__pycache__*"
```

Dans la console Lambda → **Code → Charger depuis → .zip** → uploader `lambda.zip`.

### 5.3 Variables d'environnement

**Configuration → Variables d'environnement** :

| Clé | Valeur |
|---|---|
| `API_URL` | `https://alexa-api.mondomaine.com` |
| `API_USERNAME` | valeur de `api_username` (étape 1) |
| `API_PASSWORD` | valeur de `api_password` (étape 1) |
| `STREAM_URL` | `https://stream.mondomaine.com` |

### 5.4 Trigger Alexa

**Configuration → Déclencheurs → Ajouter un déclencheur → Alexa**

Coller le **Skill ID** visible dans la Developer Console → **Build → Endpoint → "Your Skill ID"**.

### 5.5 Récupérer l'ARN

En haut à droite de la page Lambda, copier l'ARN :

```
arn:aws:lambda:eu-west-1:XXXXXXXXXXXX:function:music-assistant-alexa
```

---

## Étape 6 — Finaliser la Skill

Dans la Developer Console → **Build → Endpoint** :

- Sélectionner **AWS Lambda ARN**
- **Default Region** : coller l'ARN (étape 5.5)
- **Europe and India** : coller le même ARN

Cliquer **Save Endpoints** puis **Build Skill**.

Dans l'onglet **Test** → passer le switch sur **Development**.

---

## Étape 7 — Vérification

### Simulateur Alexa

Dans **Test → Alexa Simulator** → taper `music assistant`.

Le **JSON Output** doit contenir :

```json
{
  "type": "AudioPlayer.Play",
  "audioItem": {
    "stream": {
      "url": "https://stream.mondomaine.com/single/..."
    }
  }
}
```

### Test vocal

Lancer une lecture dans Music Assistant sur un Echo, puis dire :

> **"Alexa, ouvre Music Assistant"**

L'Echo doit jouer le stream en cours.

---

## Étape 8 — Automation HA

Cette automation relance automatiquement la Skill sur l'Echo quand Music Assistant change de piste ou de station.

> **Prérequis :** [Alexa Media Player](https://github.com/alandtse/alexa_media_player) installé dans HA.

**Comment trouver les bons `entity_id` :**
- Player Music Assistant : **Outils de développement → États** → entité avec `app_id: music_assistant` et `mass_player_type: player`
- Echo Alexa Media Player : **Paramètres → Appareils et services → Alexa Media Player → Entités**

Voir le fichier [`automation_ha.yaml`](automation_ha.yaml) — remplacer :
- `VOTRE_PLAYER_MUSIC_ASSISTANT` → entity_id du player Music Assistant (ex : `media_player.salon`)
- `VOTRE_ECHO` → suffixe du service notify (ex : `salon` pour `notify.alexa_media_salon`)

---

## Récapitulatif des URLs

| Usage | URL |
|---|---|
| Add-on API — accès public (Lambda → add-on) | `https://alexa-api.mondomaine.com` |
| Add-on API — accès local (Music Assistant → add-on) | `http://homeassistant:5000` |
| Stream audio — accès public (Alexa → stream) | `https://stream.mondomaine.com` |

---

## Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `Unable to reach the requested skill` | Lambda dans la mauvaise région AWS | Recréer la Lambda en `eu-west-1` |
| JSON Output vide dans le simulateur | Endpoint non sauvegardé | Save Endpoints → Build Skill |
| Stream URL en `http://IP:8097` | Published IP address mal configuré | Mettre `stream.mondomaine.com` sans `https://` |
| `502 Bad Gateway` | Cloudflare ne joint pas le port 5000 | Vérifier l'IP dans la route Cloudflare |
| `401 Unauthorized` sur l'add-on | Mauvais identifiants | Vérifier `API_USERNAME` / `API_PASSWORD` |
| Aucun Echo détecté dans MA | Authentification Amazon non effectuée | Cliquer "Authenticate with Amazon" dans MA |
| Skill répond mais ne joue rien | Pas de stream actif dans MA | Lancer une lecture dans MA d'abord |
| `Access denied` depuis Cloudflare | Règle WAF manquante | Créer la règle WAF (étape 2) |

---

## Licence

MIT — contributions bienvenues.
