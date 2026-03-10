#!/bin/bash
# cmd.sh — Menu Reachy Care

PI="pollen@192.168.1.244"
PASS="root"
SSH_OPTS="-o StrictHostKeyChecking=no -o PasswordAuthentication=yes -o PubkeyAuthentication=no"
SSH="sshpass -p $PASS ssh $SSH_OPTS"

# Wrapper ssh pour rsync (évite les problèmes de quoting avec -e)
SSH_WRAPPER="/tmp/reachy_ssh_wrapper.sh"
cat > "$SSH_WRAPPER" << EOF
#!/bin/bash
sshpass -p $PASS ssh $SSH_OPTS "\$@"
EOF
chmod +x "$SSH_WRAPPER"
RSYNC="rsync -av -e $SSH_WRAPPER --exclude=__pycache__ --exclude=*.pyc --exclude=.git --exclude=known_faces/ --exclude=logs/"
CARE="/Users/alexandre/Galaad-Motokiyo-Ferran/reachy_care"

if ! command -v sshpass &>/dev/null; then
  echo "Installation de sshpass..."
  brew install sshpass
fi

echo ""
echo "══════════════════════════════════"
echo "       REACHY CARE — MENU"
echo "══════════════════════════════════"
echo " 1) Tout déployer et lancer"
echo " 2) Juste lancer (déjà déployé)"
echo " 3) Enrôler une personne"
echo " 4) Oublier une personne"
echo " 5) Lister les personnes connues"
echo " 6) Mode histoire"
echo " 7) Mode exposé"
echo " 8) Mode normal"
echo " 9) Voir les logs"
echo "10) Réveil manuel (simuler wake word)"
echo "11) Changer le mot de réveil"
echo "12) Changer la ville (météo + localisation)"
echo "13) Modifier le profil d'une personne"
echo "14) Configurer l'alerte email (chute)"
echo "15) Configurer l'alerte Telegram (recommandé)"
echo "16) Changer le fuseau horaire"
echo "══════════════════════════════════"
echo ""
read -p "Ton choix (1-16) : " CHOIX

case $CHOIX in

  1)
    echo "Déploiement..."
    $RSYNC $CARE/ $PI:/home/pollen/reachy_care/
    echo "Patch..."
    $SSH $PI "source /venvs/apps_venv/bin/activate && \
      cp /home/pollen/reachy_mini_conversation_app/src/reachy_mini_conversation_app/openai_realtime.py.bak /home/pollen/reachy_mini_conversation_app/src/reachy_mini_conversation_app/openai_realtime.py && \
      cp /home/pollen/reachy_mini_conversation_app/src/reachy_mini_conversation_app/main.py.bak /home/pollen/reachy_mini_conversation_app/src/reachy_mini_conversation_app/main.py && \
      python3 /home/pollen/reachy_care/patch_source.py && \
      pip install 'openwakeword>=0.6.0' --no-deps && pip install pyaudio"
    echo "Lancement..."
    $SSH -t $PI "bash /home/pollen/reachy_care/start_all.sh"
    ;;

  2)
    $SSH -t $PI "bash /home/pollen/reachy_care/start_all.sh"
    ;;

  3)
    read -p "Prénom à enrôler : " NOM
    $SSH $PI "echo '{\"cmd\": \"enroll\", \"name\": \"$NOM\"}' > /tmp/reachy_care_cmd.json"
    echo "Commande envoyée — le robot va capturer le visage de $NOM"
    ;;

  4)
    read -p "Prénom à oublier : " NOM
    $SSH $PI "echo '{\"cmd\": \"forget\", \"name\": \"$NOM\"}' > /tmp/reachy_care_cmd.json"
    echo "Commande envoyée"
    ;;

  5)
    $SSH $PI "echo '{\"cmd\": \"list_persons\"}' > /tmp/reachy_care_cmd.json"
    echo "Commande envoyée — Reachy va lister les personnes à voix haute"
    ;;

  6)
    $SSH $PI "echo '{\"cmd\": \"switch_mode\", \"mode\": \"histoire\"}' > /tmp/reachy_care_cmd.json"
    echo "Mode histoire activé"
    ;;

  7)
    read -p "Sujet de l'exposé : " SUJET
    $SSH $PI "echo '{\"cmd\": \"switch_mode\", \"mode\": \"pro\", \"topic\": \"$SUJET\"}' > /tmp/reachy_care_cmd.json"
    echo "Mode exposé activé — sujet : $SUJET"
    ;;

  8)
    $SSH $PI "echo '{\"cmd\": \"switch_mode\", \"mode\": \"normal\"}' > /tmp/reachy_care_cmd.json"
    echo "Mode normal activé"
    ;;

  9)
    $SSH -t $PI "tail -f /home/pollen/reachy_care/logs/reachy_care.log"
    ;;

  10)
    echo "Envoi du réveil manuel..."
    $SSH $PI "echo '{\"cmd\": \"wake\"}' > /tmp/reachy_care_cmd.json"
    echo "Réveil envoyé — la session va se réactiver"
    ;;

  11)
    echo ""
    echo "Mots de réveil disponibles :"
    echo "  alexa       → 'Alexa'"
    echo "  hey_jarvis  → 'Hey Jarvis'"
    echo "  hey_mycroft → 'Hey Mycroft'"
    echo "  hey_rhasspy → 'Hey Rhasspy'"
    echo ""
    echo "Pour un nom personnalisé (ex: 'Hey Reachy'), il faut entraîner"
    echo "un modèle ONNX custom — voir CONFIGURATION.md section 3."
    echo ""
    read -p "Mot de réveil choisi : " MOT
    $SSH $PI "sed -i 's/^WAKE_WORD_FALLBACK.*/WAKE_WORD_FALLBACK      = \"$MOT\"/' /home/pollen/reachy_care/config.py"
    echo "✅ Mot de réveil changé en '$MOT' — relance le robot (option 2) pour appliquer"
    ;;

  12)
    read -p "Ville (ex: Paris, France) : " VILLE
    $SSH $PI "sed -i 's/^LOCATION.*/LOCATION                = \"$VILLE\"/' /home/pollen/reachy_care/config.py"
    echo "Ville changée en '$VILLE' — relance le robot (option 2) pour appliquer"
    ;;

  13)
    read -p "Prénom de la personne : " NOM
    echo ""
    echo "Champs modifiables :"
    echo "  medications      → liste de médicaments"
    echo "  schedules        → horaires (repas, médicaments...)"
    echo "  emergency_contact → contact d'urgence"
    echo "  notes            → informations libres"
    echo ""
    read -p "Champ à modifier : " CHAMP
    read -p "Nouvelle valeur : " VALEUR
    $SSH $PI "python3 -c \"
import sys; sys.path.insert(0, '/home/pollen/reachy_care')
from modules.memory_manager import MemoryManager
import config
m = MemoryManager(str(config.KNOWN_FACES_DIR))
m.update_profile('$NOM', '$CHAMP', '$VALEUR')
print('Profil mis à jour : $NOM.$CHAMP = $VALEUR')
\""
    ;;

  14)
    echo ""
    echo "Configuration alerte email (chute détectée → email à motokiyoferran@gmail.com)"
    echo ""
    echo "⚠️  Gmail : tu dois créer un mot de passe d'application :"
    echo "   → myaccount.google.com > Sécurité > Mots de passe des applications"
    echo "   → Nom : 'Reachy Care'"
    echo ""
    read -p "Adresse Gmail expéditeur (ex: reachy.alerts@gmail.com) : " GMAIL
    read -p "Mot de passe d'application Gmail (16 caractères) : " GMAILPASS
    $SSH $PI "sed -i 's|^ALERT_EMAIL_FROM.*|ALERT_EMAIL_FROM        = \"$GMAIL\"|' /home/pollen/reachy_care/config.py && \
      sed -i 's|^ALERT_EMAIL_PASSWORD.*|ALERT_EMAIL_PASSWORD    = \"$GMAILPASS\"|' /home/pollen/reachy_care/config.py && \
      sed -i 's|^ALERT_EMAIL_ENABLED.*|ALERT_EMAIL_ENABLED     = True|' /home/pollen/reachy_care/config.py"
    echo "✅ Email configuré — relance le robot (option 2) pour appliquer"
    ;;

  15)
    echo ""
    echo "Configuration alerte Telegram (recommandé — notification instantanée)"
    echo ""
    echo "Étapes pour créer le bot (1 fois) :"
    echo "  1. Ouvre Telegram → cherche @BotFather → /newbot"
    echo "  2. Choisis un nom et un username → tu reçois un TOKEN"
    echo "  3. Envoie /start à ton nouveau bot"
    echo "  4. Va sur : https://api.telegram.org/bot<TOKEN>/getUpdates"
    echo "     → copie le 'id' dans 'chat' → c'est ton CHAT_ID"
    echo ""
    read -p "Token du bot (ex: 123456789:AAF...) : " TG_TOKEN
    read -p "Ton Chat ID (ex: 987654321) : " TG_CHAT
    $SSH $PI "sed -i 's|^TELEGRAM_BOT_TOKEN.*|TELEGRAM_BOT_TOKEN      = \"$TG_TOKEN\"|' /home/pollen/reachy_care/config.py && \
      sed -i 's|^TELEGRAM_CHAT_ID.*|TELEGRAM_CHAT_ID        = \"$TG_CHAT\"|' /home/pollen/reachy_care/config.py && \
      sed -i 's|^TELEGRAM_ENABLED.*|TELEGRAM_ENABLED        = True|' /home/pollen/reachy_care/config.py"
    echo "✅ Telegram configuré — relance le robot (option 2) pour appliquer"
    ;;

  16)
    echo ""
    echo "Fuseaux horaires courants :"
    echo "  Europe/Paris        → France métropolitaine"
    echo "  Europe/London       → Royaume-Uni"
    echo "  America/New_York    → Est USA/Canada"
    echo "  America/Los_Angeles → Ouest USA"
    echo "  America/Toronto     → Ontario"
    echo "  Asia/Tokyo          → Japon"
    echo "  Asia/Shanghai       → Chine"
    echo "  Australia/Sydney    → Australie Est"
    echo ""
    echo "Liste complète : timedatectl list-timezones"
    echo ""
    read -p "Fuseau horaire (ex: Europe/Paris) : " TZ_VAL
    $SSH $PI "sed -i 's|^TIMEZONE.*|TIMEZONE                = \"$TZ_VAL\"|' /home/pollen/reachy_care/config.py"
    echo "✅ Fuseau horaire changé en '$TZ_VAL' — relance le robot (option 2) pour appliquer"
    ;;

  *)
    echo "Choix invalide"
    ;;

esac

echo ""
read -p "Appuie sur Entrée pour fermer..."
