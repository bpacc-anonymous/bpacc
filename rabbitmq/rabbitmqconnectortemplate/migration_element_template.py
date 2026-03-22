import os
import shutil
import sys
from pathlib import Path

# --- CONFIGURATION ---
SOURCE_DIR = "camunda-templates"
# Chemin standard pour Camunda Modeler sur macOS
DEST_DIR = Path.home() / "Library/Application Support/camunda-modeler/resources/element-templates"

def deploy():
    # 1. Vérification de la source
    if not os.path.exists(SOURCE_DIR):
        print(f"ERREUR: Le dossier source '{SOURCE_DIR}' n'existe pas.")
        print("Avez-vous lancé 'generate_templates.py' ?")
        sys.exit(1)

    # 2. Vérification/Création de la destination
    try:
        if not DEST_DIR.exists():
            print(f"Le dossier de destination n'existe pas. Création de : {DEST_DIR}")
            DEST_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        print("ERREUR: Permission refusée. Essayez avec 'sudo'.")
        sys.exit(1)

    # 3. Déploiement (Copie)
    print(f"Déploiement des templates depuis '{SOURCE_DIR}' vers Camunda Modeler...")
    
    files = [f for f in os.listdir(SOURCE_DIR) if f.endswith('.json')]
    
    if not files:
        print("Aucun fichier JSON trouvé à déployer.")
        sys.exit(0)

    count = 0
    for filename in files:
        src_file = os.path.join(SOURCE_DIR, filename)
        dest_file = DEST_DIR / filename
        
        try:
            shutil.copy2(src_file, dest_file)
            print(f"  [OK] {filename}")
            count += 1
        except Exception as e:
            print(f"  [ERREUR] Impossible de copier {filename}: {e}")

    print("-" * 30)
    print(f"SUCCÈS : {count} templates déployés.")
    print("Veuillez REDÉMARRER Camunda Modeler pour voir les changements.")

if __name__ == "__main__":
    deploy()