# Android TV Remote (Epson fix)

Version modifiée de l'intégration officielle **Android TV Remote** de Home Assistant
(basée sur Home Assistant 2026.9.4), pour les appareils qui passent en boucle de
« éteint » à « indisponible », typiquement les **vidéoprojecteurs Epson** en veille.

Elle remplace l'intégration officielle (même domaine `androidtv_remote`) : vos
appareils déjà configurés, entités et automatisations sont conservés.

## Le problème

La bibliothèque `androidtvremote2` coupe la connexion si l'appareil n'envoie aucun
message pendant 16 secondes (normalement il envoie un ping toutes les 5 s). En veille,
certains appareils acceptent la connexion mais n'envoient plus de pings : la connexion
est coupée, l'entité passe en **indisponible**, puis la reconnexion réussit
immédiatement et l'entité repasse en **éteint**, à l'infini.

## Ce que change cette version

Deux options sont ajoutées (Paramètres → Appareils et services → Android TV Remote →
**Configurer**) :

| Option | Défaut | Effet |
| --- | --- | --- |
| **Délai avant indisponibilité** | 60 s | Après une perte de connexion, les entités gardent leur dernier état pendant ce délai. Si l'appareil se reconnecte entre-temps, rien ne change. `0` = comportement d'origine. |
| **Délai d'inactivité** | 16 s | Temps sans message de l'appareil avant de considérer la connexion perdue (valeur codée en dur dans la bibliothèque d'origine). Avec plusieurs appareils, la plus grande valeur est utilisée. |

Les messages « Disconnected from / Reconnected to » passent aussi du niveau `info` au
niveau `debug` pour ne plus remplir le journal.

Tout le reste (appairage, télécommande, media player, applications, etc.) est
identique à l'intégration officielle.

## Installation via HACS

1. HACS → menu ⋮ → **Dépôts personnalisés**.
2. Ajoutez l'URL de ce dépôt, catégorie **Intégration**.
3. Installez **Android TV Remote (Epson fix)**, puis redémarrez Home Assistant.

Pour revenir à l'intégration officielle : désinstallez-la depuis HACS et redémarrez.

## Réglages conseillés

- Commencez avec les valeurs par défaut (60 s / 16 s). Le cycle de déconnexion/reconnexion
  est alors masqué.
- Si vous voyez encore des passages en indisponible, augmentez le **délai avant
  indisponibilité** (ex. 120 s).
- Le **délai d'inactivité** peut être augmenté (ex. 60 s) pour réduire le nombre de
  reconnexions, au prix d'une détection plus lente d'une vraie coupure.

## Diagnostic

```yaml
logger:
  default: warning
  logs:
    androidtvremote2: debug
    custom_components.androidtv_remote: debug
```

## Tests

```bash
pip install pytest-homeassistant-custom-component androidtvremote2
pytest
```

## Licence

Code dérivé de [Home Assistant Core](https://github.com/home-assistant/core),
sous licence Apache 2.0 (voir `LICENSE.md`).
