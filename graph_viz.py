import sys
import os
import datetime
from pathlib import Path

# --- Gestion du chemin pour les imports (si nécessaire) ---
# Permet de remonter d'un dossier pour trouver le module 'bpacc'
project_root = os.path.abspath(os.path.join(os.getcwd(), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import de ton graphe
from bpacc.bp_layers.B1.graph import b1_graph

# --- Configuration des dossiers de sortie ---
OUTPUT_DIR = Path("bpacc/bp_layers/B1/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

timestamp   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
png_path    = OUTPUT_DIR / f"b1_graph_{timestamp}.png"
latest_path = OUTPUT_DIR / "b1_graph_latest.png"

print("\n=== BPACC B1 — Graph Visualizer ===")
print("  Génération du graphe via Mermaid (Zéro dépendance locale)...")

try:
    # C'est ici qu'est la magie : on utilise draw_mermaid_png()
    # Pas besoin de Graphviz installé sur ton système !
    png_data = b1_graph.get_graph(xray=True).draw_mermaid_png()

    # Sauvegarde de la version horodatée
    with open(png_path, "wb") as f:
        f.write(png_data)

    # Sauvegarde de la version 'latest' (écrase la précédente)
    with open(latest_path, "wb") as f:
        f.write(png_data)

    print(f"  ✓ Graphe sauvegardé → {png_path}")
    print(f"  ✓ Dernière version  → {latest_path}")
    print(f"  Taille              : {len(png_data) / 1024:.1f} KB\n")

except Exception as e:
    print(f"  ✗ Erreur lors de la génération : {e}")