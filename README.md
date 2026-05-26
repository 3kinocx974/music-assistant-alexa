# Music Assistant → Alexa (Docker-free)

> Control [Music Assistant](https://music-assistant.io) playback on Amazon Echo devices, **without any Docker container**, using a Home Assistant add-on and a free AWS Lambda function.

Based on the work of [timlaing/music-assistant-alexa-api](https://github.com/timlaing/music-assistant-alexa-api) and [alams154/music-assistant-alexa-skill-prototype](https://github.com/alams154/music-assistant-alexa-skill-prototype).

> **⚠️ Important:** This guide uses a **modified fork** of the timlaing add-on that adds the `/alexa/intents` route, allowing Music Assistant to control playback (stop, pause, play, next, previous) on Echo devices. Use [3kinocx974/Alexa-api](https://github.com/3kinocx974/Alexa-api) instead of the original timlaing repository.

---

## Table of Contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Step 1 — Home Assistant Add-on (modified fork)](#step-1--home-assistant-add-on-modified-fork)
- [Step 2 — Cloudflare Tunnel](#step-2--cloudflare-tunnel)
- [Step 3 — Music Assistant](#step-3--music-assistant)
- [Step 4 — Alexa Skill](#step-4--alexa-skill)
- [Step 5 — AWS Lambda](#step-5--aws-lambda)
- [Step 6 — Finalize the Skill](#step-6--finalize-the-skill)
- [Step 7 — Verification](#step-7--verification)
- [Step 8 — HA Automation](#step-8--ha-automation)
- [Troubleshooting](#troubleshooting)

---

## Architecture

```
Voice command → Amazon Cloud → Alexa Skill (Developer Console)
                                         │
                                  AWS Lambda (eu-west-1)
                              (Python handler / ASK SDK)
                                         │
                              HTTPS (Cloudflare tunnel)
                                         │
                  HA Add-on: 3kinocx974/Alexa-api (modified fork)
                    (port 5000, /ma/push-url, /ma/latest-url,
                               /alexa/intents)
                                         │
                             Music Assistant (port 8097)
                                         │
                              HTTPS (Cloudflare tunnel)
                                         ▼
                                  Echo Dot / Echo Show
```

| Component | Role |
|---|---|
| **Add-on (fork)** | Receives stream URL from Music Assistant (`POST /ma/push-url`), serves it to Lambda (`GET /ma/latest-url`), and receives playback commands (`POST /alexa/intents`) |
| **AWS Lambda** | Receives Alexa requests, queries the add-on, responds with an `AudioPlayer.Play` directive |
| **Cloudflare tunnel** | Exposes the add-on (port 5000) and Music Assistant (port 8097) over public HTTPS |

### What's different from the original add-on

The original timlaing add-on does not handle the `/alexa/intents` route that Music Assistant uses to send playback control commands (stop, pause, play, next, previous). This fork adds that route and connects it to the Home Assistant API to control Alexa `media_player` entities.

---

## Prerequisites

- Home Assistant OS up and running
- [Music Assistant](https://music-assistant.io) installed in HA
- A domain connected to Cloudflare with an active tunnel
- [Alexa Media Player](https://github.com/alandtse/alexa_media_player) (HACS) installed in HA
- A free [Amazon Developer](https://developer.amazon.com) account
- A free [AWS](https://aws.amazon.com) account (Lambda is included in the free tier)

---

## Step 1 — Home Assistant Add-on (modified fork)

> Use the **modified fork** `3kinocx974/Alexa-api`, not the original timlaing repository.

### 1.1 Add the repository

**Settings → Add-ons → Add-on Store → ⋮ → Repositories**

```
https://github.com/3kinocx974/Alexa-api
```

Refresh the store → **Music Assistant Alexa API** → **Install**.

### 1.2 Configure the add-on

In the **Configuration** tab:

```yaml
ma_hostname: https://stream.yourdomain.com   # stream subdomain (created in step 2)
api_username: my-api-user                    # username of your choice
api_password: my-fixed-password             # set a fixed password (do not leave empty)
aws_default_region: eu-west-1
```

> **Important:** Do not leave `api_password` empty — the add-on would generate a new password on every restart, breaking the sync with Music Assistant.

**Start the add-on.**

---

## Step 2 — Cloudflare Tunnel

In **Cloudflare Zero Trust → Networks → Tunnels → your tunnel → Public Hostnames**, create **two routes**:

| Subdomain | Service | Purpose |
|---|---|---|
| `alexa-api.yourdomain.com` | `http://HA_IP:5000` | Add-on (Skill API) |
| `stream.yourdomain.com` | `http://HA_IP:8097` | Music Assistant (audio stream) |

> Replace `HA_IP` with the local IP address of your Home Assistant server.  
> Keep DNS records in **Proxied** mode (orange cloud) — required for Cloudflare tunnels.

### WAF Rule

In **Cloudflare → your domain → Security → WAF → Custom Rules**, create a rule:

```
(http.user_agent contains "Alexa") or
(http.user_agent contains "AmazonAlexa") or
(http.host eq "alexa-api.yourdomain.com")
```

**Action: Skip**

---

## Step 3 — Music Assistant

### 3.1 Alexa Player Provider

**Music Assistant → Settings → Player Providers → + → Alexa**

| Field | Value |
|---|---|
| API URL | `http://homeassistant:5000` |
| API Basic Auth Username | value of `api_username` (step 1) |
| API Basic Auth Password | value of `api_password` (step 1) |

Click **Authenticate with Amazon** and complete the OAuth flow.

### 3.2 Published IP address

**Music Assistant → Settings → Core → Streams → Published IP address**

```
stream.yourdomain.com
```

> Without `https://` — Music Assistant builds the full URL automatically.

---

## Step 4 — Alexa Skill

On [developer.amazon.com/alexa/console/ask](https://developer.amazon.com/alexa/console/ask) → **Create Skill**:

| Field | Value |
|---|---|
| Skill name | `Music Assistant` |
| Primary locale | `English (US)` or `French (FR)` |
| Type | Custom |
| Hosting | Provision your own |

### 4.1 Invocation Name

**Build → Invocation**:

```
music assistant
```

### 4.2 Interaction Model

**Build → Interaction Model → JSON Editor** — paste the content of [`interaction_model_en.json`](interaction_model_en.json) (English) or [`interaction_model_fr.json`](interaction_model_fr.json) (French).

### 4.3 Interfaces

**Build → Interfaces** — enable:

- ✅ **Audio Player**
- ✅ **Alexa Presentation Language (APL)**

### 4.4 Endpoint

Leave pending — the Lambda ARN will be added in step 6.

---

## Step 5 — AWS Lambda

> ⚠️ The **eu-west-1 (Ireland)** region is required for Alexa Skills targeting Europe. Unsupported regions (e.g. eu-west-3 Paris) will prevent the Skill from being triggered.

### 5.1 Create the function

On [console.aws.amazon.com/lambda](https://console.aws.amazon.com/lambda) — select region **Europe (Ireland) eu-west-1**:

- **Create function** → "Author from scratch"
- Name: `music-assistant-alexa`
- Runtime: **Python 3.12**
- Architecture: x86_64

### 5.2 Deploy the code

Clone this repository, then from the `lambda/` folder:

```bash
pip install ask-sdk-core --target . --break-system-packages
zip -r ../lambda.zip . -x "*.pyc" -x "*__pycache__*"
```

In the Lambda console → **Code → Upload from → .zip** → upload `lambda.zip`.

### 5.3 Environment variables

**Configuration → Environment variables**:

| Key | Value |
|---|---|
| `API_URL` | `https://alexa-api.yourdomain.com` |
| `API_USERNAME` | value of `api_username` (step 1) |
| `API_PASSWORD` | value of `api_password` (step 1) |
| `STREAM_URL` | `https://stream.yourdomain.com` |

### 5.4 Alexa Trigger

**Configuration → Triggers → Add trigger → Alexa**

Paste the **Skill ID** visible in the Developer Console → **Build → Endpoint → "Your Skill ID"**.

### 5.5 Copy the ARN

Top right of the Lambda page, copy the ARN:

```
arn:aws:lambda:eu-west-1:XXXXXXXXXXXX:function:music-assistant-alexa
```

---

## Step 6 — Finalize the Skill

In the Developer Console → **Build → Endpoint**:

- Select **AWS Lambda ARN**
- **Default Region**: paste the ARN (step 5.5)
- **Europe and India**: paste the same ARN

Click **Save Endpoints** then **Build Skill**.

In the **Test** tab → set the switch to **Development**.

---

## Step 7 — Verification

### Alexa Simulator

In **Test → Alexa Simulator** → type `music assistant`.

The **JSON Output** should contain:

```json
{
  "type": "AudioPlayer.Play",
  "audioItem": {
    "stream": {
      "url": "https://stream.yourdomain.com/single/..."
    }
  }
}
```

### Voice test

Start playback in Music Assistant on an Echo device, then say:

> **"Alexa, open Music Assistant"**

The Echo should start playing the current stream. Stop/pause/play commands from the Music Assistant interface should also work on the Echo.

---

## Step 8 — HA Automation

This automation automatically re-launches the Skill on the Echo when Music Assistant changes track or station.

> **Prerequisite:** [Alexa Media Player](https://github.com/alandtse/alexa_media_player) installed in HA.

**How to find the right `entity_id` values:**
- Music Assistant player: **Developer Tools → States** → entity with `app_id: music_assistant` and `mass_player_type: player`
- Alexa Media Player Echo: **Settings → Devices & Services → Alexa Media Player → Entities**

See [`automation_ha.yaml`](automation_ha.yaml) — replace:
- `YOUR_MUSIC_ASSISTANT_PLAYER` → Music Assistant player entity_id (e.g. `media_player.living_room`)
- `YOUR_ECHO` → notify service suffix (e.g. `living_room` for `notify.alexa_media_living_room`)

---

## URL Summary

| Purpose | URL |
|---|---|
| Add-on API — public access (Lambda → add-on) | `https://alexa-api.yourdomain.com` |
| Add-on API — local access (Music Assistant → add-on) | `http://homeassistant:5000` |
| Audio stream — public access (Alexa → stream) | `https://stream.yourdomain.com` |

---

## Troubleshooting

| Symptom | Likely cause | Solution |
|---|---|---|
| `Unable to reach the requested skill` | Lambda in wrong AWS region | Recreate Lambda in `eu-west-1` |
| Empty JSON Output in simulator | Endpoint not saved | Save Endpoints → Build Skill |
| Stream URL shows `http://IP:8097` | Published IP address misconfigured | Set `stream.yourdomain.com` without `https://` |
| `502 Bad Gateway` | Cloudflare can't reach port 5000 | Check the IP in the Cloudflare route |
| `401 Unauthorized` on add-on | Wrong credentials | Check `API_USERNAME` / `API_PASSWORD` |
| No Echo devices detected in MA | Amazon authentication not completed | Click "Authenticate with Amazon" in MA |
| Skill responds but no audio plays | No active stream in MA | Start playback in MA first |
| `Access denied` from Cloudflare | Missing WAF rule | Create the WAF rule (step 2) |
| Stop/pause not working | Using original add-on or wrong password | Use fork `3kinocx974/Alexa-api` with a fixed password |
| Password changes on every restart | `api_password` left empty in config | Set a fixed password in the add-on configuration |

---

## License

MIT — contributions welcome.
