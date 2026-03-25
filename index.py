import os

# ⚠️ Mets ici le chemin vers ton dossier
folder = "/Users/ton_nom/Desktop/test_files"

files = os.listdir(folder)

for index, file in enumerate(files, start=1):
    old_path = os.path.join(folder, file)

    # Vérifie que c’est un fichier (pas un dossier)
    if os.path.isfile(old_path):
        new_name = f"Facture_{index:03}.pdf"
        new_path = os.path.join(folder, new_name)

        os.rename(old_path, new_path)
        print(f"{file} → {new_name}")

print("Renaming completed ✅")